from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import torch
from rdkit import Chem, RDLogger
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset


RDLogger.DisableLog("rdApp.*")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREVIEW_PATH = ROOT / "data" / "baselite_smiles_v1" / "training_template_preview.jsonl"
DEFAULT_CONFIG_PATH = ROOT / "configs" / "stage_b_restore_aug_full_20epoch_bf16.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "stage_b_restore_aug_full_20epoch"

EPOCH_METRICS_JSONL = "epoch_metrics.jsonl"
EPOCH_METRICS_CSV = "epoch_metrics.csv"
QUICK_EVAL_METRICS_JSONL = "quick_eval_metrics.jsonl"
EPOCH_METRIC_CSV_FIELDS = (
    "checkpoint_name",
    "checkpoint_epoch",
    "checkpoint_optimizer_step",
    "checkpoint_recent_train_loss",
    "checkpoint_epoch_train_loss_mean",
    "sample_count",
    "decoded_sample_count",
    "loss",
    "token_accuracy",
    "exact_string_match",
    "rdkit_validity",
    "two_attachment_validity",
    "canonical_match",
    "early_stopping_metric",
    "early_stopping_mode",
    "early_stopping_current",
    "early_stopping_best",
    "early_stopping_best_checkpoint",
    "early_stopping_wait",
    "early_stopping_stop_training",
    "early_stopping_reason",
)


@dataclass(frozen=True)
class StageBConfig:
    preview_path: str = str(DEFAULT_PREVIEW_PATH)
    output_dir: str = str(DEFAULT_OUTPUT_DIR)
    max_seq_len_restore_label: int = 512
    max_epochs: int = 1
    per_device_train_batch_size: int = 1
    per_device_eval_batch_size: int = 1
    gradient_accumulation_steps: int = 16
    quick_eval_every_steps: int = 100
    quick_eval_samples: int = 128
    quick_eval_decode_samples: int = 16
    checkpoint_at_epoch_end: bool = False
    checkpoint_every_steps: int = 0
    checkpoint_eval_samples: int = 128
    checkpoint_eval_decode_samples: int = 32
    early_stopping_enabled: bool = False
    early_stopping_metric: str = "loss"
    early_stopping_mode: str = "min"
    early_stopping_patience: int = 4
    early_stopping_min_delta: float = 0.001
    early_stopping_min_epochs: int = 8
    early_stopping_monitor_only: bool = False
    eval_decode_samples: int = 64
    formal_eval_full_decode: bool = False
    learning_rate_lora: float = 1.0e-4
    learning_rate_restore_head: float = 5.0e-5
    weight_decay: float = 0.01
    max_grad_norm: float = 1.0
    lora_rank: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    lora_target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")
    restore_hidden_size: int = 512
    restore_num_layers: int = 2
    restore_num_attention_heads: int = 8
    restore_dropout: float = 0.05
    precision: str = "bf16"
    seed: int = 42


@dataclass
class RestoreBatch:
    input_ids_view1: torch.Tensor
    attention_mask_view1: torch.Tensor
    restore_labels: torch.Tensor
    restore_label_mask: torch.Tensor
    record_ids: list[str]
    splits: list[str]
    view_ids: list[str]
    augmentation_strategies: list[str]
    text_view_1_strategies: list[str]
    text_view_1: list[str]
    canonical_smiles: list[str]
    target_texts: list[str]

    def to(self, device: torch.device | str) -> "RestoreBatch":
        return RestoreBatch(
            input_ids_view1=self.input_ids_view1.to(device),
            attention_mask_view1=self.attention_mask_view1.to(device),
            restore_labels=self.restore_labels.to(device),
            restore_label_mask=self.restore_label_mask.to(device),
            record_ids=self.record_ids,
            splits=self.splits,
            view_ids=self.view_ids,
            augmentation_strategies=self.augmentation_strategies,
            text_view_1_strategies=self.text_view_1_strategies,
            text_view_1=self.text_view_1,
            canonical_smiles=self.canonical_smiles,
            target_texts=self.target_texts,
        )


class StageAPreviewDataset(Dataset):
    def __init__(self, preview_path: Path | str, split: str) -> None:
        self.preview_path = Path(preview_path)
        self.split = split
        self.rows: list[dict[str, Any]] = []
        with self.preview_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("split") != split:
                    continue
                self._validate_row(row, line_no)
                self.rows.append(row)

    def _validate_row(self, row: dict[str, Any], line_no: int) -> None:
        required = [
            "record_id",
            "canonical_smiles",
            "input_ids_view1",
            "attention_mask_view1",
            "restore_labels",
            "restore_label_mask",
        ]
        for field in required:
            if field not in row:
                raise ValueError(f"{self.preview_path}:{line_no}: missing {field}")
        if "text_view_2" in row:
            raise ValueError(f"{self.preview_path}:{line_no}: Stage B restore-only data must not contain text_view_2")

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self.rows[index]


def collate_restore_records(
    records: list[dict[str, Any]],
    *,
    pad_token_id: int,
    label_pad_token_id: int,
) -> RestoreBatch:
    if not records:
        raise ValueError("cannot collate an empty batch")

    max_input_len = max(len(row["input_ids_view1"]) for row in records)
    max_label_len = max(len(row["restore_labels"]) for row in records)

    input_ids: list[list[int]] = []
    attention_masks: list[list[int]] = []
    labels: list[list[int]] = []
    label_masks: list[list[bool]] = []
    record_ids: list[str] = []
    splits: list[str] = []
    view_ids: list[str] = []
    augmentation_strategies: list[str] = []
    text_view_1_strategies: list[str] = []
    text_view_1: list[str] = []
    canonical_smiles: list[str] = []
    target_texts: list[str] = []

    for row in records:
        input_len = len(row["input_ids_view1"])
        label_len = len(row["restore_labels"])
        input_pad = max_input_len - input_len
        label_pad = max_label_len - label_len

        input_ids.append([int(token_id) for token_id in row["input_ids_view1"]] + [pad_token_id] * input_pad)
        attention_masks.append([int(value) for value in row["attention_mask_view1"]] + [0] * input_pad)
        labels.append([int(token_id) for token_id in row["restore_labels"]] + [label_pad_token_id] * label_pad)
        label_masks.append([bool(value) for value in row["restore_label_mask"]] + [False] * label_pad)
        record_ids.append(str(row["record_id"]))
        splits.append(str(row.get("split", "")))
        view_ids.append(str(row.get("view_id", "identity")))
        augmentation_strategies.append(str(row.get("augmentation_strategy", "identity")))
        text_view_1_strategies.append(str(row.get("text_view_1_strategy", "")))
        text_view_1.append(str(row.get("text_view_1", row.get("input_text_view1", ""))))
        canonical_smiles.append(str(row["canonical_smiles"]))
        target_texts.append(str(row.get("target_text", "")))

    return RestoreBatch(
        input_ids_view1=torch.tensor(input_ids, dtype=torch.long),
        attention_mask_view1=torch.tensor(attention_masks, dtype=torch.long),
        restore_labels=torch.tensor(labels, dtype=torch.long),
        restore_label_mask=torch.tensor(label_masks, dtype=torch.bool),
        record_ids=record_ids,
        splits=splits,
        view_ids=view_ids,
        augmentation_strategies=augmentation_strategies,
        text_view_1_strategies=text_view_1_strategies,
        text_view_1=text_view_1,
        canonical_smiles=canonical_smiles,
        target_texts=target_texts,
    )


