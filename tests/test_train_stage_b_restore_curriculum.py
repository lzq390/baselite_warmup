from __future__ import annotations

from collections import Counter

from scripts.train_stage_b_restore_curriculum import (
    add_robustness_aggregates,
    allocate_strategy_counts,
    build_curriculum_epoch_rows,
    count_input_label_conflicts,
    filter_train_input_label_conflicts,
    full_decode_sample_limit,
    update_early_stopping_monitor,
)
from scripts.train_stage_b_restore_full import StageBConfig


def make_curriculum_rows(per_strategy: int = 9264) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for strategy in ("identity", "rdkit_random_smiles", "direction_flip", "attachment_rooted_smiles", "light_denoise"):
        for index in range(per_strategy):
            rows.append(
                {
                    "record_id": f"{strategy}_{index:05d}",
                    "augmentation_strategy": strategy,
                }
            )
    return rows


def strategy_counts(rows: list[dict[str, str]]) -> Counter[str]:
    return Counter(row["augmentation_strategy"] for row in rows)


def make_labeled_row(record_id: str, strategy: str, text_view: str, label: str) -> dict[str, str]:
    return {
        "record_id": record_id,
        "split": "train",
        "view_id": f"{record_id}::{strategy}",
        "augmentation_strategy": strategy,
        "text_view_1_strategy": strategy,
        "text_view_1": text_view,
        "input_text_view1": f"<polymer_view_smiles>\n{text_view}\n</polymer_view_smiles>\n",
        "canonical_text_target": label,
        "canonical_smiles": label,
    }


def test_filter_train_input_label_conflicts_prefers_self_label_rows() -> None:
    rows = [
        make_labeled_row("identity_self", "identity", "*CC*", "*CC*"),
        make_labeled_row("denoise_collision", "light_denoise", "*CC*", "*CCC*"),
        make_labeled_row("clean_denoise", "light_denoise", "*CO*", "*CO*"),
    ]

    clean_rows, stats, audit_rows = filter_train_input_label_conflicts(rows)

    assert [row["record_id"] for row in clean_rows] == ["identity_self", "clean_denoise"]
    assert stats["train_conflict_filter_removed_row_count"] == 1
    assert stats["train_conflict_filter_removed_by_strategy"] == {"light_denoise": 1}
    assert stats["train_conflict_filter_remaining_conflicting_input_view_count"] == 0
    assert audit_rows[0]["kept_rows"][0]["record_id"] == "identity_self"
    assert audit_rows[0]["removed_rows"][0]["record_id"] == "denoise_collision"


def test_filter_train_input_label_conflicts_drops_pure_non_self_collisions() -> None:
    rows = [
        make_labeled_row("denoise_a", "light_denoise", "*CC*", "*CCC*"),
        make_labeled_row("denoise_b", "light_denoise", "*CC*", "*COC*"),
        make_labeled_row("identity_clean", "identity", "*NN*", "*NN*"),
    ]

    clean_rows, stats, audit_rows = filter_train_input_label_conflicts(rows)

    assert [row["record_id"] for row in clean_rows] == ["identity_clean"]
    assert stats["train_conflict_filter_removed_row_count"] == 2
    assert stats["train_conflict_filter_removed_by_strategy"] == {"light_denoise": 2}
    assert stats["train_conflict_filter_remaining_conflicting_input_view_count"] == 0
    assert audit_rows[0]["kept_rows"] == []
    assert {row["record_id"] for row in audit_rows[0]["removed_rows"]} == {"denoise_a", "denoise_b"}


def test_filter_train_input_label_conflicts_leaves_clean_rows_unchanged() -> None:
    rows = [
        make_labeled_row("identity_a", "identity", "*CC*", "*CC*"),
        make_labeled_row("denoise_b", "light_denoise", "*CO*", "*CO*"),
    ]

    clean_rows, stats, audit_rows = filter_train_input_label_conflicts(rows)

    assert clean_rows == rows
    assert audit_rows == []
    assert stats["train_conflict_filter_removed_row_count"] == 0
    assert count_input_label_conflicts(clean_rows) == 0


