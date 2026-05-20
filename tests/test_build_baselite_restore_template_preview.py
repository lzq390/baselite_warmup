from __future__ import annotations

import pytest

from scripts.build_baselite_restore_template_preview import (
    build_preview_record,
    length_stats,
    validate_input_row,
)


class FakeTokenizer:
    eos_token = "<eos>"

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        assert add_special_tokens is False
        return [ord(char) for char in text]

    def decode(self, token_ids: list[int], skip_special_tokens: bool = False) -> str:
        assert skip_special_tokens is False
        return "".join(chr(token_id) for token_id in token_ids)


def test_build_preview_record_uses_restore_only_identity_template() -> None:
    row = {
        "record_id": "ru_000001",
        "split": "train",
        "canonical_smiles": "*CC*",
        "canonical_hash": "canonical-hash",
        "graph_hash": "graph-hash",
    }

    preview = build_preview_record(row, FakeTokenizer())

    assert preview["text_view_1_strategy"] == "identity"
    assert preview["text_view_1"] == "*CC*"
    assert preview["canonical_text_target"] == "*CC*"
    assert preview["input_text_view1"] == "<polymer_view_smiles>\n*CC*\n</polymer_view_smiles>\n"
    assert preview["target_text"] == "*CC*<eos>"
    assert "text_view_2" not in preview


def test_build_preview_record_keeps_target_out_of_input_text() -> None:
    row = {
        "record_id": "ru_000002",
        "split": "valid",
        "canonical_smiles": "N#CC*",
        "canonical_hash": "canonical-hash",
        "graph_hash": "graph-hash",
    }

    preview = build_preview_record(row, FakeTokenizer())

    assert preview["target_text"] == "N#CC*<eos>"
    assert "N#CC*<eos>" not in preview["input_text_view1"]
    assert preview["restore_labels"] == [ord(char) for char in "N#CC*<eos>"]


def test_build_preview_record_masks_match_token_lengths_and_are_all_valid() -> None:
    row = {
        "record_id": "ru_000003",
        "split": "test",
        "canonical_smiles": "*O*",
        "canonical_hash": "canonical-hash",
        "graph_hash": "graph-hash",
    }

    preview = build_preview_record(row, FakeTokenizer())

    assert len(preview["attention_mask_view1"]) == len(preview["input_ids_view1"])
    assert len(preview["restore_label_mask"]) == len(preview["restore_labels"])
    assert all(value == 1 for value in preview["attention_mask_view1"])
    assert all(value is True for value in preview["restore_label_mask"])
    assert preview["view1_token_length"] == len(preview["input_ids_view1"])
    assert preview["restore_label_length"] == len(preview["restore_labels"])


def test_length_stats_uses_stable_nearest_rank_percentiles() -> None:
    assert length_stats([10, 20, 30, 40, 50]) == {
        "count": 5,
        "min": 10,
        "p50": 30,
        "p90": 50,
        "p95": 50,
        "p99": 50,
        "max": 50,
        "mean": 30.0,
    }


def test_validate_input_row_requires_canonical_smiles() -> None:
    with pytest.raises(ValueError, match="missing canonical_smiles"):
        validate_input_row({"record_id": "ru_missing"}, "train", 1)
