from __future__ import annotations

import json
from pathlib import Path

import torch

from scripts.train_stage_b_restore_full import (
    RestoreBatch,
    RestoreCrossAttentionHead,
    StageBConfig,
    StageAPreviewDataset,
    append_epoch_metrics,
    append_quick_eval_metrics,
    collate_restore_records,
    early_stopping_is_improvement,
    evaluate_restore,
    get_model_backbone,
    greedy_decode_restore,
    masked_cross_entropy,
    reset_training_metric_files,
    save_restore_checkpoint,
    shift_restore_labels_right,
    validate_preview_tokenizer_compatibility,
    validate_decoded_smiles,
)


def write_preview(path: Path) -> None:
    rows = [
        {
            "record_id": "ru_train_1",
            "split": "train",
            "canonical_smiles": "*CC*",
            "input_ids_view1": [10, 11, 12],
            "attention_mask_view1": [1, 1, 1],
            "restore_labels": [20, 21, 99],
            "restore_label_mask": [True, True, True],
            "target_text": "*CC*<eos>",
        },
        {
            "record_id": "ru_valid_1",
            "split": "valid",
            "canonical_smiles": "*CO*",
            "input_ids_view1": [13, 14],
            "attention_mask_view1": [1, 1],
            "restore_labels": [22, 99],
            "restore_label_mask": [True, True],
            "target_text": "*CO*<eos>",
        },
    ]
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_stage_a_preview_dataset_filters_by_split(tmp_path: Path) -> None:
    preview_path = tmp_path / "preview.jsonl"
    write_preview(preview_path)

    train_dataset = StageAPreviewDataset(preview_path, split="train")
    valid_dataset = StageAPreviewDataset(preview_path, split="valid")

    assert len(train_dataset) == 1
    assert len(valid_dataset) == 1
    assert train_dataset[0]["record_id"] == "ru_train_1"
    assert valid_dataset[0]["record_id"] == "ru_valid_1"


def test_collator_pads_inputs_and_restore_labels() -> None:
    records = [
        {
            "record_id": "a",
            "canonical_smiles": "*CC*",
            "input_ids_view1": [1, 2, 3],
            "attention_mask_view1": [1, 1, 1],
            "restore_labels": [4, 5],
            "restore_label_mask": [True, True],
        },
        {
            "record_id": "b",
            "canonical_smiles": "*O*",
            "input_ids_view1": [6],
            "attention_mask_view1": [1],
            "restore_labels": [7, 8, 9],
            "restore_label_mask": [True, True, True],
        },
    ]

    batch = collate_restore_records(records, pad_token_id=0, label_pad_token_id=0)

    assert isinstance(batch, RestoreBatch)
    assert batch.input_ids_view1.tolist() == [[1, 2, 3], [6, 0, 0]]
    assert batch.attention_mask_view1.tolist() == [[1, 1, 1], [1, 0, 0]]
    assert batch.restore_labels.tolist() == [[4, 5, 0], [7, 8, 9]]
    assert batch.restore_label_mask.tolist() == [[True, True, False], [True, True, True]]
    assert batch.record_ids == ["a", "b"]
    assert batch.view_ids == ["identity", "identity"]
    assert batch.augmentation_strategies == ["identity", "identity"]


def test_shift_restore_labels_right_uses_eos_start_token() -> None:
    labels = torch.tensor([[5, 6, 7], [8, 9, 0]])
    mask = torch.tensor([[True, True, True], [True, True, False]])

    shifted = shift_restore_labels_right(labels, mask, decoder_start_token_id=99, pad_token_id=0)

    assert shifted.tolist() == [[99, 5, 6], [99, 8, 0]]


def test_masked_cross_entropy_only_uses_true_mask_positions() -> None:
    logits = torch.tensor(
        [
            [[5.0, 0.0], [0.0, 5.0], [5.0, 0.0]],
            [[0.0, 5.0], [5.0, 0.0], [0.0, 5.0]],
        ]
    )
    labels = torch.tensor([[0, 1, 1], [1, 0, 0]])
    mask = torch.tensor([[True, True, False], [True, False, False]])

    loss = masked_cross_entropy(logits, labels, mask)
    expected = torch.nn.functional.cross_entropy(
        torch.tensor([[5.0, 0.0], [0.0, 5.0], [0.0, 5.0]]),
        torch.tensor([0, 1, 1]),
    )

    assert torch.allclose(loss, expected)