def test_curriculum_epoch_one_oversamples_identity_to_full_epoch_size() -> None:
    rows = make_curriculum_rows()

    epoch_rows, metadata = build_curriculum_epoch_rows(rows, epoch_index=1, seed=42)

    assert len(epoch_rows) == 46320
    assert strategy_counts(epoch_rows) == Counter({"identity": 46320})
    assert metadata["curriculum_enabled"] is True
    assert metadata["curriculum_strategy_counts"] == {
        "identity": 46320,
        "rdkit_random_smiles": 0,
        "direction_flip": 0,
        "attachment_rooted_smiles": 0,
        "light_denoise": 0,
    }


def test_curriculum_epoch_four_uses_only_identity_and_random() -> None:
    rows = make_curriculum_rows()

    epoch_rows, metadata = build_curriculum_epoch_rows(rows, epoch_index=4, seed=42)
    counts = strategy_counts(epoch_rows)

    assert len(epoch_rows) == 46320
    assert set(counts) == {"identity", "rdkit_random_smiles"}
    assert counts == Counter(allocate_strategy_counts(46320, metadata["curriculum_strategy_weights"]))


def test_curriculum_epoch_five_introduces_direction_flip() -> None:
    rows = make_curriculum_rows()

    epoch_rows, metadata = build_curriculum_epoch_rows(rows, epoch_index=5, seed=42)
    counts = strategy_counts(epoch_rows)

    assert len(epoch_rows) == 46320
    assert set(counts) == {"identity", "rdkit_random_smiles", "direction_flip"}
    assert counts == Counter(allocate_strategy_counts(46320, metadata["curriculum_strategy_weights"]))
    assert abs(counts["direction_flip"] / 46320 - 0.20) < 0.001


def test_curriculum_epoch_thirteen_contains_all_v2_strategies_with_high_denoise_share() -> None:
    rows = make_curriculum_rows()

    epoch_rows, metadata = build_curriculum_epoch_rows(rows, epoch_index=13, seed=42)
    counts = strategy_counts(epoch_rows)

    assert len(epoch_rows) == 46320
    assert set(counts) == {
        "identity",
        "rdkit_random_smiles",
        "direction_flip",
        "attachment_rooted_smiles",
        "light_denoise",
    }
    assert counts == Counter(allocate_strategy_counts(46320, metadata["curriculum_strategy_weights"]))
    assert abs(counts["light_denoise"] / 46320 - 0.25) < 0.001


def test_curriculum_sampling_is_deterministic_for_same_seed_and_epoch() -> None:
    rows = make_curriculum_rows(per_strategy=8)

    first, first_metadata = build_curriculum_epoch_rows(rows, epoch_index=8, seed=7)
    second, second_metadata = build_curriculum_epoch_rows(rows, epoch_index=8, seed=7)

    assert [row["record_id"] for row in first] == [row["record_id"] for row in second]
    assert first_metadata == second_metadata


def test_curriculum_uses_original_epoch_target_after_clean_pool_shrinks() -> None:
    rows = make_curriculum_rows(per_strategy=10)
    clean_rows = [
        row
        for row in rows
        if row["augmentation_strategy"] != "light_denoise" or row["record_id"].endswith(("00000", "00001", "00002"))
    ]

    epoch_rows, metadata = build_curriculum_epoch_rows(
        clean_rows,
        epoch_index=13,
        seed=42,
        epoch_target_row_count=len(rows),
    )
    counts = strategy_counts(epoch_rows)

    assert len(clean_rows) == 43
    assert len(epoch_rows) == 50
    assert metadata["curriculum_epoch_target_row_count"] == 50
    assert counts == Counter(allocate_strategy_counts(50, metadata["curriculum_strategy_weights"]))
    assert counts["light_denoise"] > 3


def test_identity_only_preview_keeps_old_row_count_without_curriculum() -> None:
    rows = [{"record_id": f"identity_{index}", "augmentation_strategy": "identity"} for index in range(5)]

    epoch_rows, metadata = build_curriculum_epoch_rows(rows, epoch_index=1, seed=42)

    assert len(epoch_rows) == 5
    assert set(row["record_id"] for row in epoch_rows) == {row["record_id"] for row in rows}
    assert metadata["curriculum_enabled"] is False


