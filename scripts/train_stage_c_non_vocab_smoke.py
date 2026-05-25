from __future__ import annotations

import argparse
import csv
import gc
import json
import math
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_stage_c_non_vocab_dataset import (  # noqa: E402
    DEFAULT_GRAPH_PATH,
    DEFAULT_OUTPUT_DIR as DEFAULT_STAGE_C_DATASET_DIR,
    NULL_CATEGORY,
    build_graph_feature_schema,
    read_jsonl,
)
from scripts.train_stage_b_restore_smoke import (  # noqa: E402
    RestoreCrossAttentionHead,
    forward_encoder_hidden,
    greedy_decode_restore,
    masked_cross_entropy,
    save_restore_checkpoint,
    shift_restore_labels_right,
    strip_after_eos,
    token_accuracy,
    validate_decoded_smiles,
    validate_preview_tokenizer_compatibility,
)


DEFAULT_PREVIEW_PATH = ROOT / "data" / "baselite_smiles_v1" / "training_template_preview.jsonl"
DEFAULT_CONFIG_PATH = ROOT / "configs" / "stage_c_non_vocab_smoke_bf16.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "stage_c_non_vocab_smoke"
DEFAULT_GRAPH_FEATURE_SCHEMA_PATH = DEFAULT_STAGE_C_DATASET_DIR / "graph_feature_schema.json"