def test_epoch_and_quick_eval_metric_writers(tmp_path: Path) -> None:
    reset_training_metric_files(tmp_path)
    append_quick_eval_metrics(tmp_path, {"optimizer_step": 10, "quick_valid": {"loss": 1.5}})
    append_epoch_metrics(
        tmp_path,
        {
            "checkpoint_name": "epoch_001",
            "checkpoint_epoch": 1,
            "checkpoint_optimizer_step": 12,
            "loss": 1.25,
        },
        early_stopping={
            "enabled": True,
            "metric": "loss",
            "mode": "min",
            "current": 1.25,
            "best": 1.25,
            "best_checkpoint": "epoch_001",
            "wait": 0,
            "stop_training": False,
            "reason": None,
        },
    )

    quick_rows = [json.loads(line) for line in (tmp_path / "quick_eval_metrics.jsonl").read_text().splitlines()]
    epoch_rows = [json.loads(line) for line in (tmp_path / "epoch_metrics.jsonl").read_text().splitlines()]
    csv_text = (tmp_path / "epoch_metrics.csv").read_text()

    assert quick_rows[0]["optimizer_step"] == 10
    assert epoch_rows[0]["early_stopping"]["best_checkpoint"] == "epoch_001"
    assert "checkpoint_name" in csv_text


def test_early_stopping_improvement_modes() -> None:
    assert early_stopping_is_improvement(0.9, 1.0, mode="min", min_delta=0.05)
    assert not early_stopping_is_improvement(0.98, 1.0, mode="min", min_delta=0.05)
    assert early_stopping_is_improvement(0.8, 0.7, mode="max", min_delta=0.05)


def test_greedy_decode_restore_stops_at_eos() -> None:
    class StepHead(torch.nn.Module):
        vocab_size = 5

        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def forward(self, decoder_input_ids, encoder_hidden_states, encoder_attention_mask=None):
            self.calls += 1
            logits = torch.zeros(decoder_input_ids.shape[0], decoder_input_ids.shape[1], self.vocab_size)
            next_token = {1: 2, 2: 3, 3: 4}[self.calls]
            logits[:, -1, next_token] = 10.0
            return logits

    decoded = greedy_decode_restore(
        restore_head=StepHead(),
        encoder_hidden_states=torch.zeros(1, 3, 4),
        encoder_attention_mask=torch.ones(1, 3, dtype=torch.long),
        decoder_start_token_id=1,
        eos_token_id=4,
        max_length=8,
    )

    assert decoded.tolist() == [[2, 3, 4]]


def test_validate_decoded_smiles_reports_validity_and_canonical_match() -> None:
    valid = validate_decoded_smiles("*CC*", target_canonical_smiles="*CC*")
    invalid = validate_decoded_smiles("*C(", target_canonical_smiles="*CC*")
    bad_attachment = validate_decoded_smiles("*CC", target_canonical_smiles="*CC*")

    assert valid["rdkit_valid"] is True
    assert valid["two_attachment_valid"] is True
    assert valid["canonical_match"] is True
    assert invalid["rdkit_valid"] is False
    assert bad_attachment["rdkit_valid"] is True
    assert bad_attachment["two_attachment_valid"] is False


def test_tiny_restore_head_forward_loss_and_checkpoint_reload(tmp_path: Path) -> None:
    torch.manual_seed(0)
    head = RestoreCrossAttentionHead(
        vocab_size=32,
        hidden_size=8,
        num_layers=1,
        num_attention_heads=2,
        dropout=0.0,
        pad_token_id=0,
        decoder_start_token_id=31,
    )
    encoder_hidden = torch.randn(2, 4, 8)
    encoder_mask = torch.ones(2, 4, dtype=torch.long)
    labels = torch.tensor([[1, 2, 3], [4, 5, 0]])
    mask = torch.tensor([[True, True, True], [True, True, False]])

    logits = head(
        shift_restore_labels_right(labels, mask, decoder_start_token_id=31, pad_token_id=0),
        encoder_hidden,
        encoder_mask,
    )
    loss = masked_cross_entropy(logits, labels, mask)
    assert torch.isfinite(loss)
    assert logits.shape == (2, 3, 32)

    checkpoint_dir = tmp_path / "checkpoint"
    save_restore_checkpoint(checkpoint_dir, head, {"hidden_size": 8, "vocab_size": 32})
    reloaded = RestoreCrossAttentionHead(
        vocab_size=32,
        hidden_size=8,
        num_layers=1,
        num_attention_heads=2,
        dropout=0.0,
        pad_token_id=0,
        decoder_start_token_id=31,
    )
    reloaded.load_state_dict(torch.load(checkpoint_dir / "restore_head.pt", map_location="cpu"))
    reloaded_logits = reloaded(
        shift_restore_labels_right(labels, mask, decoder_start_token_id=31, pad_token_id=0),
        encoder_hidden,
        encoder_mask,
    )

    assert reloaded_logits.shape == logits.shape


