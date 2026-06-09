from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import torch

from scripts.build_stage_c_non_vocab_dataset import (
    build_graph_feature_schema,
    build_stage_c_audit,
    validate_join,
)
from scripts.train_stage_b_restore_full import RestoreCrossAttentionHead, load_yaml_config as load_stage_b_config, masked_cross_entropy
from scripts.train_stage_b_restore_curriculum import allocate_strategy_counts, build_curriculum_epoch_rows
from scripts.train_stage_c_non_vocab_curriculum import update_early_stopping_monitor
from scripts.train_stage_c_non_vocab_full import (
    ProjectionHead,
    PureTorchGraphEncoder,
    StageCConfig,
    StageCPreviewGraphDataset,
    append_epoch_metrics,
    build_restore_memory,
    collate_stage_c_records,
    early_stopping_is_improvement,
    encode_graph_row,
    formal_eval_decode_sample_limit,
    formal_eval_retrieval_sample_limit,
    forward_stage_c,
    load_yaml_config,
    retrieval_metrics,
    save_module_checkpoint,
    symmetric_infonce_loss,
    unique_record_sample_limit,
    validate_training_config,
    write_eval_report,
    write_extra_stage_c_eval_outputs,
)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def graph_row(record_id: str = "ru_1", canonical_hash: str = "hash_1") -> dict:
    return {
        "record_id": record_id,
        "canonical_hash": canonical_hash,
        "canonical_smiles": "*CC*",
        "graph_hash": "graph_1",
        "attachment_atom_ids": [0, 2],
        "nodes": [
            {
                "atom_id": 0,
                "element": "*",
                "atomic_num": 0,
                "degree": 1,
                "formal_charge": 0,
                "aromatic": False,
                "is_attachment": True,
                "ring_membership": False,
                "hybridization": "UNSPECIFIED",
                "attachment_role": "attachment_1",
            },
            {
                "atom_id": 1,
                "element": "C",
                "atomic_num": 6,
                "degree": 2,
                "formal_charge": 0,
                "aromatic": False,
                "is_attachment": False,
                "ring_membership": False,
                "hybridization": "SP3",
                "attachment_role": None,
            },
            {
                "atom_id": 2,
                "element": "*",
                "atomic_num": 0,
                "degree": 1,
                "formal_charge": 0,
                "aromatic": False,
                "is_attachment": True,
                "ring_membership": False,
                "hybridization": "UNSPECIFIED",
                "attachment_role": "attachment_2",
            },
        ],
        "edges": [
            {
                "begin_atom_id": 0,
                "end_atom_id": 1,
                "bond_type": "SINGLE",
                "aromatic": False,
                "is_periodic_edge": False,
                "is_repeat_connection": False,
            },
            {
                "begin_atom_id": 1,
                "end_atom_id": 2,
                "bond_type": "SINGLE",
                "aromatic": False,
                "is_periodic_edge": False,
                "is_repeat_connection": False,
            },
        ],
    }


def preview_row(record_id: str = "ru_1", split: str = "train", canonical_hash: str = "hash_1") -> dict:
    return {
        "record_id": record_id,
        "split": split,
        "canonical_smiles": "*CC*",
        "canonical_hash": canonical_hash,
        "graph_hash": "graph_1",
        "input_ids_view1": [1, 2, 3],
        "attention_mask_view1": [1, 1, 1],
        "restore_labels": [4, 5, 9],
        "restore_label_mask": [True, True, True],
        "target_text": "*CC*<eos>",
    }


