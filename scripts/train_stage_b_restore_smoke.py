from __future__ import annotations

import argparse
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
DEFAULT_CONFIG_PATH = ROOT / "configs" / "stage_b_restore_smoke_bf16.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "stage_b_restore_smoke"


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
    eval_decode_samples: int = 64
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
    canonical_smiles: list[str]
    target_texts: list[str]

    def to(self, device: torch.device | str) -> "RestoreBatch":
        return RestoreBatch(
            input_ids_view1=self.input_ids_view1.to(device),
            attention_mask_view1=self.attention_mask_view1.to(device),
            restore_labels=self.restore_labels.to(device),
            restore_label_mask=self.restore_label_mask.to(device),
            record_ids=self.record_ids,
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
        canonical_smiles.append(str(row["canonical_smiles"]))
        target_texts.append(str(row.get("target_text", "")))

    return RestoreBatch(
        input_ids_view1=torch.tensor(input_ids, dtype=torch.long),
        attention_mask_view1=torch.tensor(attention_masks, dtype=torch.long),
        restore_labels=torch.tensor(labels, dtype=torch.long),
        restore_label_mask=torch.tensor(label_masks, dtype=torch.bool),
        record_ids=record_ids,
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
        target_key_padding_mask = decoder_input_ids == self.pad_token_id
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
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
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
            losses.append(float(masked_cross_entropy(logits, batch.restore_labels, batch.restore_label_mask).item()))
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
                    if not result["canonical_match"]:
                        failed_cases.append(
                            {
                                "record_id": batch.record_ids[row_index],
                                "target": target,
                                **result,
                            }
                        )

    denom = max(total, 1)
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
    return metrics, failed_cases


def write_eval_report(path: Path, metrics: dict[str, Any], config: StageBConfig) -> None:
    lines = [
        "# Stage B Restore Smoke/Baseline Eval Report",
        "",
        "This checkpoint is a Stage B text-only restore smoke/baseline artifact, not a formal BaseLite warmup checkpoint.",
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


def save_run_artifacts(
    *,
    output_dir: Path,
    model: Any,
    restore_head: RestoreCrossAttentionHead,
    tokenizer: Any,
    config: StageBConfig,
    metrics: dict[str, Any],
    failed_cases: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(model, "save_pretrained"):
        model.save_pretrained(output_dir / "lora_adapter")
    save_restore_checkpoint(output_dir / "restore_head", restore_head, asdict(config))
    tokenizer.save_pretrained(output_dir / "tokenizer")
    (output_dir / "training_config.json").write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "eval_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (output_dir / "failed_cases.jsonl").open("w", encoding="utf-8") as handle:
        for row in failed_cases:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    write_eval_report(output_dir / "eval_report.md", metrics, config)


def copy_config_snapshot(config_path: Path, output_dir: Path) -> None:
    if config_path.exists():
        shutil.copy2(config_path, output_dir / "stage_b_restore_smoke_bf16.yaml")


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
    ).to(device=device, dtype=torch.bfloat16)
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
    parser = argparse.ArgumentParser(description="Train Stage B text-only restore smoke/baseline.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--model-name-or-path", required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--preview-path", type=Path, default=None)
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
    ).to(device=device, dtype=torch.bfloat16)

    preview_path = Path(config.preview_path)
    train_dataset = StageAPreviewDataset(preview_path, split="train")
    valid_dataset = StageAPreviewDataset(preview_path, split="valid")
    collate = lambda rows: collate_restore_records(rows, pad_token_id=tokenizer.pad_token_id, label_pad_token_id=tokenizer.pad_token_id)
    train_loader = DataLoader(train_dataset, batch_size=config.per_device_train_batch_size, shuffle=True, collate_fn=collate)
    valid_loader = DataLoader(valid_dataset, batch_size=config.per_device_eval_batch_size, shuffle=False, collate_fn=collate)
    optimizer = build_optimizer(model, restore_head, config)

    running_losses: list[float] = []
    optimizer.zero_grad(set_to_none=True)
    optimizer_steps = 0
    for _epoch in range(config.max_epochs):
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
            running_losses.append(float(loss.item()))

            if step % config.gradient_accumulation_steps == 0 or step == len(train_loader):
                torch.nn.utils.clip_grad_norm_(
                    [param for param in model.parameters() if param.requires_grad] + list(restore_head.parameters()),
                    config.max_grad_norm,
                )
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                optimizer_steps += 1

                if optimizer_steps % config.quick_eval_every_steps == 0:
                    quick_batches = math.ceil(config.quick_eval_samples / config.per_device_eval_batch_size)
                    quick_metrics, _ = evaluate_restore(
                        model=model,
                        restore_head=restore_head,
                        dataloader=valid_loader,
                        tokenizer=tokenizer,
                        config=config,
                        device=device,
                        max_batches=quick_batches,
                        decode_sample_limit=config.quick_eval_decode_samples,
                    )
                    print(json.dumps({"optimizer_step": optimizer_steps, "train_loss": running_losses[-1], "quick_valid": quick_metrics}, ensure_ascii=False))

    metrics, failed_cases = evaluate_restore(
        model=model,
        restore_head=restore_head,
        dataloader=valid_loader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        decode_sample_limit=config.eval_decode_samples,
    )
    first_window = running_losses[: max(1, len(running_losses) // 5)]
    last_window = running_losses[-max(1, len(running_losses) // 5) :]
    metrics["train_loss_first_window"] = sum(first_window) / len(first_window)
    metrics["train_loss_last_window"] = sum(last_window) / len(last_window)
    metrics["train_loss_decreased"] = metrics["train_loss_last_window"] < metrics["train_loss_first_window"]
    output_dir = Path(config.output_dir)
    save_run_artifacts(
        output_dir=output_dir,
        model=model,
        restore_head=restore_head,
        tokenizer=tokenizer,
        config=config,
        metrics=metrics,
        failed_cases=failed_cases,
    )
    copy_config_snapshot(args.config, output_dir)
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
            {"output_dir": str(output_dir), "metrics": metrics, "reload_smoke": reload_smoke},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
