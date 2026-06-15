from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from scripts.build_omg_baselite_v3_dataset import (
    allocate_reaction_quotas,
    assign_splits,
    select_records,
)
from scripts.build_omg_repeat_unit_graphs_v3 import GraphAuditAccumulator
from scripts.build_stage_b_restore_v3_template import V3_STRATEGIES, build_distinct_record_rows, strategy_for_row
from scripts.omg_v3_common import graph_row_for_record, require_rdkit, sha256_text


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


def test_allocate_reaction_quotas_matches_omg_v3_locked_full_plan() -> None:
    counts = Counter(
        {
            "3": 8404330,
            "1": 3810102,
            "2": 274432,
            "4": 195580,
            "6": 100584,
            "5": 45935,
            "8": 29565,
            "9": 9254,
            "17": 7718,
            "7": 4311,
            "12": 1280,
            "10": 876,
            "16": 744,
            "11": 737,
            "13": 454,
            "15": 186,
            "14": 43,
        }
    )

    quotas = allocate_reaction_quotas(counts, target_count=1_000_000, floor_per_reaction=1_000)

    assert quotas == {
        "1": 292765,
        "2": 21944,
        "3": 644667,
        "4": 15904,
        "5": 4442,
        "6": 8628,
        "7": 1254,
        "8": 3188,
        "9": 1632,
        "10": 876,
        "11": 737,
        "12": 1021,
        "13": 454,
        "14": 43,
        "15": 186,
        "16": 744,
        "17": 1515,
    }


def test_allocate_reaction_quotas_handles_smoke_target_below_floor_sum() -> None:
    counts = Counter({"1": 1000, "2": 1000, "3": 1000})

    quotas = allocate_reaction_quotas(counts, target_count=10, floor_per_reaction=100)

    assert sum(quotas.values()) == 10
    assert quotas == {"1": 4, "2": 3, "3": 3}


def test_select_records_excludes_current_hashes_and_assigns_leakage_free_splits(tmp_path: Path) -> None:
    pytest.importorskip("rdkit")
    Chem = require_rdkit()
    input_path = tmp_path / "omg.csv"
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["reaction_idx", "reactant_1", "reactant_2", "product"])
        writer.writeheader()
        writer.writerows(
            [
                {"reaction_idx": "1", "reactant_1": "A", "reactant_2": "B", "product": "*CC*"},
                {"reaction_idx": "1", "reactant_1": "A", "reactant_2": "B", "product": "*CO*"},
                {"reaction_idx": "2", "reactant_1": "A", "reactant_2": "B", "product": "*CN*"},
            ]
        )
    current_hashes = {sha256_text("*CC*")}

    rows, audit = select_records(
        input_path=input_path,
        quotas={"1": 1, "2": 1},
        current_hashes=current_hashes,
        sample_seed="test_seed",
        Chem=Chem,
    )
    assigned = assign_splits(rows, train_ratio=0.5, valid_ratio=0.25, split_seed_value="split_seed")

    assert len(rows) == 2
    assert {row["canonical_smiles"] for row in rows} == {"*CO*", "*CN*"}
    assert audit["counters"]["rows_skipped_current_overlap"] == 1
    assert len({row["record_id"] for row in assigned}) == 2
    assert len({row["canonical_hash"] for row in assigned}) == 2


def test_select_records_redistributes_quota_shortfall_from_replacement_pool(tmp_path: Path) -> None:
    pytest.importorskip("rdkit")
    Chem = require_rdkit()
    input_path = tmp_path / "omg.csv"
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["reaction_idx", "reactant_1", "reactant_2", "product"])
        writer.writeheader()
        writer.writerows(
            [
                {"reaction_idx": "1", "reactant_1": "A", "reactant_2": "B", "product": "*CC*"},
                {"reaction_idx": "1", "reactant_1": "A", "reactant_2": "B", "product": "*CO*"},
                {"reaction_idx": "2", "reactant_1": "A", "reactant_2": "B", "product": "*CN*"},
                {"reaction_idx": "2", "reactant_1": "A", "reactant_2": "B", "product": "*CS*"},
                {"reaction_idx": "2", "reactant_1": "A", "reactant_2": "B", "product": "*CCC*"},
                {"reaction_idx": "2", "reactant_1": "A", "reactant_2": "B", "product": "*CCO*"},
            ]
        )

    rows, audit = select_records(
        input_path=input_path,
        quotas={"1": 3, "2": 2},
        current_hashes=set(),
        sample_seed="test_seed",
        Chem=Chem,
        replacement_slack_per_reaction=4,
    )

    selected_counts = Counter(str(row["source_reaction_idx"]) for row in rows)
    assert len(rows) == 5
    assert audit["quota_shortfalls_after_filtering"] == {"1": 1}
    assert audit["replacement_count"] == 1
    assert selected_counts["1"] == 2
    assert selected_counts["2"] == 3