def test_stage_c_audit_writes_manifest_schema_and_report(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    for split in ["train", "valid", "test"]:
        write_jsonl(dataset_dir / f"{split}.jsonl", [preview_row(record_id=f"{split}_1", split=split, canonical_hash=f"{split}_hash")])
    graphs = [graph_row(record_id=f"{split}_1", canonical_hash=f"{split}_hash") for split in ["train", "valid", "test"]]
    graph_path = tmp_path / "graphs.jsonl"
    write_jsonl(graph_path, graphs)

    manifest = build_stage_c_audit(dataset_dir, graph_path, tmp_path / "stage_c")

    assert manifest["counts"]["dataset_rows"] == 3
    assert manifest["join_quality"]["missing_graph_by_record_id"] == 0
    assert (tmp_path / "stage_c" / "stage_c_manifest.json").exists()
    assert (tmp_path / "stage_c" / "graph_feature_schema.json").exists()
    assert "missing graph by record_id: `0`" in (tmp_path / "stage_c" / "stage_c_join_report.md").read_text(encoding="utf-8")


def test_stage_c_audit_rejects_canonical_hash_mismatch() -> None:
    dataset = [preview_row(record_id="ru_1", split="train", canonical_hash="dataset_hash")]
    graphs = [graph_row(record_id="ru_1", canonical_hash="graph_hash")]

    try:
        validate_join(dataset, graphs)
    except ValueError as exc:
        assert "canonical_hash_mismatches=1" in str(exc)
    else:
        raise AssertionError("expected canonical hash mismatch to fail Stage C join")


def test_graph_tensorizer_bidirectional_edges_and_batching(tmp_path: Path) -> None:
    graphs = [graph_row("ru_1", "hash_1"), graph_row("ru_2", "hash_2")]
    schema = build_graph_feature_schema(graphs)
    encoded = encode_graph_row(graphs[0], schema)

    assert encoded["node_features"].shape == (3, schema["node"]["feature_dim"])
    assert encoded["edge_index"].shape == (2, 4)
    assert encoded["edge_features"].shape == (4, schema["edge"]["feature_dim"])

    preview_path = tmp_path / "preview.jsonl"
    graph_path = tmp_path / "graphs.jsonl"
    write_jsonl(preview_path, [preview_row("ru_1", "train", "hash_1"), preview_row("ru_2", "train", "hash_2")])
    write_jsonl(graph_path, graphs)
    dataset = StageCPreviewGraphDataset(preview_path=preview_path, graph_path=graph_path, split="train")
    batch = collate_stage_c_records([dataset[0], dataset[1]], pad_token_id=0, label_pad_token_id=0, feature_schema=schema)

    assert batch.node_features.shape[0] == 6
    assert batch.edge_index.shape == (2, 8)
    assert batch.graph_batch.tolist() == [0, 0, 0, 1, 1, 1]


def test_graph_encoder_projectors_and_infonce_forward() -> None:
    schema = build_graph_feature_schema([graph_row()])
    encoded = encode_graph_row(graph_row(), schema)
    graph_batch = torch.zeros(encoded["node_features"].shape[0], dtype=torch.long)
    encoder = PureTorchGraphEncoder(
        node_feature_dim=schema["node"]["feature_dim"],
        edge_feature_dim=schema["edge"]["feature_dim"],
        hidden_size=8,
        num_layers=2,
        dropout=0.0,
    )
    node_hidden, graph_hidden = encoder(encoded["node_features"], encoded["edge_index"], encoded["edge_features"], graph_batch)
    projector = ProjectionHead(input_dim=8, output_dim=4, dropout=0.0)
    projected = projector(torch.cat([graph_hidden, graph_hidden + 0.1], dim=0))
    loss = symmetric_infonce_loss(projected, projected, temperature=0.07)

    assert node_hidden.shape == (3, 8)
    assert graph_hidden.shape == (1, 8)
    assert projected.shape == (2, 4)
    assert torch.allclose(projected.norm(dim=-1), torch.ones(2), atol=1e-5)
    assert torch.isfinite(loss)


def test_retrieval_metrics_topk() -> None:
    z_text = torch.eye(3)
    z_graph = torch.eye(3)

    metrics = retrieval_metrics(z_text, z_graph)

    assert metrics["text_to_graph_top1"] == 1.0
    assert metrics["graph_to_text_top1"] == 1.0
    assert metrics["text_to_graph_top5"] == 1.0
    assert metrics["graph_to_text_top5"] == 1.0
    assert metrics["mean_positive_similarity"] == 1.0


def test_tiny_stage_c_forward_backward_and_checkpoint_reload() -> None:
    torch.manual_seed(0)

    class TinyBackbone(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.embedding = torch.nn.Embedding(16, 8)

        def forward(self, input_ids, attention_mask=None, use_cache=False, return_dict=True):
            class Output:
                pass

            output = Output()
            output.last_hidden_state = self.embedding(input_ids)
            return output

    class TinyModel(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.model = TinyBackbone()

    schema = build_graph_feature_schema([graph_row("ru_1", "hash_1"), graph_row("ru_2", "hash_2")])
    rows = [
        {**preview_row("ru_1", "train", "hash_1"), "_graph": graph_row("ru_1", "hash_1")},
        {**preview_row("ru_2", "train", "hash_2"), "_graph": graph_row("ru_2", "hash_2")},
    ]
    batch = collate_stage_c_records(rows, pad_token_id=0, label_pad_token_id=0, feature_schema=schema)

    class Tokenizer:
        eos_token_id = 9
        pad_token_id = 0

    model = TinyModel()
    config = StageCConfig(
        graph_hidden_size=8,
        graph_num_layers=1,
        graph_dropout=0.0,
        align_dim=4,
        restore_hidden_size=8,
        restore_num_layers=1,
        restore_num_attention_heads=2,
        restore_dropout=0.0,
    )
    restore_head = RestoreCrossAttentionHead(
        vocab_size=16,
        hidden_size=8,
        num_layers=1,
        num_attention_heads=2,
        dropout=0.0,
        pad_token_id=0,
        decoder_start_token_id=9,
        encoder_hidden_size=8,
    )
    graph_encoder = PureTorchGraphEncoder(
        node_feature_dim=schema["node"]["feature_dim"],
        edge_feature_dim=schema["edge"]["feature_dim"],
        hidden_size=8,
        num_layers=1,
        dropout=0.0,
    )
    text_projector = ProjectionHead(input_dim=8, output_dim=4, dropout=0.0)
    graph_projector = ProjectionHead(input_dim=8, output_dim=4, dropout=0.0)
    graph_memory_projector = torch.nn.Linear(8, 8)

    output = forward_stage_c(
        model=model,
        batch=batch,
        tokenizer=Tokenizer(),
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        config=config,
    )
    output.total_loss.backward()

    assert torch.isfinite(output.total_loss)
    assert torch.isfinite(output.align_loss)
    assert output.logits.shape == (2, 3, 16)
    assert any(param.grad is not None for param in graph_encoder.parameters())


def test_graph_encoder_and_projector_checkpoint_reload(tmp_path: Path) -> None:
    encoder = PureTorchGraphEncoder(node_feature_dim=5, edge_feature_dim=3, hidden_size=4, num_layers=1, dropout=0.0)
    save_module_checkpoint(tmp_path / "graph_encoder", encoder, "graph_encoder.pt", {"hidden_size": 4})
    reloaded = PureTorchGraphEncoder(node_feature_dim=5, edge_feature_dim=3, hidden_size=4, num_layers=1, dropout=0.0)
    reloaded.load_state_dict(torch.load(tmp_path / "graph_encoder" / "graph_encoder.pt", map_location="cpu"))

    projector = ProjectionHead(input_dim=4, output_dim=2, dropout=0.0)
    path = tmp_path / "projectors.pt"
    torch.save({"graph_projector": projector.state_dict()}, path)
    reloaded_projector = ProjectionHead(input_dim=4, output_dim=2, dropout=0.0)
    reloaded_projector.load_state_dict(torch.load(path, map_location="cpu")["graph_projector"])

    node_features = torch.randn(3, 5)
    edge_index = torch.tensor([[0, 1], [1, 2]])
    edge_features = torch.randn(2, 3)
    graph_batch = torch.zeros(3, dtype=torch.long)
    _, graph_hidden = reloaded(node_features, edge_index, edge_features, graph_batch)
    projected = reloaded_projector(graph_hidden)

    assert graph_hidden.shape == (1, 4)
    assert projected.shape == (1, 2)


def test_build_restore_memory_concatenates_text_and_graph_nodes() -> None:
    text_hidden = torch.randn(2, 3, 4)
    text_mask = torch.ones(2, 3, dtype=torch.long)
    graph_node_hidden = torch.randn(5, 6)
    graph_batch = torch.tensor([0, 0, 1, 1, 1])
    projector = torch.nn.Linear(6, 4)

    memory, mask = build_restore_memory(
        text_hidden=text_hidden,
        text_attention_mask=text_mask,
        graph_node_hidden=graph_node_hidden,
        graph_batch=graph_batch,
        graph_memory_projector=projector,
    )

    assert memory.shape == (2, 6, 4)
    assert mask.tolist() == [[1, 1, 1, 1, 1, 0], [1, 1, 1, 1, 1, 1]]


def test_early_stopping_helpers_and_config_validation() -> None:
    assert early_stopping_is_improvement(0.90, None, mode="min", min_delta=0.001)
    assert early_stopping_is_improvement(0.89, 0.90, mode="min", min_delta=0.001)
    assert not early_stopping_is_improvement(0.8995, 0.90, mode="min", min_delta=0.001)
    assert early_stopping_is_improvement(0.42, 0.40, mode="max", min_delta=0.01)

    validate_training_config(
        StageCConfig(
            checkpoint_at_epoch_end=True,
            early_stopping_enabled=True,
            early_stopping_patience=2,
            early_stopping_min_epochs=4,
        )
    )

    try:
        validate_training_config(StageCConfig(checkpoint_at_epoch_end=False, early_stopping_enabled=True))
    except ValueError as exc:
        assert "checkpoint_at_epoch_end=true" in str(exc)
    else:
        raise AssertionError("expected early stopping without epoch checkpoints to fail")

    validate_training_config(StageCConfig(checkpoint_eval_samples=0))

    try:
        validate_training_config(StageCConfig(checkpoint_eval_samples=-1))
    except ValueError as exc:
        assert "checkpoint_eval_samples" in str(exc)
    else:
        raise AssertionError("expected negative checkpoint_eval_samples to fail")


def test_stage_c_aug_v2_configs_align_with_stage_b_v2() -> None:
    root = Path(__file__).resolve().parents[1]
    stage_b_full = load_stage_b_config(root / "configs" / "stage_b_restore_aug_v2_full_20epoch_bf16.yaml")
    stage_b_curriculum = load_stage_b_config(root / "configs" / "stage_b_restore_aug_v2_curriculum_full_20epoch_bf16.yaml")

    for config_name, output_dir in [
        ("stage_c_non_vocab_aug_v2_full_20epoch_bf16.yaml", "outputs/stage_c_non_vocab_aug_v2_full_30epoch"),
        (
            "stage_c_non_vocab_aug_v2_curriculum_full_20epoch_bf16.yaml",
            "outputs/stage_c_non_vocab_aug_v2_curriculum_full_30epoch",
        ),
    ]:
        config = load_yaml_config(root / "configs" / config_name)
        stage_b = stage_b_curriculum if "curriculum" in config_name else stage_b_full

        assert config.preview_path == stage_b.preview_path == "data/baselite_smiles_aug_v2/training_template_preview.jsonl"
        assert config.output_dir == output_dir
        assert stage_b.max_epochs == 20
        assert config.max_epochs == 30
        assert config.per_device_train_batch_size * config.gradient_accumulation_steps == (
            stage_b.per_device_train_batch_size * stage_b.gradient_accumulation_steps
        )
        assert config.seed == stage_b.seed == 42
        assert config.lora_rank == stage_b.lora_rank
        assert config.lora_alpha == stage_b.lora_alpha
        assert config.lora_dropout == stage_b.lora_dropout
        assert config.lora_target_modules == stage_b.lora_target_modules
        assert config.restore_hidden_size == stage_b.restore_hidden_size
        assert config.restore_num_layers == stage_b.restore_num_layers
        assert config.restore_num_attention_heads == stage_b.restore_num_attention_heads
        assert config.restore_dropout == stage_b.restore_dropout
        assert config.learning_rate_lora == stage_b.learning_rate_lora
        assert config.learning_rate_restore_head == stage_b.learning_rate_restore_head
        assert config.checkpoint_at_epoch_end is True
        assert config.checkpoint_every_steps == 0
        assert config.early_stopping_enabled is True
        assert config.early_stopping_monitor_only is True
        assert config.early_stopping_metric == "restore_loss"
        assert stage_b.early_stopping_metric == "loss"
        assert config.formal_eval_full_decode is True
        assert config.formal_eval_dedup_retrieval is True


def test_stage_c_eval_report_uses_formal_stage_c_wording(tmp_path: Path) -> None:
    report_path = tmp_path / "eval_report.md"
    write_eval_report(
        report_path,
        {"restore_loss": 1.0, "canonical_match": 0.5},
        StageCConfig(max_epochs=20, align_loss_weight=0.2),
    )

    text = report_path.read_text(encoding="utf-8")
    assert "smoke" not in text.lower()
    assert "L_restore + 0.2 * L_align" in text


def test_stage_c_extra_eval_outputs_write_restore_predictions(tmp_path: Path) -> None:
    prediction = {
        "record_id": "ru_1",
        "augmentation_strategy": "identity",
        "decoded_smiles": "*CC*",
        "canonical_match": True,
    }
    write_extra_stage_c_eval_outputs(
        output_dir=tmp_path,
        prefix="robustness",
        split="valid",
        metrics={"canonical_match": 1.0},
        failed_cases=[],
        predictions=[prediction],
        retrieval_rows=[],
        config=StageCConfig(),
        eval_preview_path=tmp_path / "preview.jsonl",
    )

    rows = (tmp_path / "robustness_valid_predictions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0]) == prediction


def test_stage_c_formal_eval_uses_full_decode_and_dedup_retrieval(tmp_path: Path) -> None:
    preview_path = tmp_path / "preview.jsonl"
    graph_path = tmp_path / "graphs.jsonl"
    rows = [
        {**preview_row("ru_1", "valid", "hash_1"), "view_id": "ru_1::identity", "augmentation_strategy": "identity"},
        {
            **preview_row("ru_1", "valid", "hash_1"),
            "view_id": "ru_1::rdkit_random_smiles",
            "augmentation_strategy": "rdkit_random_smiles",
        },
        {**preview_row("ru_2", "valid", "hash_2"), "view_id": "ru_2::identity", "augmentation_strategy": "identity"},
    ]
    write_jsonl(preview_path, rows)
    write_jsonl(graph_path, [graph_row("ru_1", "hash_1"), graph_row("ru_2", "hash_2")])

    dataset = StageCPreviewGraphDataset(preview_path=preview_path, graph_path=graph_path, split="valid")
    config = StageCConfig(formal_eval_full_decode=True, formal_eval_dedup_retrieval=True)

    assert len(dataset) == 3
    assert unique_record_sample_limit(dataset) == 2
    assert formal_eval_decode_sample_limit(config, dataset, configured_limit=0) == 3
    assert formal_eval_retrieval_sample_limit(config, dataset, configured_limit=0) == 2


def test_aug_v2_preview_counts_support_stage_b_stage_c_comparison() -> None:
    root = Path(__file__).resolve().parents[1]
    preview_path = root / "data" / "baselite_smiles_aug_v2" / "training_template_preview.jsonl"
    split_counts: Counter[str] = Counter()
    split_records: dict[str, set[str]] = {"train": set(), "valid": set(), "test": set()}
    strategy_counts: Counter[tuple[str, str]] = Counter()
    with preview_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            split = str(row["split"])
            strategy = str(row.get("augmentation_strategy") or row.get("text_view_1_strategy") or "identity")
            split_counts[split] += 1
            split_records[split].add(str(row["record_id"]))
            strategy_counts[(split, strategy)] += 1

    assert split_counts == Counter({"train": 46320, "valid": 5790, "test": 5790})
    assert {split: len(records) for split, records in split_records.items()} == {"train": 9264, "valid": 1158, "test": 1158}
    for strategy in ("identity", "rdkit_random_smiles", "direction_flip", "attachment_rooted_smiles", "light_denoise"):
        assert strategy_counts[("train", strategy)] == 9264
        assert strategy_counts[("valid", strategy)] == 1158
        assert strategy_counts[("test", strategy)] == 1158


def test_stage_c_curriculum_uses_stage_b_weights_and_monitor_only() -> None:
    rows = []
    for strategy in ("identity", "rdkit_random_smiles", "direction_flip", "attachment_rooted_smiles", "light_denoise"):
        for index in range(4):
            rows.append({"record_id": f"{strategy}_{index}", "augmentation_strategy": strategy})

    epoch_rows, metadata = build_curriculum_epoch_rows(rows, epoch_index=13, seed=42, epoch_target_row_count=20)
    counts = Counter(row["augmentation_strategy"] for row in epoch_rows)

    assert metadata["curriculum_enabled"] is True
    assert counts == Counter(allocate_strategy_counts(20, metadata["curriculum_strategy_weights"]))

    state, best, checkpoint, wait = update_early_stopping_monitor(
        config=StageCConfig(
            early_stopping_enabled=True,
            early_stopping_monitor_only=True,
            early_stopping_min_epochs=1,
            early_stopping_patience=1,
        ),
        checkpoint_metrics={"restore_loss": 1.1},
        checkpoint_name="epoch_002",
        epoch_index=2,
        best_metric=1.0,
        best_checkpoint="epoch_001",
        wait=0,
    )

    assert state is not None
    assert state["monitor_only"] is True
    assert state["stop_training"] is False
    assert state["would_stop_training"] is True
    assert best == 1.0
    assert checkpoint == "epoch_001"
    assert wait == 1


def test_append_epoch_metrics_writes_jsonl_and_csv(tmp_path: Path) -> None:
    metrics = {
        "checkpoint_name": "epoch_001",
        "checkpoint_epoch": 1,
        "checkpoint_optimizer_step": 579,
        "checkpoint_recent_train_loss": 4.2,
        "checkpoint_epoch_train_loss_mean": 4.8,
        "sample_count": 1158,
        "decoded_sample_count": 128,
        "retrieval_sample_count": 512,
        "loss": 3.1,
        "restore_loss": 3.0,
        "align_loss": 1.0,
        "token_accuracy": 0.25,
        "text_to_graph_top1": 0.1,
    }
    early_stopping = {
        "enabled": True,
        "metric": "loss",
        "mode": "min",
        "current": 3.1,
        "best": 3.1,
        "best_checkpoint": "epoch_001",
        "wait": 0,
        "stop_training": False,
        "reason": None,
    }

    append_epoch_metrics(tmp_path, metrics, early_stopping=early_stopping)

    jsonl_row = json.loads((tmp_path / "epoch_metrics.jsonl").read_text(encoding="utf-8"))
    assert jsonl_row["checkpoint_name"] == "epoch_001"
    assert jsonl_row["early_stopping"]["best_checkpoint"] == "epoch_001"

    csv_lines = (tmp_path / "epoch_metrics.csv").read_text(encoding="utf-8").splitlines()
    assert csv_lines[0].startswith("checkpoint_name,checkpoint_epoch,checkpoint_optimizer_step")
    assert "epoch_001,1,579" in csv_lines[1]