def shift_restore_labels_right(
    labels: torch.Tensor,
    label_mask: torch.Tensor,
    *,
    decoder_start_token_id: int,
    pad_token_id: int,
) -> torch.Tensor:
    shifted = torch.full_like(labels, fill_value=pad_token_id)
    if labels.shape[1] == 0:
        return shifted
    shifted[:, 0] = torch.where(
        label_mask[:, 0],
        torch.full_like(labels[:, 0], fill_value=decoder_start_token_id),
        torch.full_like(labels[:, 0], fill_value=pad_token_id),
    )
    if labels.shape[1] > 1:
        shifted[:, 1:] = torch.where(label_mask[:, 1:], labels[:, :-1], torch.full_like(labels[:, 1:], fill_value=pad_token_id))
    return shifted


def masked_cross_entropy(logits: torch.Tensor, labels: torch.Tensor, label_mask: torch.Tensor) -> torch.Tensor:
    active = label_mask.reshape(-1)
    if not bool(active.any()):
        raise ValueError("restore_label_mask has no active positions")
    flat_logits = logits.reshape(-1, logits.shape[-1])[active]
    flat_labels = labels.reshape(-1)[active]
    return F.cross_entropy(flat_logits, flat_labels)


class RestoreCrossAttentionHead(nn.Module):
    def __init__(
        self,
        *,
        vocab_size: int,
        hidden_size: int,
        num_layers: int,
        num_attention_heads: int,
        dropout: float,
        pad_token_id: int,
        decoder_start_token_id: int,
        max_target_positions: int = 512,
        encoder_hidden_size: int | None = None,
    ) -> None:
        super().__init__()
        self.vocab_size = vocab_size
        self.hidden_size = hidden_size
        self.pad_token_id = pad_token_id
        self.decoder_start_token_id = decoder_start_token_id
        self.encoder_hidden_size = encoder_hidden_size or hidden_size
        self.encoder_projection = (
            nn.Identity()
            if self.encoder_hidden_size == hidden_size
            else nn.Linear(self.encoder_hidden_size, hidden_size)
        )
        self.token_embedding = nn.Embedding(vocab_size, hidden_size, padding_idx=pad_token_id)
        self.position_embedding = nn.Embedding(max_target_positions, hidden_size)
        layer = nn.TransformerDecoderLayer(
            d_model=hidden_size,
            nhead=num_attention_heads,
            dim_feedforward=hidden_size * 4,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.decoder = nn.TransformerDecoder(layer, num_layers=num_layers)
        self.final_layer_norm = nn.LayerNorm(hidden_size)
        self.lm_head = nn.Linear(hidden_size, vocab_size, bias=False)

    def forward(
        self,
        decoder_input_ids: torch.Tensor,
        encoder_hidden_states: torch.Tensor,
        encoder_attention_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        seq_len = decoder_input_ids.shape[1]
        positions = torch.arange(seq_len, device=decoder_input_ids.device).unsqueeze(0)
        hidden = self.token_embedding(decoder_input_ids) + self.position_embedding(positions)
        causal_mask = torch.triu(
            torch.ones((seq_len, seq_len), dtype=torch.bool, device=decoder_input_ids.device),
            diagonal=1,
        )
        memory_key_padding_mask = None
        if encoder_attention_mask is not None:
            memory_key_padding_mask = encoder_attention_mask == 0
        target_key_padding_mask = None
        encoder_hidden_states = encoder_hidden_states.to(dtype=self.token_embedding.weight.dtype)
        projected_encoder_hidden_states = self.encoder_projection(encoder_hidden_states)
        decoded = self.decoder(
            tgt=hidden,
            memory=projected_encoder_hidden_states,
            tgt_mask=causal_mask,
            tgt_key_padding_mask=target_key_padding_mask,
            memory_key_padding_mask=memory_key_padding_mask,
        )
        return self.lm_head(self.final_layer_norm(decoded))


@torch.no_grad()
def greedy_decode_restore(
    *,
    restore_head: nn.Module,
    encoder_hidden_states: torch.Tensor,
    encoder_attention_mask: torch.Tensor,
    decoder_start_token_id: int,
    eos_token_id: int,
    max_length: int,
) -> torch.Tensor:
    device = encoder_hidden_states.device
    batch_size = encoder_hidden_states.shape[0]
    decoder_input_ids = torch.full((batch_size, 1), decoder_start_token_id, dtype=torch.long, device=device)
    generated: list[torch.Tensor] = []
    finished = torch.zeros(batch_size, dtype=torch.bool, device=device)

    for _ in range(max_length):
        logits = restore_head(decoder_input_ids, encoder_hidden_states, encoder_attention_mask)
        next_token = torch.argmax(logits[:, -1, :], dim=-1)
        generated.append(next_token)
        finished |= next_token == eos_token_id
        decoder_input_ids = torch.cat([decoder_input_ids, next_token.unsqueeze(1)], dim=1)
        if bool(finished.all()):
            break

    return torch.stack(generated, dim=1) if generated else torch.empty(batch_size, 0, dtype=torch.long, device=device)


def validate_decoded_smiles(decoded_smiles: str, *, target_canonical_smiles: str) -> dict[str, Any]:
    mol = Chem.MolFromSmiles(decoded_smiles)
    if mol is None:
        return {
            "decoded_smiles": decoded_smiles,
            "rdkit_valid": False,
            "two_attachment_valid": False,
            "canonical_smiles": None,
            "canonical_match": False,
            "failure_reason": "rdkit_parse_failed",
        }
    attachment_count = sum(1 for atom in mol.GetAtoms() if atom.GetSymbol() == "*")
    two_attachment_valid = attachment_count == 2
    canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
    return {
        "decoded_smiles": decoded_smiles,
        "rdkit_valid": True,
        "two_attachment_valid": two_attachment_valid,
        "canonical_smiles": canonical,
        "canonical_match": canonical == target_canonical_smiles,
        "failure_reason": None if two_attachment_valid else "attachment_count_not_two",
    }


def token_accuracy(logits: torch.Tensor, labels: torch.Tensor, label_mask: torch.Tensor) -> float:
    predictions = torch.argmax(logits, dim=-1)
    active = label_mask
    if not bool(active.any()):
        return 0.0
    correct = (predictions[active] == labels[active]).float().mean()
    return float(correct.item())


def strip_after_eos(token_ids: list[int], eos_token_id: int) -> list[int]:
    stripped: list[int] = []
    for token_id in token_ids:
        if token_id == eos_token_id:
            break
        stripped.append(token_id)
    return stripped


def validate_preview_tokenizer_compatibility(tokenizer: Any, preview_path: Path | str, sample_size: int = 32) -> None:
    if tokenizer.eos_token != "<|endoftext|>" or tokenizer.eos_token_id != 151643:
        raise ValueError(
            "Stage B requires the Qwen2.5-7B Base tokenizer "
            f"with eos_token='<|endoftext|>' and eos_token_id=151643; got "
            f"eos_token={tokenizer.eos_token!r}, eos_token_id={tokenizer.eos_token_id!r}"
        )

    checked = 0
    with Path(preview_path).open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if "input_text_view1" not in row or "target_text" not in row:
                continue
            encoded_view = tokenizer.encode(row["input_text_view1"], add_special_tokens=False)
            encoded_target = tokenizer.encode(row["target_text"], add_special_tokens=False)
            if encoded_view != row["input_ids_view1"]:
                raise ValueError(f"{preview_path}:{line_no}: tokenizer mismatch for input_ids_view1")
            if encoded_target != row["restore_labels"]:
                raise ValueError(f"{preview_path}:{line_no}: tokenizer mismatch for restore_labels")
            checked += 1
            if checked >= sample_size:
                break
    if checked == 0:
        raise ValueError(f"{preview_path}: no preview rows with text fields were available for tokenizer compatibility check")


def save_restore_checkpoint(checkpoint_dir: Path | str, restore_head: nn.Module, config: dict[str, Any]) -> None:
    checkpoint_path = Path(checkpoint_dir)
    checkpoint_path.mkdir(parents=True, exist_ok=True)
    torch.save(restore_head.state_dict(), checkpoint_path / "restore_head.pt")
    (checkpoint_path / "restore_head_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_yaml_config(path: Path) -> StageBConfig:
    import yaml

    if not path.exists():
        return StageBConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    flat: dict[str, Any] = {}
    for value in data.values():
        if isinstance(value, dict):
            flat.update(value)
    if "lora_target_modules" in flat:
        flat["lora_target_modules"] = tuple(flat["lora_target_modules"])
    allowed = set(StageBConfig.__dataclass_fields__)
    return StageBConfig(**{key: value for key, value in flat.items() if key in allowed})


def get_model_backbone(model: Any) -> nn.Module:
    if hasattr(model, "get_base_model"):
        base_model = model.get_base_model()
        if hasattr(base_model, "model"):
            backbone = base_model.model
            if hasattr(backbone, "model"):
                return backbone.model
            return backbone
        return base_model
    if hasattr(model, "model"):
        backbone = model.model
        if hasattr(backbone, "model"):
            return backbone.model
        return backbone
    if hasattr(model, "base_model") and hasattr(model.base_model, "model"):
        wrapped_model = model.base_model.model
        if hasattr(wrapped_model, "model"):
            return wrapped_model.model
        return wrapped_model
    raise AttributeError("could not locate decoder backbone on loaded model")


def forward_encoder_hidden(model: Any, batch: RestoreBatch) -> torch.Tensor:
    backbone = get_model_backbone(model)
    outputs = backbone(
        input_ids=batch.input_ids_view1,
        attention_mask=batch.attention_mask_view1,
        use_cache=False,
        return_dict=True,
    )
    return outputs.last_hidden_state


def build_optimizer(model: nn.Module, restore_head: nn.Module, config: StageBConfig) -> torch.optim.Optimizer:
    lora_params = [param for param in model.parameters() if param.requires_grad]
    restore_params = list(restore_head.parameters())
    return torch.optim.AdamW(
        [
            {"params": lora_params, "lr": config.learning_rate_lora},
            {"params": restore_params, "lr": config.learning_rate_restore_head},
        ],
        weight_decay=config.weight_decay,
    )


def restore_prediction_context(batch: RestoreBatch, row_index: int) -> dict[str, Any]:
    return {
        "record_id": batch.record_ids[row_index],
        "split": batch.splits[row_index],
        "view_id": batch.view_ids[row_index],
        "augmentation_strategy": batch.augmentation_strategies[row_index],
        "text_view_1_strategy": batch.text_view_1_strategies[row_index],
        "text_view_1": batch.text_view_1[row_index],
        "target": batch.canonical_smiles[row_index],
        "target_text": batch.target_texts[row_index],
    }


def evaluate_restore(
    *,
    model: nn.Module,
    restore_head: RestoreCrossAttentionHead,
    dataloader: DataLoader,
    tokenizer: Any,
    config: StageBConfig,
    device: torch.device,
    max_batches: int | None = None,
    decode_sample_limit: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    model.eval()
    restore_head.eval()
    if decode_sample_limit is None:
        decode_sample_limit = config.eval_decode_samples
    losses: list[float] = []
    accuracies: list[float] = []
    exact_matches = 0
    rdkit_valid = 0
    two_attachment_valid = 0
    canonical_matches = 0
    total = 0
    failed_cases: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    decoded_count = 0

    with torch.no_grad():
        for batch_index, batch in enumerate(dataloader):
            if max_batches is not None and batch_index >= max_batches:
                break
            batch = batch.to(device)
            hidden = forward_encoder_hidden(model, batch)
            decoder_input = shift_restore_labels_right(
                batch.restore_labels,
                batch.restore_label_mask,
                decoder_start_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.pad_token_id,
            )
            logits = restore_head(decoder_input, hidden, batch.attention_mask_view1)
            losses.append(float(masked_cross_entropy(logits.float(), batch.restore_labels, batch.restore_label_mask).item()))
            accuracies.append(token_accuracy(logits, batch.restore_labels, batch.restore_label_mask))

            total += len(batch.record_ids)

            remaining_decode = None if decode_sample_limit is None else max(decode_sample_limit - decoded_count, 0)
            if remaining_decode:
                decode_batch_size = min(remaining_decode, batch.input_ids_view1.shape[0])
                decoded_ids = greedy_decode_restore(
                    restore_head=restore_head,
                    encoder_hidden_states=hidden[:decode_batch_size],
                    encoder_attention_mask=batch.attention_mask_view1[:decode_batch_size],
                    decoder_start_token_id=tokenizer.eos_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                    max_length=config.max_seq_len_restore_label,
                )
                for row_index, token_ids in enumerate(decoded_ids.detach().cpu().tolist()):
                    text = tokenizer.decode(strip_after_eos(token_ids, tokenizer.eos_token_id), skip_special_tokens=True)
                    target = batch.canonical_smiles[row_index]
                    result = validate_decoded_smiles(text, target_canonical_smiles=target)
                    exact_matches += int(text == target)
                    rdkit_valid += int(result["rdkit_valid"])
                    two_attachment_valid += int(result["two_attachment_valid"])
                    canonical_matches += int(result["canonical_match"])
                    decoded_count += 1
                    prediction = {
                        **restore_prediction_context(batch, row_index),
                        "exact_string_match": text == target,
                        **result,
                    }
                    predictions.append(prediction)
                    if not result["canonical_match"]:
                        failed_cases.append(prediction)

    decode_denom = max(decoded_count, 1)
    metrics = {
        "loss": sum(losses) / max(len(losses), 1),
        "token_accuracy": sum(accuracies) / max(len(accuracies), 1),
        "exact_string_match": exact_matches / decode_denom,
        "rdkit_validity": rdkit_valid / decode_denom,
        "two_attachment_validity": two_attachment_valid / decode_denom,
        "canonical_match": canonical_matches / decode_denom,
        "sample_count": total,
        "decoded_sample_count": decoded_count,
    }
    return metrics, failed_cases, predictions


def full_decode_sample_limit(dataset: Any) -> int:
    return len(dataset)


def formal_eval_decode_sample_limit(config: StageBConfig, dataset: Any, configured_limit: int) -> int:
    if config.formal_eval_full_decode:
        return full_decode_sample_limit(dataset)
    return configured_limit


def rate(count: int | float, total: int) -> float:
    return count / total if total else 0.0


def aggregate_boolean_metric(rows: list[dict[str, Any]], key: str) -> float:
    return rate(sum(1 for row in rows if bool(row.get(key))), len(rows))


def add_strategy_aggregates(
    metrics: dict[str, Any],
    predictions: list[dict[str, Any]],
    *,
    prefix: str,
    macro_strategies: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    by_strategy_rows: dict[str, list[dict[str, Any]]] = {}
    for row in predictions:
        strategy = str(row.get("augmentation_strategy", "unknown"))
        by_strategy_rows.setdefault(strategy, []).append(row)

    by_strategy: dict[str, dict[str, Any]] = {}
    for strategy in sorted(by_strategy_rows):
        rows = by_strategy_rows[strategy]
        by_strategy[strategy] = {
            "sample_count": len(rows),
            "failed_count": sum(1 for row in rows if not bool(row.get("canonical_match"))),
            "exact_string_match": aggregate_boolean_metric(rows, "exact_string_match"),
            "rdkit_validity": aggregate_boolean_metric(rows, "rdkit_valid"),
            "two_attachment_validity": aggregate_boolean_metric(rows, "two_attachment_valid"),
            "canonical_match": aggregate_boolean_metric(rows, "canonical_match"),
        }

    selected_strategies = [
        strategy
        for strategy in (macro_strategies or tuple(sorted(by_strategy)))
        if by_strategy.get(strategy, {}).get("sample_count", 0) > 0
    ]
    macro_metrics = {
        metric_name: rate(
            sum(by_strategy[strategy][metric_name] for strategy in selected_strategies),
            len(selected_strategies),
        )
        for metric_name in ("exact_string_match", "rdkit_validity", "two_attachment_validity", "canonical_match")
    }
    macro_metrics["strategy_count"] = len(selected_strategies)
    macro_metrics["strategies"] = selected_strategies

    return {
        **metrics,
        f"{prefix}_by_strategy": by_strategy,
        f"{prefix}_strategy_macro_avg": macro_metrics,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_eval_report(path: Path, metrics: dict[str, Any], config: StageBConfig) -> None:
    lines = [
        "# Stage B Restore Full Eval Report",
        "",
        "This checkpoint is a Stage B text-only restore training artifact.",
        "",
        f"- max epochs: `{config.max_epochs}`",
        f"- precision: `{config.precision}`",
        f"- preview path: `{config.preview_path}`",
        "",
        "## Metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_extra_eval_report(
    path: Path,
    *,
    metrics: dict[str, Any],
    config: StageBConfig,
    eval_preview_path: Path,
    split: str,
) -> None:
    lines = [
        "# Stage B Restore Extra Eval Report",
        "",
        "This report is an eval-only pass against an alternate preview file.",
        "",
        f"- split: `{split}`",
        f"- train preview path: `{config.preview_path}`",
        f"- eval preview path: `{eval_preview_path}`",
        f"- precision: `{config.precision}`",
        "",
        "## Metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_extra_eval_outputs(
    *,
    output_dir: Path,
    prefix: str,
    split: str,
    metrics: dict[str, Any],
    failed_cases: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    config: StageBConfig,
    eval_preview_path: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{prefix}_{split}"
    (output_dir / f"{stem}_eval_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_jsonl(output_dir / f"{stem}_failed_cases.jsonl", failed_cases)
    write_jsonl(output_dir / f"{stem}_predictions.jsonl", predictions)
    write_extra_eval_report(
        output_dir / f"{stem}_eval_report.md",
        metrics=metrics,
        config=config,
        eval_preview_path=eval_preview_path,
        split=split,
    )


def run_extra_restore_eval(
    *,
    eval_preview_path: Path,
    output_dir: Path,
    output_prefix: str,
    model: nn.Module,
    restore_head: RestoreCrossAttentionHead,
    tokenizer: Any,
    config: StageBConfig,
    collate_fn: Any,
    device: torch.device,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    validate_preview_tokenizer_compatibility(tokenizer, eval_preview_path)
    for split in ("valid", "test"):
        dataset = StageAPreviewDataset(eval_preview_path, split=split)
        if len(dataset) == 0:
            continue
        dataloader = DataLoader(dataset, batch_size=config.per_device_eval_batch_size, shuffle=False, collate_fn=collate_fn)
        decode_sample_limit = formal_eval_decode_sample_limit(config, dataset, config.eval_decode_samples)
        metrics, failed_cases, predictions = evaluate_restore(
            model=model,
            restore_head=restore_head,
            dataloader=dataloader,
            tokenizer=tokenizer,
            config=config,
            device=device,
            decode_sample_limit=decode_sample_limit,
        )
        metrics = add_strategy_aggregates(metrics, predictions, prefix=output_prefix)
        metrics["formal_eval_full_decode"] = config.formal_eval_full_decode
        write_extra_eval_outputs(
            output_dir=output_dir,
            prefix=output_prefix,
            split=split,
            metrics=metrics,
            failed_cases=failed_cases,
            predictions=predictions,
            config=config,
            eval_preview_path=eval_preview_path,
        )
        results[split] = metrics
    return results


def save_run_artifacts(
    *,
    output_dir: Path,
    model: Any,
    restore_head: RestoreCrossAttentionHead,
    tokenizer: Any,
    config: StageBConfig,
    metrics: dict[str, Any],
    failed_cases: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(model, "save_pretrained"):
        model.save_pretrained(output_dir / "lora_adapter")
    save_restore_checkpoint(output_dir / "restore_head", restore_head, asdict(config))
    tokenizer.save_pretrained(output_dir / "tokenizer")
    (output_dir / "training_config.json").write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "eval_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_jsonl(output_dir / "failed_cases.jsonl", failed_cases)
    write_jsonl(output_dir / "predictions.jsonl", predictions)
    write_eval_report(output_dir / "eval_report.md", metrics, config)


def copy_config_snapshot(config_path: Path, output_dir: Path) -> None:
    if config_path.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config_path, output_dir / config_path.name)


def reset_training_metric_files(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in (EPOCH_METRICS_JSONL, EPOCH_METRICS_CSV, QUICK_EVAL_METRICS_JSONL):
        path = output_dir / filename
        if path.exists():
            path.unlink()


def append_quick_eval_metrics(output_dir: Path, row: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / QUICK_EVAL_METRICS_JSONL).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def append_epoch_metrics(
    output_dir: Path,
    metrics: dict[str, Any],
    *,
    early_stopping: dict[str, Any] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    row = {**metrics, "early_stopping": early_stopping or {"enabled": False}}
    with (output_dir / EPOCH_METRICS_JSONL).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    flat_row = {field: metrics.get(field) for field in EPOCH_METRIC_CSV_FIELDS}
    if early_stopping:
        flat_row.update(
            {
                "early_stopping_metric": early_stopping.get("metric"),
                "early_stopping_mode": early_stopping.get("mode"),
                "early_stopping_current": early_stopping.get("current"),
                "early_stopping_best": early_stopping.get("best"),
                "early_stopping_best_checkpoint": early_stopping.get("best_checkpoint"),
                "early_stopping_wait": early_stopping.get("wait"),
                "early_stopping_stop_training": early_stopping.get("stop_training"),
                "early_stopping_reason": early_stopping.get("reason"),
            }
        )

    csv_path = output_dir / EPOCH_METRICS_CSV
    write_header = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=EPOCH_METRIC_CSV_FIELDS,
            extrasaction="ignore",
            lineterminator="\n",
        )
        if write_header:
            writer.writeheader()
        writer.writerow(flat_row)


def save_checkpoint_with_eval(
    *,
    checkpoint_dir: Path,
    checkpoint_name: str,
    epoch: int,
    optimizer_step: int,
    model: Any,
    restore_head: RestoreCrossAttentionHead,
    dataloader: DataLoader,
    tokenizer: Any,
    config: StageBConfig,
    device: torch.device,
    recent_train_loss: float | None,
    epoch_train_loss_mean: float | None = None,
) -> dict[str, Any]:
    max_batches = None
    if not config.formal_eval_full_decode and config.checkpoint_eval_samples > 0:
        max_batches = math.ceil(config.checkpoint_eval_samples / config.per_device_eval_batch_size)
    eval_sample_limit = (
        full_decode_sample_limit(dataloader.dataset)
        if config.formal_eval_full_decode
        else config.checkpoint_eval_samples
    )
    decode_sample_limit = formal_eval_decode_sample_limit(
        config,
        dataloader.dataset,
        config.checkpoint_eval_decode_samples,
    )
    metrics, failed_cases, predictions = evaluate_restore(
        model=model,
        restore_head=restore_head,
        dataloader=dataloader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        max_batches=max_batches,
        decode_sample_limit=decode_sample_limit,
    )
    metrics = add_strategy_aggregates(metrics, predictions, prefix="all_view")
    metrics = {
        **metrics,
        "checkpoint_name": checkpoint_name,
        "checkpoint_epoch": epoch,
        "checkpoint_optimizer_step": optimizer_step,
        "checkpoint_recent_train_loss": recent_train_loss,
        "checkpoint_epoch_train_loss_mean": epoch_train_loss_mean,
        "formal_eval_full_decode": config.formal_eval_full_decode,
        "full_epoch_decode": config.formal_eval_full_decode,
    }
    save_run_artifacts(
        output_dir=checkpoint_dir,
        model=model,
        restore_head=restore_head,
        tokenizer=tokenizer,
        config=config,
        metrics=metrics,
        failed_cases=failed_cases,
        predictions=predictions,
    )
    (checkpoint_dir / "checkpoint_metadata.json").write_text(
        json.dumps(
            {
                "checkpoint_name": checkpoint_name,
                "epoch": epoch,
                "optimizer_step": optimizer_step,
                "recent_train_loss": recent_train_loss,
                "epoch_train_loss_mean": epoch_train_loss_mean,
                "eval_sample_limit": eval_sample_limit,
                "eval_decode_sample_limit": decode_sample_limit,
                "formal_eval_full_decode": config.formal_eval_full_decode,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return metrics


def validate_training_config(config: StageBConfig) -> None:
    if config.gradient_accumulation_steps < 1:
        raise ValueError("gradient_accumulation_steps must be >= 1")
    if config.quick_eval_every_steps < 0:
        raise ValueError("quick_eval_every_steps must be >= 0; use 0 to disable quick eval")
    if config.checkpoint_eval_samples < 0:
        raise ValueError("checkpoint_eval_samples must be >= 0; use 0 for full validation")
    if config.checkpoint_every_steps < 0:
        raise ValueError("checkpoint_every_steps must be >= 0")
    if not config.early_stopping_enabled:
        return
    if not config.checkpoint_at_epoch_end:
        raise ValueError("Stage B early stopping currently requires checkpoint_at_epoch_end=true")
    if config.early_stopping_mode not in {"min", "max"}:
        raise ValueError("early_stopping_mode must be 'min' or 'max'")
    if config.early_stopping_patience < 1:
        raise ValueError("early_stopping_patience must be >= 1")
    if config.early_stopping_min_epochs < 1:
        raise ValueError("early_stopping_min_epochs must be >= 1")
    if config.early_stopping_min_delta < 0:
        raise ValueError("early_stopping_min_delta must be >= 0")


def early_stopping_is_improvement(current: float, best: float | None, *, mode: str, min_delta: float) -> bool:
    if best is None:
        return True
    if mode == "min":
        return current < best - min_delta
    if mode == "max":
        return current > best + min_delta
    raise ValueError("mode must be 'min' or 'max'")


def update_early_stopping_state(
    *,
    config: StageBConfig,
    checkpoint_metrics: dict[str, Any],
    checkpoint_name: str,
    epoch_index: int,
    best_metric: float | None,
    best_checkpoint: str | None,
    wait: int,
    stop_training: bool = False,
    early_stop_reason: str | None = None,
) -> tuple[dict[str, Any] | None, float | None, str | None, int, bool, str | None]:
    if not config.early_stopping_enabled:
        return None, best_metric, best_checkpoint, wait, stop_training, early_stop_reason

    raw_metric = checkpoint_metrics.get(config.early_stopping_metric)
    if not isinstance(raw_metric, (int, float)) or not math.isfinite(float(raw_metric)):
        raise ValueError(f"early stopping metric is missing or non-finite: {config.early_stopping_metric}")
    metric_value = float(raw_metric)
    improved = early_stopping_is_improvement(
        metric_value,
        best_metric,
        mode=config.early_stopping_mode,
        min_delta=config.early_stopping_min_delta,
    )
    would_stop_training = False
    monitor_reason: str | None = None
    if improved:
        best_metric = metric_value
        best_checkpoint = checkpoint_name
        wait = 0
    elif epoch_index >= config.early_stopping_min_epochs:
        wait += 1
        if wait >= config.early_stopping_patience:
            would_stop_training = True
            monitor_reason = (
                f"{config.early_stopping_metric} did not improve by "
                f"{config.early_stopping_min_delta} for {wait} epoch checkpoints"
            )
            if not config.early_stopping_monitor_only:
                early_stop_reason = monitor_reason
                stop_training = True

    state = {
        "enabled": True,
        "monitor_only": config.early_stopping_monitor_only,
        "metric": config.early_stopping_metric,
        "mode": config.early_stopping_mode,
        "current": metric_value,
        "best": best_metric,
        "best_checkpoint": best_checkpoint,
        "wait": wait,
        "stop_training": stop_training,
        "would_stop_training": would_stop_training,
        "reason": monitor_reason if config.early_stopping_monitor_only else early_stop_reason,
    }
    return state, best_metric, best_checkpoint, wait, stop_training, early_stop_reason


def run_reload_smoke(
    *,
    model_name_or_path: str,
    output_dir: Path,
    tokenizer: Any,
    config: StageBConfig,
    valid_dataset: StageAPreviewDataset,
    collate_fn: Any,
    device: torch.device,
) -> dict[str, Any]:
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    base_model = AutoModelForCausalLM.from_pretrained(
        model_name_or_path,
        torch_dtype=torch.bfloat16,
        device_map={"": 0},
    )
    reloaded_model = PeftModel.from_pretrained(base_model, output_dir / "lora_adapter")
    reloaded_model.config.use_cache = False
    reloaded_model.eval()

    model_hidden_size = int(reloaded_model.config.hidden_size)
    reloaded_head = RestoreCrossAttentionHead(
        vocab_size=len(tokenizer),
        hidden_size=config.restore_hidden_size,
        num_layers=config.restore_num_layers,
        num_attention_heads=config.restore_num_attention_heads,
        dropout=config.restore_dropout,
        pad_token_id=tokenizer.pad_token_id,
        decoder_start_token_id=tokenizer.eos_token_id,
        max_target_positions=config.max_seq_len_restore_label,
        encoder_hidden_size=model_hidden_size,
    ).to(device=device)
    reloaded_head.load_state_dict(torch.load(output_dir / "restore_head" / "restore_head.pt", map_location=device))
    reloaded_head.eval()

    smoke_loader = DataLoader(valid_dataset, batch_size=1, shuffle=False, collate_fn=collate_fn)
    batch = next(iter(smoke_loader)).to(device)
    with torch.no_grad():
        hidden = forward_encoder_hidden(reloaded_model, batch)
        decoded = greedy_decode_restore(
            restore_head=reloaded_head,
            encoder_hidden_states=hidden,
            encoder_attention_mask=batch.attention_mask_view1,
            decoder_start_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
            max_length=config.max_seq_len_restore_label,
        )

    result = {
        "status": "passed",
        "record_id": batch.record_ids[0],
        "decoded_token_count": int(decoded.shape[1]),
    }
    (output_dir / "reload_smoke.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Stage B text-only restore full run.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--model-name-or-path", required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--preview-path", type=Path, default=None)
    parser.add_argument("--eval-preview-path", type=Path, default=None)
    parser.add_argument("--eval-output-prefix", default="robustness")
    return parser.parse_args()


def main() -> None:
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

    args = parse_args()
    config = load_yaml_config(args.config)
    if args.output_dir is not None:
        config = StageBConfig(**{**asdict(config), "output_dir": str(args.output_dir)})
    if args.preview_path is not None:
        config = StageBConfig(**{**asdict(config), "preview_path": str(args.preview_path)})

    validate_training_config(config)
    set_seed(config.seed)
    if not torch.cuda.is_available():
        raise SystemExit("Stage B real Qwen2.5-7B bf16 LoRA training requires a CUDA GPU.")
    device = torch.device("cuda")

    tokenizer = AutoTokenizer.from_pretrained(args.model_name_or_path, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    validate_preview_tokenizer_compatibility(tokenizer, config.preview_path)

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name_or_path,
        torch_dtype=torch.bfloat16,
        device_map={"": 0},
    )
    model.config.use_cache = False
    lora_config = LoraConfig(
        r=config.lora_rank,
        lora_alpha=config.lora_alpha,
        target_modules=list(config.lora_target_modules),
        lora_dropout=config.lora_dropout,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    model.train()

    hidden_size = int(model.config.hidden_size)
    restore_head = RestoreCrossAttentionHead(
        vocab_size=len(tokenizer),
        hidden_size=config.restore_hidden_size,
        num_layers=config.restore_num_layers,
        num_attention_heads=config.restore_num_attention_heads,
        dropout=config.restore_dropout,
        pad_token_id=tokenizer.pad_token_id,
        decoder_start_token_id=tokenizer.eos_token_id,
        max_target_positions=config.max_seq_len_restore_label,
        encoder_hidden_size=hidden_size,
    ).to(device=device)

    preview_path = Path(config.preview_path)
    train_dataset = StageAPreviewDataset(preview_path, split="train")
    valid_dataset = StageAPreviewDataset(preview_path, split="valid")
    test_dataset = StageAPreviewDataset(preview_path, split="test")
    collate = lambda rows: collate_restore_records(rows, pad_token_id=tokenizer.pad_token_id, label_pad_token_id=tokenizer.pad_token_id)
    train_loader = DataLoader(train_dataset, batch_size=config.per_device_train_batch_size, shuffle=True, collate_fn=collate)
    valid_loader = DataLoader(valid_dataset, batch_size=config.per_device_eval_batch_size, shuffle=False, collate_fn=collate)
    test_loader = DataLoader(test_dataset, batch_size=config.per_device_eval_batch_size, shuffle=False, collate_fn=collate)
    optimizer = build_optimizer(model, restore_head, config)

    output_dir = Path(config.output_dir)
    reset_training_metric_files(output_dir)

    trainable_params = [param for param in model.parameters() if param.requires_grad] + list(restore_head.parameters())
    train_losses: list[float] = []
    optimizer.zero_grad(set_to_none=True)
    optimizer_steps = 0
    completed_epochs = 0
    stop_training = False
    early_stop_reason: str | None = None
    early_stop_wait = 0
    best_early_metric: float | None = None
    best_early_checkpoint: str | None = None

    for epoch_index in range(1, config.max_epochs + 1):
        completed_epochs = epoch_index
        epoch_train_losses: list[float] = []
        for step, batch in enumerate(train_loader, start=1):
            model.train()
            restore_head.train()
            batch = batch.to(device)
            hidden = forward_encoder_hidden(model, batch)
            decoder_input = shift_restore_labels_right(
                batch.restore_labels,
                batch.restore_label_mask,
                decoder_start_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.pad_token_id,
            )
            logits = restore_head(decoder_input, hidden, batch.attention_mask_view1)
            loss = masked_cross_entropy(logits.float(), batch.restore_labels, batch.restore_label_mask)
            if not torch.isfinite(loss):
                raise FloatingPointError(f"non-finite training loss at step {step}: {loss.item()}")
            (loss / config.gradient_accumulation_steps).backward()
            loss_value = float(loss.item())
            train_losses.append(loss_value)
            epoch_train_losses.append(loss_value)

            if step % config.gradient_accumulation_steps == 0 or step == len(train_loader):
                torch.nn.utils.clip_grad_norm_(trainable_params, config.max_grad_norm)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                optimizer_steps += 1

                if config.quick_eval_every_steps > 0 and optimizer_steps % config.quick_eval_every_steps == 0:
                    quick_batches = math.ceil(config.quick_eval_samples / config.per_device_eval_batch_size)
                    quick_metrics, _, _ = evaluate_restore(
                        model=model,
                        restore_head=restore_head,
                        dataloader=valid_loader,
                        tokenizer=tokenizer,
                        config=config,
                        device=device,
                        max_batches=quick_batches,
                        decode_sample_limit=config.quick_eval_decode_samples,
                    )
                    quick_row = {
                        "epoch": epoch_index,
                        "optimizer_step": optimizer_steps,
                        "train_loss": train_losses[-1],
                        "quick_valid": quick_metrics,
                    }
                    append_quick_eval_metrics(output_dir, quick_row)
                    print(json.dumps(quick_row, ensure_ascii=False))
                if config.checkpoint_every_steps > 0 and optimizer_steps % config.checkpoint_every_steps == 0:
                    checkpoint_name = f"step_{optimizer_steps:06d}"
                    checkpoint_metrics = save_checkpoint_with_eval(
                        checkpoint_dir=output_dir / "checkpoints" / checkpoint_name,
                        checkpoint_name=checkpoint_name,
                        epoch=epoch_index,
                        optimizer_step=optimizer_steps,
                        model=model,
                        restore_head=restore_head,
                        dataloader=valid_loader,
                        tokenizer=tokenizer,
                        config=config,
                        device=device,
                        recent_train_loss=train_losses[-1] if train_losses else None,
                    )
                    copy_config_snapshot(args.config, output_dir / "checkpoints" / checkpoint_name)
                    print(json.dumps({"checkpoint": checkpoint_name, "metrics": checkpoint_metrics}, ensure_ascii=False))
        if config.checkpoint_at_epoch_end:
            checkpoint_name = f"epoch_{epoch_index:03d}"
            epoch_train_loss_mean = sum(epoch_train_losses) / len(epoch_train_losses) if epoch_train_losses else None
            checkpoint_metrics = save_checkpoint_with_eval(
                checkpoint_dir=output_dir / "checkpoints" / checkpoint_name,
                checkpoint_name=checkpoint_name,
                epoch=epoch_index,
                optimizer_step=optimizer_steps,
                model=model,
                restore_head=restore_head,
                dataloader=valid_loader,
                tokenizer=tokenizer,
                config=config,
                device=device,
                recent_train_loss=train_losses[-1] if train_losses else None,
                epoch_train_loss_mean=epoch_train_loss_mean,
            )
            copy_config_snapshot(args.config, output_dir / "checkpoints" / checkpoint_name)
            print(json.dumps({"checkpoint": checkpoint_name, "metrics": checkpoint_metrics}, ensure_ascii=False))
            (
                early_stopping_state,
                best_early_metric,
                best_early_checkpoint,
                early_stop_wait,
                stop_training,
                early_stop_reason,
            ) = update_early_stopping_state(
                config=config,
                checkpoint_metrics=checkpoint_metrics,
                checkpoint_name=checkpoint_name,
                epoch_index=epoch_index,
                best_metric=best_early_metric,
                best_checkpoint=best_early_checkpoint,
                wait=early_stop_wait,
                stop_training=stop_training,
                early_stop_reason=early_stop_reason,
            )
            if early_stopping_state is not None:
                print(json.dumps({"early_stopping": early_stopping_state}, ensure_ascii=False))
            append_epoch_metrics(output_dir, checkpoint_metrics, early_stopping=early_stopping_state)
        if stop_training:
            break

    valid_decode_sample_limit = formal_eval_decode_sample_limit(config, valid_dataset, config.eval_decode_samples)
    test_decode_sample_limit = formal_eval_decode_sample_limit(config, test_dataset, config.eval_decode_samples)
    metrics, failed_cases, predictions = evaluate_restore(
        model=model,
        restore_head=restore_head,
        dataloader=valid_loader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        decode_sample_limit=valid_decode_sample_limit,
    )
    test_metrics, test_failed_cases, test_predictions = evaluate_restore(
        model=model,
        restore_head=restore_head,
        dataloader=test_loader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        decode_sample_limit=test_decode_sample_limit,
    )
    metrics = add_strategy_aggregates(metrics, predictions, prefix="all_view")
    test_metrics = add_strategy_aggregates(test_metrics, test_predictions, prefix="all_view")
    first_window = train_losses[: max(1, len(train_losses) // 5)]
    last_window = train_losses[-max(1, len(train_losses) // 5) :]
    if first_window and last_window:
        metrics["train_loss_first_window"] = sum(first_window) / len(first_window)
        metrics["train_loss_last_window"] = sum(last_window) / len(last_window)
        metrics["train_loss_decreased"] = metrics["train_loss_last_window"] < metrics["train_loss_first_window"]
    metrics["completed_epochs"] = completed_epochs
    metrics["optimizer_steps"] = optimizer_steps
    metrics["train_sample_count"] = len(train_dataset)
    metrics["valid_sample_count"] = len(valid_dataset)
    metrics["test_sample_count"] = len(test_dataset)
    metrics["early_stopped"] = stop_training
    metrics["early_stop_reason"] = early_stop_reason
    metrics["early_stopping_monitor_only"] = config.early_stopping_monitor_only
    metrics["best_early_stopping_metric"] = best_early_metric
    metrics["best_early_stopping_checkpoint"] = best_early_checkpoint
    metrics["formal_eval_full_decode"] = config.formal_eval_full_decode
    metrics["full_final_decode"] = config.formal_eval_full_decode
    metrics["all_view_test_loss"] = test_metrics.get("loss")
    metrics["all_view_test_canonical_match"] = test_metrics.get("canonical_match")
    metrics["identity_test_loss"] = test_metrics.get("loss")
    metrics["identity_test_canonical_match"] = test_metrics.get("canonical_match")
    test_metrics = {
        **test_metrics,
        "formal_eval_full_decode": config.formal_eval_full_decode,
        "full_final_decode": config.formal_eval_full_decode,
    }
    save_run_artifacts(
        output_dir=output_dir,
        model=model,
        restore_head=restore_head,
        tokenizer=tokenizer,
        config=config,
        metrics=metrics,
        failed_cases=failed_cases,
        predictions=predictions,
    )
    write_extra_eval_outputs(
        output_dir=output_dir,
        prefix="identity",
        split="test",
        metrics=test_metrics,
        failed_cases=test_failed_cases,
        predictions=test_predictions,
        config=config,
        eval_preview_path=preview_path,
    )
    copy_config_snapshot(args.config, output_dir)
    extra_eval: dict[str, dict[str, Any]] = {}
    if args.eval_preview_path is not None:
        extra_eval = run_extra_restore_eval(
            eval_preview_path=args.eval_preview_path,
            output_dir=output_dir,
            output_prefix=args.eval_output_prefix,
            model=model,
            restore_head=restore_head,
            tokenizer=tokenizer,
            config=config,
            collate_fn=collate,
            device=device,
        )
    del optimizer
    del model
    del restore_head
    import gc

    gc.collect()
    torch.cuda.empty_cache()
    reload_smoke = run_reload_smoke(
        model_name_or_path=args.model_name_or_path,
        output_dir=output_dir,
        tokenizer=tokenizer,
        config=config,
        valid_dataset=valid_dataset,
        collate_fn=collate,
        device=device,
    )
    print(
        json.dumps(
            {"output_dir": str(output_dir), "metrics": metrics, "reload_smoke": reload_smoke, "extra_eval": extra_eval},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