def test_restore_head_projects_encoder_hidden_size_when_needed() -> None:
    head = RestoreCrossAttentionHead(
        vocab_size=16,
        hidden_size=4,
        encoder_hidden_size=10,
        num_layers=1,
        num_attention_heads=2,
        dropout=0.0,
        pad_token_id=0,
        decoder_start_token_id=15,
    )

    logits = head(
        decoder_input_ids=torch.tensor([[15, 1]]),
        encoder_hidden_states=torch.randn(1, 3, 10),
        encoder_attention_mask=torch.ones(1, 3, dtype=torch.long),
    )

    assert logits.shape == (1, 2, 16)


def test_restore_head_accepts_bf16_encoder_hidden_with_fp32_weights() -> None:
    head = RestoreCrossAttentionHead(
        vocab_size=16,
        hidden_size=4,
        encoder_hidden_size=10,
        num_layers=1,
        num_attention_heads=2,
        dropout=0.0,
        pad_token_id=0,
        decoder_start_token_id=15,
    )

    logits = head(
        decoder_input_ids=torch.tensor([[15, 1]]),
        encoder_hidden_states=torch.randn(1, 3, 10, dtype=torch.bfloat16),
        encoder_attention_mask=torch.ones(1, 3, dtype=torch.long),
    )

    assert logits.dtype == torch.float32
    assert logits.shape == (1, 2, 16)


def test_restore_head_does_not_mask_eos_start_as_padding() -> None:
    head = RestoreCrossAttentionHead(
        vocab_size=16,
        hidden_size=4,
        num_layers=1,
        num_attention_heads=2,
        dropout=0.0,
        pad_token_id=15,
        decoder_start_token_id=15,
    )

    logits = head(
        decoder_input_ids=torch.tensor([[15, 1, 2]]),
        encoder_hidden_states=torch.randn(1, 3, 4),
        encoder_attention_mask=torch.ones(1, 3, dtype=torch.long),
    )

    assert torch.isfinite(logits).all()
    assert logits.shape == (1, 3, 16)


def test_get_model_backbone_unwraps_peft_style_nested_causal_lm() -> None:
    class Backbone(torch.nn.Module):
        pass

    class CausalLM(torch.nn.Module):
        def __init__(self, backbone: torch.nn.Module) -> None:
            super().__init__()
            self.model = backbone

    class PeftStyleWrapper(torch.nn.Module):
        def __init__(self, causal_lm: torch.nn.Module) -> None:
            super().__init__()
            self._base_model = causal_lm

        def get_base_model(self) -> torch.nn.Module:
            return self._base_model

        @property
        def model(self) -> torch.nn.Module:
            raise AssertionError("get_model_backbone should unwrap get_base_model before probing .model")

    backbone = Backbone()

    assert get_model_backbone(PeftStyleWrapper(CausalLM(backbone))) is backbone


def test_validate_preview_tokenizer_compatibility_checks_ids(tmp_path: Path) -> None:
    preview_path = tmp_path / "preview.jsonl"
    row = {
        "record_id": "ru_compat",
        "split": "train",
        "input_text_view1": "view",
        "target_text": "target<eos>",
        "input_ids_view1": [1, 2, 3, 4],
        "restore_labels": [5, 6],
        "canonical_smiles": "*CC*",
        "attention_mask_view1": [1, 1, 1, 1],
        "restore_label_mask": [True, True],
    }
    preview_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    class CompatTokenizer:
        eos_token = "<|endoftext|>"
        eos_token_id = 151643

        def encode(self, text: str, add_special_tokens: bool = False):
            assert add_special_tokens is False
            return [1, 2, 3, 4] if text == "view" else [5, 6]

    validate_preview_tokenizer_compatibility(CompatTokenizer(), preview_path, sample_size=1)


def test_validate_preview_tokenizer_compatibility_rejects_instruct_eos(tmp_path: Path) -> None:
    preview_path = tmp_path / "preview.jsonl"
    preview_path.write_text("", encoding="utf-8")

    class InstructTokenizer:
        eos_token = "<|im_end|>"
        eos_token_id = 151645

    try:
        validate_preview_tokenizer_compatibility(InstructTokenizer(), preview_path, sample_size=1)
    except ValueError as exc:
        assert "Qwen2.5-7B Base" in str(exc)
    else:
        raise AssertionError("expected tokenizer compatibility check to reject instruct eos")