def test_robustness_aggregates_include_strategy_macro_and_record_success() -> None:
    predictions = [
        {
            "record_id": "r1",
            "augmentation_strategy": "rdkit_random_smiles",
            "canonical_match": True,
            "rdkit_valid": True,
            "two_attachment_valid": True,
            "exact_string_match": True,
        },
        {
            "record_id": "r1",
            "augmentation_strategy": "light_denoise",
            "canonical_match": True,
            "rdkit_valid": True,
            "two_attachment_valid": True,
            "exact_string_match": False,
        },
        {
            "record_id": "r2",
            "augmentation_strategy": "rdkit_random_smiles",
            "canonical_match": True,
            "rdkit_valid": True,
            "two_attachment_valid": True,
            "exact_string_match": True,
        },
        {
            "record_id": "r2",
            "augmentation_strategy": "light_denoise",
            "canonical_match": False,
            "rdkit_valid": False,
            "two_attachment_valid": False,
            "exact_string_match": False,
        },
        {
            "record_id": "r3",
            "augmentation_strategy": "rdkit_random_smiles",
            "canonical_match": False,
            "rdkit_valid": True,
            "two_attachment_valid": True,
            "exact_string_match": False,
        },
        {
            "record_id": "r3",
            "augmentation_strategy": "light_denoise",
            "canonical_match": False,
            "rdkit_valid": True,
            "two_attachment_valid": True,
            "exact_string_match": False,
        },
    ]

    metrics = add_robustness_aggregates({"sample_count": 6, "decoded_sample_count": 6}, predictions)

    by_strategy = metrics["robustness_by_strategy"]
    assert by_strategy["rdkit_random_smiles"]["sample_count"] == 3
    assert by_strategy["rdkit_random_smiles"]["canonical_match"] == 2 / 3
    assert by_strategy["light_denoise"]["sample_count"] == 3
    assert by_strategy["light_denoise"]["canonical_match"] == 1 / 3
    assert metrics["robustness_strategy_macro_avg"]["canonical_match"] == 0.5
    assert metrics["robustness_record_all_views_success"]["success_count"] == 1
    assert metrics["robustness_record_all_views_success"]["rate"] == 1 / 3
    assert metrics["robustness_record_any_view_success"]["success_count"] == 2
    assert metrics["robustness_record_partial_success"]["success_count"] == 1


def test_full_decode_sample_limit_uses_dataset_length() -> None:
    assert full_decode_sample_limit([object(), object(), object()]) == 3


def test_early_stopping_monitor_never_requests_stop_training() -> None:
    config = StageBConfig(
        early_stopping_enabled=True,
        early_stopping_metric="loss",
        early_stopping_mode="min",
        early_stopping_patience=2,
        early_stopping_min_epochs=1,
        early_stopping_min_delta=0.001,
    )
    state, best, checkpoint, wait = update_early_stopping_monitor(
        config=config,
        checkpoint_metrics={"loss": 1.0},
        checkpoint_name="epoch_001",
        epoch_index=1,
        best_metric=None,
        best_checkpoint=None,
        wait=0,
    )
    state, best, checkpoint, wait = update_early_stopping_monitor(
        config=config,
        checkpoint_metrics={"loss": 1.0},
        checkpoint_name="epoch_002",
        epoch_index=2,
        best_metric=best,
        best_checkpoint=checkpoint,
        wait=wait,
    )
    state, best, checkpoint, wait = update_early_stopping_monitor(
        config=config,
        checkpoint_metrics={"loss": 1.0},
        checkpoint_name="epoch_003",
        epoch_index=3,
        best_metric=best,
        best_checkpoint=checkpoint,
        wait=wait,
    )

    assert state is not None
    assert state["monitor_only"] is True
    assert state["would_stop_training"] is True
    assert state["stop_training"] is False
    assert best == 1.0
    assert checkpoint == "epoch_001"
    assert wait == 2