EPOCH_METRICS_JSONL = "epoch_metrics.jsonl"
EPOCH_METRICS_CSV = "epoch_metrics.csv"
EPOCH_METRIC_CSV_FIELDS = (
    "checkpoint_name",
    "checkpoint_epoch",
    "checkpoint_optimizer_step",
    "checkpoint_recent_train_loss",
    "checkpoint_epoch_train_loss_mean",
    "sample_count",
    "decoded_sample_count",
    "retrieval_sample_count",
    "loss",
    "restore_loss",
    "align_loss",
    "token_accuracy",
    "exact_string_match",
    "rdkit_validity",
    "two_attachment_validity",
    "canonical_match",
    "text_to_graph_top1",
    "text_to_graph_top5",
    "graph_to_text_top1",
    "graph_to_text_top5",
    "mean_positive_similarity",
    "mean_negative_similarity",
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
class StageCConfig:
    preview_path: str = str(DEFAULT_PREVIEW_PATH)
    graph_path: str = str(DEFAULT_GRAPH_PATH)
    graph_feature_schema_path: str = str(DEFAULT_GRAPH_FEATURE_SCHEMA_PATH)
    output_dir: str = str(DEFAULT_OUTPUT_DIR)
    max_seq_len_restore_label: int = 512
    max_train_samples: int | None = 512
    max_valid_samples: int | None = 128
    max_epochs: int = 1
    per_device_train_batch_size: int = 2
    per_device_eval_batch_size: int = 2
    gradient_accumulation_steps: int = 8
    quick_eval_every_steps: int = 50
    quick_eval_samples: int = 64
    quick_eval_decode_samples: int = 16
    quick_eval_retrieval_samples: int = 64
    checkpoint_at_epoch_end: bool = False
    checkpoint_every_steps: int = 0
    checkpoint_eval_samples: int = 128
    checkpoint_eval_decode_samples: int = 32
    checkpoint_eval_retrieval_samples: int = 128
    early_stopping_enabled: bool = False
    early_stopping_metric: str = "loss"
    early_stopping_mode: str = "min"
    early_stopping_patience: int = 4
    early_stopping_min_delta: float = 0.001
    early_stopping_min_epochs: int = 8
    eval_decode_samples: int = 64
    eval_retrieval_samples: int = 128
    learning_rate_lora: float = 1.0e-4
    learning_rate_restore_head: float = 5.0e-5
    learning_rate_graph_encoder: float = 1.0e-4
    learning_rate_projectors: float = 1.0e-4
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
    graph_hidden_size: int = 256
    graph_num_layers: int = 3
    graph_dropout: float = 0.05
    align_dim: int = 256
    align_temperature: float = 0.07
    restore_loss_weight: float = 1.0
    align_loss_weight: float = 0.1
    precision: str = "bf16"
    seed: int = 42


@dataclass
class StageCBatch:
    input_ids_view1: torch.Tensor
    attention_mask_view1: torch.Tensor
    restore_labels: torch.Tensor
    restore_label_mask: torch.Tensor
    node_features: torch.Tensor
    edge_index: torch.Tensor
    edge_features: torch.Tensor
    graph_batch: torch.Tensor
    record_ids: list[str]
    canonical_smiles: list[str]
    target_texts: list[str]

    def to(self, device: torch.device | str) -> "StageCBatch":
        return StageCBatch(
            input_ids_view1=self.input_ids_view1.to(device),
            attention_mask_view1=self.attention_mask_view1.to(device),
            restore_labels=self.restore_labels.to(device),
            restore_label_mask=self.restore_label_mask.to(device),
            node_features=self.node_features.to(device),
            edge_index=self.edge_index.to(device),
            edge_features=self.edge_features.to(device),
            graph_batch=self.graph_batch.to(device),
            record_ids=self.record_ids,
            canonical_smiles=self.canonical_smiles,
            target_texts=self.target_texts,
        )


@dataclass
class StageCForwardOutput:
    total_loss: torch.Tensor
    restore_loss: torch.Tensor
    align_loss: torch.Tensor
    logits: torch.Tensor
    z_text: torch.Tensor
    z_graph: torch.Tensor
    restore_memory: torch.Tensor
    restore_memory_mask: torch.Tensor


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml_config(path: Path) -> StageCConfig:
    import yaml

    if not path.exists():
        return StageCConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    flat: dict[str, Any] = {}
    for value in data.values():
        if isinstance(value, dict):
            flat.update(value)
    if "lora_target_modules" in flat:
        flat["lora_target_modules"] = tuple(flat["lora_target_modules"])
    allowed = set(StageCConfig.__dataclass_fields__)
    return StageCConfig(**{key: value for key, value in flat.items() if key in allowed})


def normalize_category(value: Any) -> str:
    if value is None or value == "":
        return NULL_CATEGORY
    return str(value)


def schema_feature_dims(feature_schema: dict[str, Any]) -> tuple[int, int]:
    return int(feature_schema["node"]["feature_dim"]), int(feature_schema["edge"]["feature_dim"])


def encode_categorical(value: Any, categories: list[str], *, field_name: str) -> list[float]:
    normalized = normalize_category(value)
    if normalized not in categories:
        raise ValueError(f"unknown category for {field_name}: {normalized!r}")
    return [1.0 if category == normalized else 0.0 for category in categories]


def encode_node_features(node: dict[str, Any], feature_schema: dict[str, Any]) -> list[float]:
    schema = feature_schema["node"]
    values: list[float] = []
    for field in schema["numeric_fields"]:
        values.append(float(node.get(field, 0) or 0))
    for field in schema["bool_fields"]:
        values.append(1.0 if bool(node.get(field, False)) else 0.0)
    for field, categories in schema["categorical_fields"].items():
        values.extend(encode_categorical(node.get(field), categories, field_name=f"node.{field}"))
    return values


def encode_edge_features(edge: dict[str, Any], feature_schema: dict[str, Any]) -> list[float]:
    schema = feature_schema["edge"]
    values: list[float] = []
    for field in schema["bool_fields"]:
        values.append(1.0 if bool(edge.get(field, False)) else 0.0)
    for field, categories in schema["categorical_fields"].items():
        values.extend(encode_categorical(edge.get(field), categories, field_name=f"edge.{field}"))
    return values


def encode_graph_row(graph: dict[str, Any], feature_schema: dict[str, Any]) -> dict[str, torch.Tensor]:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if not nodes:
        raise ValueError(f"{graph.get('record_id')}: graph has no nodes")

    node_id_to_index = {int(node["atom_id"]): index for index, node in enumerate(nodes)}
    node_features = torch.tensor([encode_node_features(node, feature_schema) for node in nodes], dtype=torch.float32)

    directed_edges: list[tuple[int, int]] = []
    directed_edge_features: list[list[float]] = []
    for edge in edges:
        begin = int(edge["begin_atom_id"])
        end = int(edge["end_atom_id"])
        if begin not in node_id_to_index or end not in node_id_to_index:
            raise ValueError(f"{graph.get('record_id')}: edge references missing atom id")
        src = node_id_to_index[begin]
        dst = node_id_to_index[end]
        features = encode_edge_features(edge, feature_schema)
        directed_edges.append((src, dst))
        directed_edges.append((dst, src))
        directed_edge_features.append(features)
        directed_edge_features.append(features)

    edge_dim = int(feature_schema["edge"]["feature_dim"])
    if directed_edges:
        edge_index = torch.tensor(directed_edges, dtype=torch.long).t().contiguous()
        edge_features = torch.tensor(directed_edge_features, dtype=torch.float32)
    else:
        edge_index = torch.empty((2, 0), dtype=torch.long)
        edge_features = torch.empty((0, edge_dim), dtype=torch.float32)
    return {
        "node_features": node_features,
        "edge_index": edge_index,
        "edge_features": edge_features,
    }


def load_feature_schema(schema_path: Path, graph_path: Path) -> dict[str, Any]:
    if schema_path.exists():
        return load_json(schema_path)
    return build_graph_feature_schema(read_jsonl(graph_path))


class StageCPreviewGraphDataset(Dataset):
    def __init__(
        self,
        *,
        preview_path: Path | str,
        graph_path: Path | str,
        split: str,
        max_samples: int | None = None,
    ) -> None:
        self.preview_path = Path(preview_path)
        self.graph_path = Path(graph_path)
        self.split = split
        graph_rows = read_jsonl(self.graph_path)
        self.graphs_by_record_id = {str(row["record_id"]): row for row in graph_rows}
        self.rows: list[dict[str, Any]] = []
        with self.preview_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("split") != split:
                    continue
                self._validate_row(row, line_no)
                graph = self.graphs_by_record_id.get(str(row["record_id"]))
                if graph is None:
                    raise ValueError(f"{self.preview_path}:{line_no}: missing graph for record_id={row['record_id']}")
                if str(graph.get("canonical_hash")) != str(row.get("canonical_hash")):
                    raise ValueError(f"{self.preview_path}:{line_no}: graph canonical_hash mismatch for {row['record_id']}")
                self.rows.append({**row, "_graph": graph})
                if max_samples is not None and len(self.rows) >= max_samples:
                    break

    def _validate_row(self, row: dict[str, Any], line_no: int) -> None:
        required = [
            "record_id",
            "canonical_smiles",
            "canonical_hash",
            "input_ids_view1",
            "attention_mask_view1",
            "restore_labels",
            "restore_label_mask",
        ]
        for field in required:
            if field not in row:
                raise ValueError(f"{self.preview_path}:{line_no}: missing {field}")

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self.rows[index]


def collate_stage_c_records(
    records: list[dict[str, Any]],
    *,
    pad_token_id: int,
    label_pad_token_id: int,
    feature_schema: dict[str, Any],
) -> StageCBatch:
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

    node_tensors: list[torch.Tensor] = []
    edge_index_tensors: list[torch.Tensor] = []
    edge_feature_tensors: list[torch.Tensor] = []
    graph_batch_parts: list[torch.Tensor] = []
    node_offset = 0

    for graph_index, row in enumerate(records):
        input_len = len(row["input_ids_view1"])
        label_len = len(row["restore_labels"])
        input_ids.append([int(token_id) for token_id in row["input_ids_view1"]] + [pad_token_id] * (max_input_len - input_len))
        attention_masks.append([int(value) for value in row["attention_mask_view1"]] + [0] * (max_input_len - input_len))
        labels.append([int(token_id) for token_id in row["restore_labels"]] + [label_pad_token_id] * (max_label_len - label_len))
        label_masks.append([bool(value) for value in row["restore_label_mask"]] + [False] * (max_label_len - label_len))
        record_ids.append(str(row["record_id"]))
        canonical_smiles.append(str(row["canonical_smiles"]))
        target_texts.append(str(row.get("target_text", "")))

        encoded_graph = encode_graph_row(row["_graph"], feature_schema)
        node_features = encoded_graph["node_features"]
        edge_index = encoded_graph["edge_index"]
        node_tensors.append(node_features)
        if edge_index.numel():
            edge_index_tensors.append(edge_index + node_offset)
            edge_feature_tensors.append(encoded_graph["edge_features"])
        graph_batch_parts.append(torch.full((node_features.shape[0],), graph_index, dtype=torch.long))
        node_offset += node_features.shape[0]

    edge_dim = int(feature_schema["edge"]["feature_dim"])
    edge_index = torch.cat(edge_index_tensors, dim=1) if edge_index_tensors else torch.empty((2, 0), dtype=torch.long)
    edge_features = torch.cat(edge_feature_tensors, dim=0) if edge_feature_tensors else torch.empty((0, edge_dim), dtype=torch.float32)

    return StageCBatch(
        input_ids_view1=torch.tensor(input_ids, dtype=torch.long),
        attention_mask_view1=torch.tensor(attention_masks, dtype=torch.long),
        restore_labels=torch.tensor(labels, dtype=torch.long),
        restore_label_mask=torch.tensor(label_masks, dtype=torch.bool),
        node_features=torch.cat(node_tensors, dim=0),
        edge_index=edge_index,
        edge_features=edge_features,
        graph_batch=torch.cat(graph_batch_parts, dim=0),
        record_ids=record_ids,
        canonical_smiles=canonical_smiles,
        target_texts=target_texts,
    )


class PureTorchGraphEncoder(nn.Module):
    def __init__(self, *, node_feature_dim: int, edge_feature_dim: int, hidden_size: int, num_layers: int, dropout: float) -> None:
        super().__init__()
        self.node_feature_dim = node_feature_dim
        self.edge_feature_dim = edge_feature_dim
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = nn.Dropout(dropout)
        self.node_projection = nn.Linear(node_feature_dim, hidden_size)
        self.edge_projection = nn.Linear(edge_feature_dim, hidden_size) if edge_feature_dim > 0 else None
        self.layers = nn.ModuleList([nn.Linear(hidden_size * 2, hidden_size) for _ in range(num_layers)])
        self.norms = nn.ModuleList([nn.LayerNorm(hidden_size) for _ in range(num_layers)])

    def forward(
        self,
        node_features: torch.Tensor,
        edge_index: torch.Tensor,
        edge_features: torch.Tensor,
        graph_batch: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        h = F.gelu(self.node_projection(node_features.float()))
        for layer, norm in zip(self.layers, self.norms):
            agg = torch.zeros_like(h)
            if edge_index.numel():
                src, dst = edge_index[0], edge_index[1]
                edge_hidden = self.edge_projection(edge_features.float()) if self.edge_projection is not None else 0.0
                messages = h[src] + edge_hidden
                agg.index_add_(0, dst, messages)
                degree = torch.zeros((h.shape[0], 1), dtype=h.dtype, device=h.device)
                degree.index_add_(0, dst, torch.ones((dst.shape[0], 1), dtype=h.dtype, device=h.device))
                agg = agg / degree.clamp_min(1.0)
            update = F.gelu(layer(torch.cat([h, agg], dim=-1)))
            h = norm(h + self.dropout(update))

        graph_count = int(graph_batch.max().item()) + 1
        graph_hidden = torch.zeros((graph_count, h.shape[-1]), dtype=h.dtype, device=h.device)
        graph_hidden.index_add_(0, graph_batch, h)
        counts = torch.bincount(graph_batch, minlength=graph_count).to(dtype=h.dtype, device=h.device).unsqueeze(-1)
        graph_hidden = graph_hidden / counts.clamp_min(1.0)
        return h, graph_hidden


class ProjectionHead(nn.Module):
    def __init__(self, *, input_dim: int, output_dim: int, hidden_dim: int | None = None, dropout: float = 0.0) -> None:
        super().__init__()
        hidden = hidden_dim or output_dim
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, output_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.net(x.float()), dim=-1)


def mean_pool_text(hidden: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.to(dtype=hidden.dtype).unsqueeze(-1)
    return (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1.0)


def symmetric_infonce_loss(z_text: torch.Tensor, z_graph: torch.Tensor, temperature: float) -> torch.Tensor:
    if z_text.shape[0] != z_graph.shape[0]:
        raise ValueError("z_text and z_graph batch sizes must match")
    if z_text.shape[0] < 2:
        return (z_text.sum() + z_graph.sum()) * 0.0
    logits = z_text @ z_graph.t() / temperature
    labels = torch.arange(z_text.shape[0], device=z_text.device)
    text_to_graph = F.cross_entropy(logits, labels)
    graph_to_text = F.cross_entropy(logits.t(), labels)
    return 0.5 * (text_to_graph + graph_to_text)


def build_restore_memory(
    *,
    text_hidden: torch.Tensor,
    text_attention_mask: torch.Tensor,
    graph_node_hidden: torch.Tensor,
    graph_batch: torch.Tensor,
    graph_memory_projector: nn.Module,
) -> tuple[torch.Tensor, torch.Tensor]:
    batch_size = text_hidden.shape[0]
    counts = torch.bincount(graph_batch, minlength=batch_size)
    max_nodes = int(counts.max().item())
    projected_graph = graph_memory_projector(graph_node_hidden.float()).to(dtype=text_hidden.dtype)
    graph_memory = torch.zeros((batch_size, max_nodes, text_hidden.shape[-1]), dtype=text_hidden.dtype, device=text_hidden.device)
    graph_mask = torch.zeros((batch_size, max_nodes), dtype=text_attention_mask.dtype, device=text_hidden.device)
    for batch_index in range(batch_size):
        selected = projected_graph[graph_batch == batch_index]
        graph_memory[batch_index, : selected.shape[0]] = selected
        graph_mask[batch_index, : selected.shape[0]] = 1
    return torch.cat([text_hidden, graph_memory], dim=1), torch.cat([text_attention_mask, graph_mask], dim=1)


def forward_stage_c(
    *,
    model: nn.Module,
    batch: StageCBatch,
    tokenizer: Any,
    restore_head: RestoreCrossAttentionHead,
    graph_encoder: PureTorchGraphEncoder,
    text_projector: ProjectionHead,
    graph_projector: ProjectionHead,
    graph_memory_projector: nn.Module,
    config: StageCConfig,
) -> StageCForwardOutput:
    text_hidden = forward_encoder_hidden(model, batch)
    graph_node_hidden, graph_hidden = graph_encoder(batch.node_features, batch.edge_index, batch.edge_features, batch.graph_batch)
    z_text = text_projector(mean_pool_text(text_hidden.float(), batch.attention_mask_view1))
    z_graph = graph_projector(graph_hidden)
    align_loss = symmetric_infonce_loss(z_text, z_graph, config.align_temperature)
    restore_memory, restore_memory_mask = build_restore_memory(
        text_hidden=text_hidden,
        text_attention_mask=batch.attention_mask_view1,
        graph_node_hidden=graph_node_hidden,
        graph_batch=batch.graph_batch,
        graph_memory_projector=graph_memory_projector,
    )
    decoder_input = shift_restore_labels_right(
        batch.restore_labels,
        batch.restore_label_mask,
        decoder_start_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id,
    )
    logits = restore_head(decoder_input, restore_memory, restore_memory_mask)
    restore_loss = masked_cross_entropy(logits.float(), batch.restore_labels, batch.restore_label_mask)
    total_loss = config.restore_loss_weight * restore_loss + config.align_loss_weight * align_loss
    return StageCForwardOutput(
        total_loss=total_loss,
        restore_loss=restore_loss,
        align_loss=align_loss,
        logits=logits,
        z_text=z_text,
        z_graph=z_graph,
        restore_memory=restore_memory,
        restore_memory_mask=restore_memory_mask,
    )


def retrieval_metrics(z_text: torch.Tensor, z_graph: torch.Tensor) -> dict[str, float]:
    count = z_text.shape[0]
    if count == 0:
        return {
            "text_to_graph_top1": 0.0,
            "text_to_graph_top5": 0.0,
            "graph_to_text_top1": 0.0,
            "graph_to_text_top5": 0.0,
            "mean_positive_similarity": 0.0,
            "mean_negative_similarity": 0.0,
        }
    sim = z_text @ z_graph.t()
    labels = torch.arange(count, device=sim.device)
    top_k = min(5, count)
    text_top = torch.topk(sim, k=top_k, dim=1).indices
    graph_top = torch.topk(sim.t(), k=top_k, dim=1).indices
    positive = sim.diagonal()
    if count > 1:
        negative = sim[~torch.eye(count, dtype=torch.bool, device=sim.device)]
        mean_negative = float(negative.mean().item())
    else:
        mean_negative = 0.0
    return {
        "text_to_graph_top1": float((text_top[:, 0] == labels).float().mean().item()),
        "text_to_graph_top5": float((text_top == labels.unsqueeze(1)).any(dim=1).float().mean().item()),
        "graph_to_text_top1": float((graph_top[:, 0] == labels).float().mean().item()),
        "graph_to_text_top5": float((graph_top == labels.unsqueeze(1)).any(dim=1).float().mean().item()),
        "mean_positive_similarity": float(positive.mean().item()),
        "mean_negative_similarity": mean_negative,
    }


def retrieval_predictions(z_text: torch.Tensor, z_graph: torch.Tensor, record_ids: list[str], *, top_k: int = 5) -> list[dict[str, Any]]:
    if not record_ids:
        return []
    sim = z_text @ z_graph.t()
    k = min(top_k, len(record_ids))
    scores, indices = torch.topk(sim, k=k, dim=1)
    rows: list[dict[str, Any]] = []
    for row_index, record_id in enumerate(record_ids):
        rows.append(
            {
                "record_id": record_id,
                "ranked_graph_record_ids": [record_ids[index] for index in indices[row_index].cpu().tolist()],
                "scores": [float(value) for value in scores[row_index].detach().cpu().tolist()],
            }
        )
    return rows


def evaluate_stage_c(
    *,
    model: nn.Module,
    restore_head: RestoreCrossAttentionHead,
    graph_encoder: PureTorchGraphEncoder,
    text_projector: ProjectionHead,
    graph_projector: ProjectionHead,
    graph_memory_projector: nn.Module,
    dataloader: DataLoader,
    tokenizer: Any,
    config: StageCConfig,
    device: torch.device,
    max_batches: int | None = None,
    decode_sample_limit: int | None = None,
    retrieval_sample_limit: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    model.eval()
    restore_head.eval()
    graph_encoder.eval()
    text_projector.eval()
    graph_projector.eval()
    graph_memory_projector.eval()
    if decode_sample_limit is None:
        decode_sample_limit = config.eval_decode_samples
    if retrieval_sample_limit is None:
        retrieval_sample_limit = config.eval_retrieval_samples

    total_losses: list[float] = []
    restore_losses: list[float] = []
    align_losses: list[float] = []
    accuracies: list[float] = []
    total = 0
    exact_matches = 0
    rdkit_valid = 0
    two_attachment_valid = 0
    canonical_matches = 0
    decoded_count = 0
    failed_cases: list[dict[str, Any]] = []
    retrieval_ids: list[str] = []
    retrieval_text: list[torch.Tensor] = []
    retrieval_graph: list[torch.Tensor] = []

    with torch.no_grad():
        for batch_index, batch in enumerate(dataloader):
            if max_batches is not None and batch_index >= max_batches:
                break
            batch = batch.to(device)
            output = forward_stage_c(
                model=model,
                batch=batch,
                tokenizer=tokenizer,
                restore_head=restore_head,
                graph_encoder=graph_encoder,
                text_projector=text_projector,
                graph_projector=graph_projector,
                graph_memory_projector=graph_memory_projector,
                config=config,
            )
            total_losses.append(float(output.total_loss.item()))
            restore_losses.append(float(output.restore_loss.item()))
            align_losses.append(float(output.align_loss.item()))
            accuracies.append(token_accuracy(output.logits, batch.restore_labels, batch.restore_label_mask))
            total += len(batch.record_ids)

            remaining_retrieval = max(retrieval_sample_limit - len(retrieval_ids), 0)
            if remaining_retrieval:
                take = min(remaining_retrieval, output.z_text.shape[0])
                retrieval_ids.extend(batch.record_ids[:take])
                retrieval_text.append(output.z_text[:take].detach().cpu())
                retrieval_graph.append(output.z_graph[:take].detach().cpu())

            remaining_decode = max(decode_sample_limit - decoded_count, 0)
            if remaining_decode:
                decode_batch_size = min(remaining_decode, batch.input_ids_view1.shape[0])
                decoded_ids = greedy_decode_restore(
                    restore_head=restore_head,
                    encoder_hidden_states=output.restore_memory[:decode_batch_size],
                    encoder_attention_mask=output.restore_memory_mask[:decode_batch_size],
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
                        failed_cases.append({"record_id": batch.record_ids[row_index], "target": target, **result})

    z_text = torch.cat(retrieval_text, dim=0) if retrieval_text else torch.empty((0, config.align_dim))
    z_graph = torch.cat(retrieval_graph, dim=0) if retrieval_graph else torch.empty((0, config.align_dim))
    retrieval = retrieval_metrics(z_text, z_graph)
    predictions = retrieval_predictions(z_text, z_graph, retrieval_ids)
    decode_denom = max(decoded_count, 1)
    metrics = {
        "loss": sum(total_losses) / max(len(total_losses), 1),
        "restore_loss": sum(restore_losses) / max(len(restore_losses), 1),
        "align_loss": sum(align_losses) / max(len(align_losses), 1),
        "token_accuracy": sum(accuracies) / max(len(accuracies), 1),
        "exact_string_match": exact_matches / decode_denom,
        "rdkit_validity": rdkit_valid / decode_denom,
        "two_attachment_validity": two_attachment_valid / decode_denom,
        "canonical_match": canonical_matches / decode_denom,
        "sample_count": total,
        "decoded_sample_count": decoded_count,
        "retrieval_sample_count": len(retrieval_ids),
        **retrieval,
    }
    return metrics, failed_cases, predictions


def build_optimizer(
    *,
    model: nn.Module,
    restore_head: nn.Module,
    graph_encoder: nn.Module,
    text_projector: nn.Module,
    graph_projector: nn.Module,
    graph_memory_projector: nn.Module,
    config: StageCConfig,
) -> torch.optim.Optimizer:
    return torch.optim.AdamW(
        [
            {"params": [param for param in model.parameters() if param.requires_grad], "lr": config.learning_rate_lora},
            {"params": restore_head.parameters(), "lr": config.learning_rate_restore_head},
            {"params": graph_encoder.parameters(), "lr": config.learning_rate_graph_encoder},
            {"params": text_projector.parameters(), "lr": config.learning_rate_projectors},
            {"params": graph_projector.parameters(), "lr": config.learning_rate_projectors},
            {"params": graph_memory_projector.parameters(), "lr": config.learning_rate_projectors},
        ],
        weight_decay=config.weight_decay,
    )


def save_module_checkpoint(checkpoint_dir: Path, module: nn.Module, filename: str, config: dict[str, Any]) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    torch.save(module.state_dict(), checkpoint_dir / filename)
    (checkpoint_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_eval_report(path: Path, metrics: dict[str, Any], config: StageCConfig) -> None:
    lines = [
        "# Stage C Non-vocab BaseLite Warmup Smoke Eval Report",
        "",
        "This checkpoint is a Stage C smoke artifact for `L_restore + L_align`, not a formal long-run checkpoint.",
        "",
        f"- max epochs: `{config.max_epochs}`",
        f"- precision: `{config.precision}`",
        f"- preview path: `{config.preview_path}`",
        f"- graph path: `{config.graph_path}`",
        "",
        "## Metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def reset_epoch_metrics(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in (EPOCH_METRICS_JSONL, EPOCH_METRICS_CSV):
        path = output_dir / filename
        if path.exists():
            path.unlink()


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
        writer = csv.DictWriter(handle, fieldnames=EPOCH_METRIC_CSV_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(flat_row)


def save_stage_c_artifacts(
    *,
    output_dir: Path,
    model: Any,
    restore_head: RestoreCrossAttentionHead,
    graph_encoder: PureTorchGraphEncoder,
    text_projector: ProjectionHead,
    graph_projector: ProjectionHead,
    graph_memory_projector: nn.Module,
    tokenizer: Any,
    config: StageCConfig,
    metrics: dict[str, Any],
    failed_cases: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    feature_schema: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(model, "save_pretrained"):
        model.save_pretrained(output_dir / "lora_adapter")
    save_restore_checkpoint(output_dir / "restore_head", restore_head, asdict(config))
    save_module_checkpoint(
        output_dir / "graph_encoder",
        graph_encoder,
        "graph_encoder.pt",
        {
            "node_feature_dim": graph_encoder.node_feature_dim,
            "edge_feature_dim": graph_encoder.edge_feature_dim,
            "hidden_size": graph_encoder.hidden_size,
            "num_layers": graph_encoder.num_layers,
            "graph_feature_schema": feature_schema,
        },
    )
    (output_dir / "projectors").mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "text_projector": text_projector.state_dict(),
            "graph_projector": graph_projector.state_dict(),
            "graph_memory_projector": graph_memory_projector.state_dict(),
        },
        output_dir / "projectors" / "projectors.pt",
    )
    (output_dir / "projectors" / "config.json").write_text(
        json.dumps(
            {
                "align_dim": config.align_dim,
                "graph_hidden_size": config.graph_hidden_size,
                "restore_encoder_hidden_size": restore_head.encoder_hidden_size,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    tokenizer.save_pretrained(output_dir / "tokenizer")
    (output_dir / "training_config.json").write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "eval_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (output_dir / "failed_cases.jsonl").open("w", encoding="utf-8") as handle:
        for row in failed_cases:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    with (output_dir / "retrieval_predictions.jsonl").open("w", encoding="utf-8") as handle:
        for row in retrieval_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    write_eval_report(output_dir / "eval_report.md", metrics, config)


def save_checkpoint_with_eval(
    *,
    checkpoint_dir: Path,
    checkpoint_name: str,
    epoch: int,
    optimizer_step: int,
    model: Any,
    restore_head: RestoreCrossAttentionHead,
    graph_encoder: PureTorchGraphEncoder,
    text_projector: ProjectionHead,
    graph_projector: ProjectionHead,
    graph_memory_projector: nn.Module,
    dataloader: DataLoader,
    tokenizer: Any,
    config: StageCConfig,
    device: torch.device,
    feature_schema: dict[str, Any],
    recent_train_loss: float | None,
    epoch_train_loss_mean: float | None = None,
) -> dict[str, Any]:
    max_batches = None
    if config.checkpoint_eval_samples > 0:
        max_batches = math.ceil(config.checkpoint_eval_samples / config.per_device_eval_batch_size)
    metrics, failed_cases, retrieval_rows = evaluate_stage_c(
        model=model,
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        dataloader=dataloader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        max_batches=max_batches,
        decode_sample_limit=config.checkpoint_eval_decode_samples,
        retrieval_sample_limit=config.checkpoint_eval_retrieval_samples,
    )
    metrics = {
        **metrics,
        "checkpoint_name": checkpoint_name,
        "checkpoint_epoch": epoch,
        "checkpoint_optimizer_step": optimizer_step,
        "checkpoint_recent_train_loss": recent_train_loss,
        "checkpoint_epoch_train_loss_mean": epoch_train_loss_mean,
    }
    save_stage_c_artifacts(
        output_dir=checkpoint_dir,
        model=model,
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        tokenizer=tokenizer,
        config=config,
        metrics=metrics,
        failed_cases=failed_cases,
        retrieval_rows=retrieval_rows,
        feature_schema=feature_schema,
    )
    (checkpoint_dir / "checkpoint_metadata.json").write_text(
        json.dumps(
            {
                "checkpoint_name": checkpoint_name,
                "epoch": epoch,
                "optimizer_step": optimizer_step,
                "recent_train_loss": recent_train_loss,
                "epoch_train_loss_mean": epoch_train_loss_mean,
                "eval_sample_limit": config.checkpoint_eval_samples,
                "eval_decode_sample_limit": config.checkpoint_eval_decode_samples,
                "eval_retrieval_sample_limit": config.checkpoint_eval_retrieval_samples,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return metrics


def copy_config_snapshot(config_path: Path, output_dir: Path) -> None:
    if config_path.exists():
        shutil.copy2(config_path, output_dir / config_path.name)


def validate_training_config(config: StageCConfig) -> None:
    if config.per_device_train_batch_size < 2:
        raise ValueError("Stage C InfoNCE smoke requires per_device_train_batch_size >= 2")
    if config.checkpoint_eval_samples < 0:
        raise ValueError("checkpoint_eval_samples must be >= 0; use 0 for full validation")
    if not config.early_stopping_enabled:
        return
    if not config.checkpoint_at_epoch_end:
        raise ValueError("Stage C early stopping currently requires checkpoint_at_epoch_end=true")
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


def build_stage_c_modules(
    *,
    config: StageCConfig,
    tokenizer: Any,
    model_hidden_size: int,
    feature_schema: dict[str, Any],
    device: torch.device,
) -> tuple[RestoreCrossAttentionHead, PureTorchGraphEncoder, ProjectionHead, ProjectionHead, nn.Module]:
    node_dim, edge_dim = schema_feature_dims(feature_schema)
    restore_head = RestoreCrossAttentionHead(
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
    graph_encoder = PureTorchGraphEncoder(
        node_feature_dim=node_dim,
        edge_feature_dim=edge_dim,
        hidden_size=config.graph_hidden_size,
        num_layers=config.graph_num_layers,
        dropout=config.graph_dropout,
    ).to(device=device)
    text_projector = ProjectionHead(input_dim=model_hidden_size, output_dim=config.align_dim, dropout=config.graph_dropout).to(device=device)
    graph_projector = ProjectionHead(input_dim=config.graph_hidden_size, output_dim=config.align_dim, dropout=config.graph_dropout).to(device=device)
    graph_memory_projector = nn.Linear(config.graph_hidden_size, model_hidden_size).to(device=device)
    return restore_head, graph_encoder, text_projector, graph_projector, graph_memory_projector


def run_reload_smoke(
    *,
    model_name_or_path: str,
    output_dir: Path,
    tokenizer: Any,
    config: StageCConfig,
    feature_schema: dict[str, Any],
    valid_dataset: StageCPreviewGraphDataset,
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
    hidden_size = int(reloaded_model.config.hidden_size)
    restore_head, graph_encoder, text_projector, graph_projector, graph_memory_projector = build_stage_c_modules(
        config=config,
        tokenizer=tokenizer,
        model_hidden_size=hidden_size,
        feature_schema=feature_schema,
        device=device,
    )
    restore_head.load_state_dict(torch.load(output_dir / "restore_head" / "restore_head.pt", map_location=device))
    graph_encoder.load_state_dict(torch.load(output_dir / "graph_encoder" / "graph_encoder.pt", map_location=device))
    projector_state = torch.load(output_dir / "projectors" / "projectors.pt", map_location=device)
    text_projector.load_state_dict(projector_state["text_projector"])
    graph_projector.load_state_dict(projector_state["graph_projector"])
    graph_memory_projector.load_state_dict(projector_state["graph_memory_projector"])

    smoke_loader = DataLoader(valid_dataset, batch_size=1, shuffle=False, collate_fn=collate_fn)
    batch = next(iter(smoke_loader)).to(device)
    with torch.no_grad():
        output = forward_stage_c(
            model=reloaded_model,
            batch=batch,
            tokenizer=tokenizer,
            restore_head=restore_head,
            graph_encoder=graph_encoder,
            text_projector=text_projector,
            graph_projector=graph_projector,
            graph_memory_projector=graph_memory_projector,
            config=config,
        )
        decoded = greedy_decode_restore(
            restore_head=restore_head,
            encoder_hidden_states=output.restore_memory,
            encoder_attention_mask=output.restore_memory_mask,
            decoder_start_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
            max_length=config.max_seq_len_restore_label,
        )
    result = {
        "status": "passed",
        "record_id": batch.record_ids[0],
        "decoded_token_count": int(decoded.shape[1]),
        "align_loss": float(output.align_loss.item()),
        "restore_loss": float(output.restore_loss.item()),
    }
    (output_dir / "reload_smoke.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Stage C non-vocab BaseLite warmup smoke.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--model-name-or-path", required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--preview-path", type=Path, default=None)
    parser.add_argument("--graph-path", type=Path, default=None)
    parser.add_argument("--graph-feature-schema-path", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

    args = parse_args()
    config = load_yaml_config(args.config)
    updates: dict[str, Any] = {}
    if args.output_dir is not None:
        updates["output_dir"] = str(args.output_dir)
    if args.preview_path is not None:
        updates["preview_path"] = str(args.preview_path)
    if args.graph_path is not None:
        updates["graph_path"] = str(args.graph_path)
    if args.graph_feature_schema_path is not None:
        updates["graph_feature_schema_path"] = str(args.graph_feature_schema_path)
    if updates:
        config = StageCConfig(**{**asdict(config), **updates})

    set_seed(config.seed)
    if not torch.cuda.is_available():
        raise SystemExit("Stage C Qwen2.5-7B bf16 LoRA smoke training requires a CUDA GPU.")
    validate_training_config(config)
    device = torch.device("cuda")
    feature_schema = load_feature_schema(Path(config.graph_feature_schema_path), Path(config.graph_path))

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
    restore_head, graph_encoder, text_projector, graph_projector, graph_memory_projector = build_stage_c_modules(
        config=config,
        tokenizer=tokenizer,
        model_hidden_size=hidden_size,
        feature_schema=feature_schema,
        device=device,
    )
    train_dataset = StageCPreviewGraphDataset(
        preview_path=config.preview_path,
        graph_path=config.graph_path,
        split="train",
        max_samples=config.max_train_samples,
    )
    valid_dataset = StageCPreviewGraphDataset(
        preview_path=config.preview_path,
        graph_path=config.graph_path,
        split="valid",
        max_samples=config.max_valid_samples,
    )
    collate = lambda rows: collate_stage_c_records(
        rows,
        pad_token_id=tokenizer.pad_token_id,
        label_pad_token_id=tokenizer.pad_token_id,
        feature_schema=feature_schema,
    )
    train_loader = DataLoader(train_dataset, batch_size=config.per_device_train_batch_size, shuffle=True, collate_fn=collate)
    valid_loader = DataLoader(valid_dataset, batch_size=config.per_device_eval_batch_size, shuffle=False, collate_fn=collate)
    optimizer = build_optimizer(
        model=model,
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        config=config,
    )

    train_losses: list[float] = []
    optimizer.zero_grad(set_to_none=True)
    optimizer_steps = 0
    completed_epochs = 0
    stop_training = False
    early_stop_reason: str | None = None
    early_stop_wait = 0
    best_early_metric: float | None = None
    best_early_checkpoint: str | None = None
    trainable_params = (
        [param for param in model.parameters() if param.requires_grad]
        + list(restore_head.parameters())
        + list(graph_encoder.parameters())
        + list(text_projector.parameters())
        + list(graph_projector.parameters())
        + list(graph_memory_projector.parameters())
    )
    output_dir = Path(config.output_dir)
    reset_epoch_metrics(output_dir)
    for epoch_index in range(1, config.max_epochs + 1):
        completed_epochs = epoch_index
        epoch_train_losses: list[float] = []
        for step, batch in enumerate(train_loader, start=1):
            model.train()
            restore_head.train()
            graph_encoder.train()
            text_projector.train()
            graph_projector.train()
            graph_memory_projector.train()
            batch = batch.to(device)
            output = forward_stage_c(
                model=model,
                batch=batch,
                tokenizer=tokenizer,
                restore_head=restore_head,
                graph_encoder=graph_encoder,
                text_projector=text_projector,
                graph_projector=graph_projector,
                graph_memory_projector=graph_memory_projector,
                config=config,
            )
            if not torch.isfinite(output.total_loss):
                raise FloatingPointError(f"non-finite training loss at step {step}: {output.total_loss.item()}")
            (output.total_loss / config.gradient_accumulation_steps).backward()
            loss_value = float(output.total_loss.item())
            train_losses.append(loss_value)
            epoch_train_losses.append(loss_value)

            if step % config.gradient_accumulation_steps == 0 or step == len(train_loader):
                torch.nn.utils.clip_grad_norm_(trainable_params, config.max_grad_norm)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                optimizer_steps += 1
                if optimizer_steps % config.quick_eval_every_steps == 0:
                    quick_batches = math.ceil(config.quick_eval_samples / config.per_device_eval_batch_size)
                    quick_metrics, _, _ = evaluate_stage_c(
                        model=model,
                        restore_head=restore_head,
                        graph_encoder=graph_encoder,
                        text_projector=text_projector,
                        graph_projector=graph_projector,
                        graph_memory_projector=graph_memory_projector,
                        dataloader=valid_loader,
                        tokenizer=tokenizer,
                        config=config,
                        device=device,
                        max_batches=quick_batches,
                        decode_sample_limit=config.quick_eval_decode_samples,
                        retrieval_sample_limit=config.quick_eval_retrieval_samples,
                    )
                    print(json.dumps({"optimizer_step": optimizer_steps, "train_loss": train_losses[-1], "quick_valid": quick_metrics}, ensure_ascii=False))
                if config.checkpoint_every_steps > 0 and optimizer_steps % config.checkpoint_every_steps == 0:
                    checkpoint_name = f"step_{optimizer_steps:06d}"
                    checkpoint_metrics = save_checkpoint_with_eval(
                        checkpoint_dir=output_dir / "checkpoints" / checkpoint_name,
                        checkpoint_name=checkpoint_name,
                        epoch=epoch_index,
                        optimizer_step=optimizer_steps,
                        model=model,
                        restore_head=restore_head,
                        graph_encoder=graph_encoder,
                        text_projector=text_projector,
                        graph_projector=graph_projector,
                        graph_memory_projector=graph_memory_projector,
                        dataloader=valid_loader,
                        tokenizer=tokenizer,
                        config=config,
                        device=device,
                        feature_schema=feature_schema,
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
                graph_encoder=graph_encoder,
                text_projector=text_projector,
                graph_projector=graph_projector,
                graph_memory_projector=graph_memory_projector,
                dataloader=valid_loader,
                tokenizer=tokenizer,
                config=config,
                device=device,
                feature_schema=feature_schema,
                recent_train_loss=train_losses[-1] if train_losses else None,
                epoch_train_loss_mean=epoch_train_loss_mean,
            )
            copy_config_snapshot(args.config, output_dir / "checkpoints" / checkpoint_name)
            print(json.dumps({"checkpoint": checkpoint_name, "metrics": checkpoint_metrics}, ensure_ascii=False))
            early_stopping_state: dict[str, Any] | None = None
            if config.early_stopping_enabled:
                raw_metric = checkpoint_metrics.get(config.early_stopping_metric)
                if not isinstance(raw_metric, (int, float)) or not math.isfinite(float(raw_metric)):
                    raise ValueError(f"early stopping metric is missing or non-finite: {config.early_stopping_metric}")
                metric_value = float(raw_metric)
                improved = early_stopping_is_improvement(
                    metric_value,
                    best_early_metric,
                    mode=config.early_stopping_mode,
                    min_delta=config.early_stopping_min_delta,
                )
                if improved:
                    best_early_metric = metric_value
                    best_early_checkpoint = checkpoint_name
                    early_stop_wait = 0
                elif epoch_index >= config.early_stopping_min_epochs:
                    early_stop_wait += 1
                    if early_stop_wait >= config.early_stopping_patience:
                        early_stop_reason = (
                            f"{config.early_stopping_metric} did not improve by "
                            f"{config.early_stopping_min_delta} for {early_stop_wait} epoch checkpoints"
                        )
                        stop_training = True
                early_stopping_state = {
                    "enabled": True,
                    "metric": config.early_stopping_metric,
                    "mode": config.early_stopping_mode,
                    "current": metric_value,
                    "best": best_early_metric,
                    "best_checkpoint": best_early_checkpoint,
                    "wait": early_stop_wait,
                    "stop_training": stop_training,
                    "reason": early_stop_reason,
                }
                print(
                    json.dumps(
                        {"early_stopping": early_stopping_state},
                        ensure_ascii=False,
                    )
                )
            append_epoch_metrics(output_dir, checkpoint_metrics, early_stopping=early_stopping_state)
        if stop_training:
            break

    metrics, failed_cases, retrieval_rows = evaluate_stage_c(
        model=model,
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        dataloader=valid_loader,
        tokenizer=tokenizer,
        config=config,
        device=device,
    )
    first_window = train_losses[: max(1, len(train_losses) // 5)]
    last_window = train_losses[-max(1, len(train_losses) // 5) :]
    metrics["train_loss_first_window"] = sum(first_window) / len(first_window)
    metrics["train_loss_last_window"] = sum(last_window) / len(last_window)
    metrics["train_loss_decreased"] = metrics["train_loss_last_window"] < metrics["train_loss_first_window"]
    metrics["completed_epochs"] = completed_epochs
    metrics["early_stopped"] = stop_training
    metrics["early_stop_reason"] = early_stop_reason
    metrics["best_early_stopping_metric"] = best_early_metric
    metrics["best_early_stopping_checkpoint"] = best_early_checkpoint
    save_stage_c_artifacts(
        output_dir=output_dir,
        model=model,
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        tokenizer=tokenizer,
        config=config,
        metrics=metrics,
        failed_cases=failed_cases,
        retrieval_rows=retrieval_rows,
        feature_schema=feature_schema,
    )
    copy_config_snapshot(args.config, output_dir)
    del optimizer
    del model
    del restore_head
    del graph_encoder
    del text_projector
    del graph_projector
    del graph_memory_projector
    gc.collect()
    torch.cuda.empty_cache()
    reload_smoke = run_reload_smoke(
        model_name_or_path=args.model_name_or_path,
        output_dir=output_dir,
        tokenizer=tokenizer,
        config=config,
        feature_schema=feature_schema,
        valid_dataset=valid_dataset,
        collate_fn=collate,
        device=device,
    )
    print(json.dumps({"output_dir": str(output_dir), "metrics": metrics, "reload_smoke": reload_smoke}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
