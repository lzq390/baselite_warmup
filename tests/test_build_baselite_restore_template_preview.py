from __future__ import annotations

import pytest

from scripts.build_baselite_restore_template_preview import (
    augmentation_validity_counts,
    build_preview_record,
    length_stats,
    light_denoise_smiles,
    record_id_uniqueness_by_split,
    rows_by_split_from_rows,
    stage_c_strategy_for_record,
    tokenize_smiles_for_denoise,
    validate_input_row,
)


class FakeTokenizer:
    eos_token = "<eos>"
    pad_token = "<eos>"
    eos_token_id = 99
    pad_token_id = 99
    vocab_size = 256
    is_fast = False
    model_max_length = 512

    def __len__(self) -> int:
        return 256

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


def test_build_preview_record_can_add_aug_metadata_without_text_view_2() -> None:
    row = {
        "record_id": "ru_000004",
        "split": "train",
        "canonical_smiles": "*CC*",
        "canonical_hash": "canonical-hash",
        "graph_hash": "graph-hash",
    }

    preview = build_preview_record(
        row,
        FakeTokenizer(),
        text_view_1="*C<mask>C*",
        text_view_1_strategy="light_denoise",
        include_aug_metadata=True,
        view_id="ru_000004::light_denoise",
        augmentation_strategy="light_denoise",
        augmentation_seed=123,
        augmentation_validity={"two_attachment_valid": True},
    )

    assert preview["text_view_1"] == "*C<mask>C*"
    assert preview["canonical_text_target"] == "*CC*"
    assert preview["target_text"] == "*CC*<eos>"
    assert preview["augmentation_strategy"] == "light_denoise"
    assert preview["augmentation_seed"] == 123
    assert "text_view_2" not in preview
    assert "*CC*<eos>" not in preview["input_text_view1"]


def test_light_denoise_is_deterministic_and_preserves_attachment_tokens() -> None:
    first, first_validity = light_denoise_smiles("*CC(=O)NCC*", 42)
    second, second_validity = light_denoise_smiles("*CC(=O)NCC*", 42)

    assert first == second
    assert first_validity == second_validity
    assert first.count("*") == 2
    assert first_validity["two_attachment_valid"] is True


def test_tokenize_smiles_keeps_bracket_atoms_and_attachment_tokens() -> None:
    tokens = tokenize_smiles_for_denoise("*C[SiH2]C#C*")

    assert tokens[0] == "*"
    assert tokens[-1] == "*"
    assert "[SiH2]" in tokens


def test_stage_c_strategy_for_record_is_stable() -> None:
    row = {"record_id": "ru_1", "canonical_hash": "hash_1"}

    assert stage_c_strategy_for_record(row) == stage_c_strategy_for_record(row)


def test_rows_by_split_from_rows_groups_augmented_records() -> None:
    rows = [
        {"record_id": "a", "split": "train"},
        {"record_id": "b", "split": "valid"},
        {"record_id": "c", "split": "test"},
    ]
    grouped = rows_by_split_from_rows(rows)

    assert [row["record_id"] for row in grouped["train"]] == ["a"]
    assert [row["record_id"] for row in grouped["valid"]] == ["b"]
    assert [row["record_id"] for row in grouped["test"]] == ["c"]


def test_augmented_report_helpers_count_validity_and_stage_c_duplicates() -> None:
    rows = [
        {"record_id": "a", "split": "train", "augmentation_validity": {"rdkit_valid": True, "two_attachment_valid": True}},
        {"record_id": "a", "split": "train", "augmentation_validity": {"rdkit_valid": None, "two_attachment_valid": True}},
        {"record_id": "b", "split": "valid", "augmentation_validity": {"rdkit_valid": False, "two_attachment_valid": False}},
    ]

    assert augmentation_validity_counts(rows)["rdkit_valid"] == {"true": 1, "false": 1, "unknown": 1}
    grouped = rows_by_split_from_rows(rows)
    uniqueness = record_id_uniqueness_by_split(grouped)

    assert uniqueness["train"]["duplicate_record_id_count"] == 1
    assert uniqueness["valid"]["duplicate_record_id_count"] == 0