def test_evaluate_restore_limits_greedy_decode_to_configured_samples(monkeypatch) -> None:
    class FakeTokenizer:
        eos_token_id = 9
        pad_token_id = 0

        def decode(self, token_ids, skip_special_tokens=True):
            return "*CC*"

    class FakeModel(torch.nn.Module):
        pass

    class FakeHead(torch.nn.Module):
        def forward(self, decoder_input_ids, encoder_hidden_states, encoder_attention_mask=None):
            logits = torch.zeros(decoder_input_ids.shape[0], decoder_input_ids.shape[1], 10)
            logits[..., 9] = 1.0
            return logits

    def fake_forward_encoder_hidden(model, batch):
        return torch.zeros(batch.input_ids_view1.shape[0], 2, 4)

    calls = {"count": 0, "batch_sizes": []}

    def fake_greedy_decode_restore(**kwargs):
        calls["count"] += 1
        calls["batch_sizes"].append(kwargs["encoder_hidden_states"].shape[0])
        return torch.tensor([[9]] * kwargs["encoder_hidden_states"].shape[0])

    monkeypatch.setattr("scripts.train_stage_b_restore_full.forward_encoder_hidden", fake_forward_encoder_hidden)
    monkeypatch.setattr("scripts.train_stage_b_restore_full.greedy_decode_restore", fake_greedy_decode_restore)

    rows = [
        {
            "record_id": f"r{i}",
            "canonical_smiles": "*CC*",
            "input_ids_view1": [1, 2],
            "attention_mask_view1": [1, 1],
            "restore_labels": [3, 9],
            "restore_label_mask": [True, True],
        }
        for i in range(5)
    ]
    loader = torch.utils.data.DataLoader(
        rows,
        batch_size=1,
        collate_fn=lambda batch_rows: collate_restore_records(batch_rows, pad_token_id=0, label_pad_token_id=0),
    )

    metrics, failed, predictions = evaluate_restore(
        model=FakeModel(),
        restore_head=FakeHead(),
        dataloader=loader,
        tokenizer=FakeTokenizer(),
        config=StageBConfig(eval_decode_samples=2),
        device=torch.device("cpu"),
    )

    assert metrics["sample_count"] == 5
    assert calls["count"] == 2
    assert sum(calls["batch_sizes"]) == 2
    assert failed == []
    assert len(predictions) == 2


def test_evaluate_restore_casts_bf16_logits_for_loss(monkeypatch) -> None:
    class FakeTokenizer:
        eos_token_id = 9
        pad_token_id = 0

        def decode(self, token_ids, skip_special_tokens=True):
            return "*CC*"

    class FakeModel(torch.nn.Module):
        pass

    class Bf16Head(torch.nn.Module):
        def forward(self, decoder_input_ids, encoder_hidden_states, encoder_attention_mask=None):
            logits = torch.zeros(decoder_input_ids.shape[0], decoder_input_ids.shape[1], 10, dtype=torch.bfloat16)
            logits[..., 9] = 1.0
            return logits

    def fake_forward_encoder_hidden(model, batch):
        return torch.zeros(batch.input_ids_view1.shape[0], 2, 4, dtype=torch.bfloat16)

    monkeypatch.setattr("scripts.train_stage_b_restore_full.forward_encoder_hidden", fake_forward_encoder_hidden)
    monkeypatch.setattr(
        "scripts.train_stage_b_restore_full.greedy_decode_restore",
        lambda **kwargs: torch.tensor([[9]] * kwargs["encoder_hidden_states"].shape[0]),
    )

    rows = [
        {
            "record_id": "r0",
            "canonical_smiles": "*CC*",
            "input_ids_view1": [1, 2],
            "attention_mask_view1": [1, 1],
            "restore_labels": [3, 9],
            "restore_label_mask": [True, True],
        }
    ]
    loader = torch.utils.data.DataLoader(
        rows,
        batch_size=1,
        collate_fn=lambda batch_rows: collate_restore_records(batch_rows, pad_token_id=0, label_pad_token_id=0),
    )

    metrics, _, predictions = evaluate_restore(
        model=FakeModel(),
        restore_head=Bf16Head(),
        dataloader=loader,
        tokenizer=FakeTokenizer(),
        config=StageBConfig(eval_decode_samples=1),
        device=torch.device("cpu"),
    )

    assert torch.isfinite(torch.tensor(metrics["loss"]))
    assert predictions[0]["record_id"] == "r0"