def test_select_records_enforces_unique_graph_hash_with_replacement_pool(tmp_path: Path) -> None:
    pytest.importorskip("rdkit")
    Chem = require_rdkit()
    input_path = tmp_path / "omg.csv"
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["reaction_idx", "reactant_1", "reactant_2", "product"])
        writer.writeheader()
        writer.writerows(
            [
                {"reaction_idx": "1", "reactant_1": "A", "reactant_2": "B", "product": "*Nc1cn[nH]c1*"},
                {"reaction_idx": "1", "reactant_1": "A", "reactant_2": "B", "product": "*Nc1c[nH]nc1*"},
                {"reaction_idx": "1", "reactant_1": "A", "reactant_2": "B", "product": "*CS*"},
                {"reaction_idx": "1", "reactant_1": "A", "reactant_2": "B", "product": "*CC*"},
            ]
        )

    rows, audit = select_records(
        input_path=input_path,
        quotas={"1": 2},
        current_hashes=set(),
        sample_seed="test_seed",
        Chem=Chem,
        replacement_slack_per_reaction=4,
    )

    assert len(rows) == 2
    assert len({row["canonical_hash"] for row in rows}) == 2
    assert len({row["graph_hash"] for row in rows}) == 2
    assert audit["graph_duplicate_drop_count"] == 1
    assert audit["graph_replacement_count"] == 1


def test_graph_row_schema_and_streaming_audit_join() -> None:
    pytest.importorskip("rdkit")
    Chem = require_rdkit()
    record = {
        "record_id": "omg_v3_0000001",
        "canonical_smiles": "*CC*",
        "canonical_hash": sha256_text("*CC*"),
    }
    graph_hash = __import__("scripts.omg_v3_common", fromlist=["graph_hash_for_smiles"]).graph_hash_for_smiles("*CC*", Chem)
    record["graph_hash"] = graph_hash
    record["split"] = "train"

    graph = graph_row_for_record(record, Chem)
    audit = GraphAuditAccumulator([record])
    audit.add_graph(graph)

    assert graph["record_id"] == record["record_id"]
    assert len(graph["attachment_atom_ids"]) == 2
    assert all(edge["is_periodic_edge"] is False for edge in graph["edges"])
    assert audit.join_quality()["missing_graph_by_record_id"] == 0
    assert audit.join_quality()["canonical_hash_mismatch_count"] == 0
    assert audit.feature_schema()["node"]["feature_dim"] > 0


def test_v3_template_builds_exactly_five_distinct_strategy_rows() -> None:
    pytest.importorskip("rdkit")
    Chem = require_rdkit()
    canonical = "*CC(=O)NCC*"
    record = {
        "record_id": "omg_v3_0000001",
        "split": "train",
        "canonical_smiles": canonical,
        "canonical_hash": sha256_text(canonical),
        "graph_hash": "graph_hash",
    }

    rows, failures, audit_rows = build_distinct_record_rows(
        record,
        FakeTokenizer(),
        seen_input_labels={},
        context="stage_b_restore_v3",
        retry_limit=64,
        Chem=Chem,
        max_seq_len_view=512,
    )

    assert failures == []
    assert [strategy_for_row(row) for row in rows] == list(V3_STRATEGIES)
    assert len({row["text_view_1"] for row in rows}) == 5
    assert all(row["augmentation_policy"] == "restore_aug_v3" for row in rows)
    assert {row["augmentation_validity"]["two_attachment_valid"] for row in rows} == {True}
    assert rows[-1]["augmentation_strategy"] == "light_denoise"
    assert "<mask>" in rows[-1]["text_view_1"]
