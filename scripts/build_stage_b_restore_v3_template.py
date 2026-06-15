from __future__ import annotations

import argparse
import json
import statistics
import sys
from array import array
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_baselite_restore_template_preview import (  # noqa: E402
    AUGMENTATION_FAILURES,
    DEFAULT_TOKENIZER_DIR,
    TRAINING_PREVIEW,
    build_preview_record,
    light_denoise_smiles,
    rdkit_random_smiles,
    rdkit_validity,
)
from scripts.build_stage_b_restore_v2_template import (  # noqa: E402
    DISTINCT_VIEW_AUDIT,
    INPUT_LABEL_CONFLICT_AUDIT,
    canonical_match,
    equivalent_surface_variants,
    equivalent_validity,
    text_view_for_row,
)
from scripts.omg_v3_common import ROOT as COMMON_ROOT  # noqa: E402
from scripts.omg_v3_common import read_dataset_rows, require_rdkit, stable_hash_int  # noqa: E402


DEFAULT_DATASET_DIR = COMMON_ROOT / "data" / "baselite_smiles_v3"
DEFAULT_GRAPH_PATH = COMMON_ROOT / "data" / "processed" / "omg_repeat_unit_graphs_v3.jsonl"
DEFAULT_OUTPUT_DIR = COMMON_ROOT / "data" / "baselite_smiles_aug_v3"
STAGE_B_RESTORE_AUG_V3 = "restore_aug_v3"
V3_STRATEGIES = (
    "identity",
    "rdkit_random_smiles",
    "direction_flip",
    "attachment_rooted_smiles",
    "light_denoise",
)
DIFFICULTY_BY_STRATEGY = {
    "identity": (1, "identity"),
    "rdkit_random_smiles": (2, "equivalent_random_smiles"),
    "direction_flip": (3, "direction_flip_equivalent"),
    "attachment_rooted_smiles": (4, "attachment_rooted_equivalent"),
    "light_denoise": (5, "light_denoise"),
}


def progress_log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(COMMON_ROOT).as_posix()
    except ValueError:
        return str(path)


def strategy_for_row(row: dict[str, Any]) -> str:
    return str(row.get("augmentation_strategy") or row.get("text_view_1_strategy") or "identity")


def label_for_row(row: dict[str, Any]) -> str:
    label = str(row.get("canonical_text_target") or row.get("canonical_smiles") or row.get("target_text") or "")
    for eos_token in ("<|endoftext|>", "<eos>"):
        if label.endswith(eos_token):
            return label[: -len(eos_token)]
    return label


def input_view_for_row(row: dict[str, Any]) -> str:
    return str(row.get("input_text_view1") or "")


def augmentation_seed_for_attempt(
    source_row: dict[str, Any],
    *,
    strategy: str,
    context: str,
    retry_attempt: int,
) -> int:
    return stable_hash_int(
        STAGE_B_RESTORE_AUG_V3,
        context,
        source_row["split"],
        source_row["record_id"],
        source_row["canonical_hash"],
        strategy,
        retry_attempt,
    ) & 0x7FFFFFFF


def add_v3_metadata(
    row: dict[str, Any],
    *,
    strategy: str,
    context: str,
    retry_attempt: int = 0,
) -> dict[str, Any]:
    difficulty_level, difficulty_name = DIFFICULTY_BY_STRATEGY[strategy]
    suffix = f"{context}::{strategy}"
    if retry_attempt:
        suffix += f"::retry_{retry_attempt:03d}"
    row.update(
        {
            "view_id": f"{row['record_id']}::{suffix}",
            "augmentation_policy": STAGE_B_RESTORE_AUG_V3,
            "augmentation_strategy": strategy,
            "augmentation_difficulty_level": difficulty_level,
            "augmentation_difficulty_name": difficulty_name,
            "augmentation_retry_attempt": retry_attempt,
        }
    )
    return row


def build_v3_row_from_text(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    strategy: str,
    text_view: str,
    validity: dict[str, Any],
    context: str,
    retry_attempt: int,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    seed = augmentation_seed_for_attempt(
        source_row,
        strategy=strategy,
        context=context,
        retry_attempt=retry_attempt,
    )
    preview = build_preview_record(
        source_row,
        tokenizer,
        text_view_1=text_view,
        text_view_1_strategy=strategy,
        include_aug_metadata=True,
        view_id=f"{source_row['record_id']}::{context}::{strategy}",
        augmentation_strategy=strategy,
        augmentation_seed=seed,
        augmentation_validity=validity,
    )
    add_v3_metadata(preview, strategy=strategy, context=context, retry_attempt=retry_attempt)
    if preview["view1_token_length"] > max_seq_len_view:
        return None, {
            "record_id": source_row["record_id"],
            "split": source_row["split"],
            "canonical_hash": source_row["canonical_hash"],
            "strategy": strategy,
            "context": context,
            "reason": "view_length_overflow",
            "view1_token_length": preview["view1_token_length"],
            "max_seq_len_view": max_seq_len_view,
        }
    return preview, None


def surface_variant_rows(
    source_row: dict[str, Any],
    tokenizer: Any,
    row: dict[str, Any],
    *,
    context: str,
    retry_attempt: int,
    Chem: Any,
    max_seq_len_view: int,
) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    strategy = strategy_for_row(row)
    for text_view, validity in equivalent_surface_variants(text_view_for_row(row), str(source_row["canonical_smiles"]), Chem):
        preview, failure = build_v3_row_from_text(
            source_row,
            tokenizer,
            strategy=strategy,
            text_view=text_view,
            validity=validity,
            context=context,
            retry_attempt=retry_attempt,
            max_seq_len_view=max_seq_len_view,
        )
        if preview is not None and failure is None:
            preview["distinct_surface_variant"] = True
            variants.append(preview)
    return variants


def select_first_distinct(candidates: list[dict[str, Any]], seen_text_views: set[str]) -> dict[str, Any] | None:
    for row in candidates:
        if text_view_for_row(row) not in seen_text_views:
            return row
    return None


def make_identity_row(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    context: str,
    Chem: Any,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    canonical_smiles = str(source_row["canonical_smiles"])
    return build_v3_row_from_text(
        source_row,
        tokenizer,
        strategy="identity",
        text_view=canonical_smiles,
        validity=equivalent_validity(canonical_smiles, canonical_smiles, Chem),
        context=context,
        retry_attempt=0,
        max_seq_len_view=max_seq_len_view,
    )


def make_rdkit_random_row(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    context: str,
    retry_attempt: int,
    Chem: Any,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    seed = augmentation_seed_for_attempt(
        source_row,
        strategy="rdkit_random_smiles",
        context=context,
        retry_attempt=retry_attempt,
    )
    canonical_smiles = str(source_row["canonical_smiles"])
    text_view, validity = rdkit_random_smiles(canonical_smiles, seed, Chem)
    if text_view is None:
        return None, {
            "record_id": source_row["record_id"],
            "split": source_row["split"],
            "canonical_hash": source_row["canonical_hash"],
            "strategy": "rdkit_random_smiles",
            "context": context,
            "reason": validity.get("failure_reason", "augmentation_failed"),
        }
    validity["canonical_match"] = canonical_match(text_view, canonical_smiles, Chem)
    if (
        validity.get("rdkit_valid") is not True
        or validity.get("two_attachment_valid") is not True
        or validity.get("canonical_match") is not True
    ):
        return None, {
            "record_id": source_row["record_id"],
            "split": source_row["split"],
            "canonical_hash": source_row["canonical_hash"],
            "strategy": "rdkit_random_smiles",
            "context": context,
            "reason": "rdkit_random_invalid_or_not_canonical_equivalent",
            "validity": validity,
            "text_view_1": text_view,
        }
    return build_v3_row_from_text(
        source_row,
        tokenizer,
        strategy="rdkit_random_smiles",
        text_view=text_view,
        validity=validity,
        context=context,
        retry_attempt=retry_attempt,
        max_seq_len_view=max_seq_len_view,
    )


def rooted_text_candidates(canonical_smiles: str, Chem: Any, *, direction_first: bool) -> list[tuple[str, dict[str, Any]]]:
    mol = Chem.MolFromSmiles(canonical_smiles)
    if mol is None:
        return []
    attachment_ids = [atom.GetIdx() for atom in mol.GetAtoms() if atom.GetSymbol() == "*"]
    if len(attachment_ids) != 2:
        return []
    if direction_first:
        ordered_roots = [attachment_ids[1], attachment_ids[0]]
        for neighbor in mol.GetAtomWithIdx(attachment_ids[1]).GetNeighbors():
            ordered_roots.append(neighbor.GetIdx())
        ordered_roots.extend(reversed(range(mol.GetNumAtoms())))
    else:
        ordered_roots = sorted(
            range(mol.GetNumAtoms()),
            key=lambda atom_idx: (0 if atom_idx in attachment_ids else 1, atom_idx),
        )

    candidates: list[tuple[str, dict[str, Any]]] = []
    seen_texts: set[str] = set()
    seen_roots: set[int] = set()
    for atom_idx in ordered_roots:
        if int(atom_idx) in seen_roots:
            continue
        seen_roots.add(int(atom_idx))
        try:
            text_view = Chem.MolToSmiles(mol, canonical=False, rootedAtAtom=int(atom_idx), isomericSmiles=True)
        except Exception:
            continue
        if text_view in seen_texts:
            continue
        seen_texts.add(text_view)
        validity = rdkit_validity(text_view, Chem)
        validity["canonical_match"] = canonical_match(text_view, canonical_smiles, Chem)
        validity["rooted_atom_id"] = int(atom_idx)
        if (
            validity.get("rdkit_valid") is True
            and validity.get("two_attachment_valid") is True
            and validity.get("canonical_match") is True
        ):
            candidates.append((text_view, validity))
    return candidates


def make_rooted_row(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    strategy: str,
    text_view: str,
    validity: dict[str, Any],
    context: str,
    retry_attempt: int,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    return build_v3_row_from_text(
        source_row,
        tokenizer,
        strategy=strategy,
        text_view=text_view,
        validity=validity,
        context=context,
        retry_attempt=retry_attempt,
        max_seq_len_view=max_seq_len_view,
    )


def make_light_denoise_row(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    context: str,
    retry_attempt: int,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    seed = augmentation_seed_for_attempt(
        source_row,
        strategy="light_denoise",
        context=context,
        retry_attempt=retry_attempt,
    )
    text_view, validity = light_denoise_smiles(str(source_row["canonical_smiles"]), seed)
    validity["canonical_match"] = None
    if validity.get("two_attachment_valid") is not True:
        return None, {
            "record_id": source_row["record_id"],
            "split": source_row["split"],
            "canonical_hash": source_row["canonical_hash"],
            "strategy": "light_denoise",
            "context": context,
            "reason": "denoise_attachment_count_not_two",
            "validity": validity,
            "text_view_1": text_view,
        }
    if "<mask>" not in text_view:
        return None, {
            "record_id": source_row["record_id"],
            "split": source_row["split"],
            "canonical_hash": source_row["canonical_hash"],
            "strategy": "light_denoise",
            "context": context,
            "reason": "denoise_without_mask_rejected_for_v3_collision_safety",
            "validity": validity,
            "text_view_1": text_view,
        }
    return build_v3_row_from_text(
        source_row,
        tokenizer,
        strategy="light_denoise",
        text_view=text_view,
        validity=validity,
        context=context,
        retry_attempt=retry_attempt,
        max_seq_len_view=max_seq_len_view,
    )


def failure_for_distinct_view(
    source_row: dict[str, Any],
    *,
    strategy: str,
    reason: str,
    seen_text_views: set[str],
    retry_limit: int,
) -> dict[str, Any]:
    return {
        "record_id": source_row["record_id"],
        "split": source_row["split"],
        "canonical_hash": source_row["canonical_hash"],
        "strategy": strategy,
        "reason": reason,
        "retry_limit": retry_limit,
        "seen_text_view_count": len(seen_text_views),
        "seen_text_views": sorted(seen_text_views),
    }


def select_rdkit_random_distinct_row(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    seen_text_views: set[str],
    context: str,
    retry_limit: int,
    Chem: Any,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    last_failure: dict[str, Any] | None = None
    duplicate_attempts = 0
    surface_candidates: list[tuple[int, dict[str, Any]]] = []
    for attempt in range(retry_limit + 1):
        row, failure = make_rdkit_random_row(
            source_row,
            tokenizer,
            context=context,
            retry_attempt=attempt,
            Chem=Chem,
            max_seq_len_view=max_seq_len_view,
        )
        if row is None:
            last_failure = failure
            continue
        if text_view_for_row(row) not in seen_text_views:
            audit = None
            if attempt:
                audit = retry_audit(source_row, "rdkit_random_smiles", attempt, duplicate_attempts, row, False)
            return row, None, audit
        for variant in surface_variant_rows(
            source_row,
            tokenizer,
            row,
            context=context,
            retry_attempt=attempt,
            Chem=Chem,
            max_seq_len_view=max_seq_len_view,
        ):
            surface_candidates.append((attempt, variant))
        duplicate_attempts += 1
    for attempt, selected in surface_candidates:
        if text_view_for_row(selected) not in seen_text_views:
            return selected, None, retry_audit(source_row, "rdkit_random_smiles", attempt, duplicate_attempts, selected, True)
    return None, last_failure or failure_for_distinct_view(
        source_row,
        strategy="rdkit_random_smiles",
        reason="distinct_view_retry_limit_exceeded",
        seen_text_views=seen_text_views,
        retry_limit=retry_limit,
    ), None


def select_rooted_distinct_row(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    strategy: str,
    direction_first: bool,
    seen_text_views: set[str],
    context: str,
    retry_limit: int,
    Chem: Any,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    duplicate_attempts = 0
    surface_candidates: list[tuple[int, dict[str, Any]]] = []
    for attempt, (text_view, validity) in enumerate(
        rooted_text_candidates(str(source_row["canonical_smiles"]), Chem, direction_first=direction_first)
    ):
        if attempt > retry_limit:
            break
        row, failure = make_rooted_row(
            source_row,
            tokenizer,
            strategy=strategy,
            text_view=text_view,
            validity=validity,
            context=context,
            retry_attempt=attempt,
            max_seq_len_view=max_seq_len_view,
        )
        if row is None:
            continue
        if text_view_for_row(row) not in seen_text_views:
            audit = None
            if attempt:
                audit = retry_audit(source_row, strategy, attempt, duplicate_attempts, row, False)
            return row, None, audit
        for variant in surface_variant_rows(
            source_row,
            tokenizer,
            row,
            context=context,
            retry_attempt=attempt,
            Chem=Chem,
            max_seq_len_view=max_seq_len_view,
        ):
            surface_candidates.append((attempt, variant))
        duplicate_attempts += 1
    for attempt, selected in surface_candidates:
        if text_view_for_row(selected) not in seen_text_views:
            return selected, None, retry_audit(source_row, strategy, attempt, duplicate_attempts, selected, True)
    return None, failure_for_distinct_view(
        source_row,
        strategy=strategy,
        reason="distinct_view_retry_limit_exceeded",
        seen_text_views=seen_text_views,
        retry_limit=retry_limit,
    ), None


def select_light_denoise_distinct_row(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    seen_text_views: set[str],
    seen_input_labels: dict[str, str],
    context: str,
    start_retry_attempt: int,
    retry_limit: int,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    last_failure: dict[str, Any] | None = None
    duplicate_attempts = 0
    label = str(source_row["canonical_smiles"])
    for attempt in range(start_retry_attempt, retry_limit + 1):
        row, failure = make_light_denoise_row(
            source_row,
            tokenizer,
            context=context,
            retry_attempt=attempt,
            max_seq_len_view=max_seq_len_view,
        )
        if row is None:
            last_failure = failure
            continue
        input_view = input_view_for_row(row)
        conflicts_global = input_view in seen_input_labels and seen_input_labels[input_view] != label
        if text_view_for_row(row) not in seen_text_views and not conflicts_global:
            audit = None
            if attempt or duplicate_attempts:
                audit = retry_audit(source_row, "light_denoise", attempt, duplicate_attempts, row, False)
            return row, None, audit
        duplicate_attempts += 1
    return None, last_failure or failure_for_distinct_view(
        source_row,
        strategy="light_denoise",
        reason="distinct_or_input_label_retry_limit_exceeded",
        seen_text_views=seen_text_views,
        retry_limit=retry_limit,
    ), None


def retry_audit(
    source_row: dict[str, Any],
    strategy: str,
    selected_retry_attempt: int,
    duplicate_attempt_count: int,
    selected: dict[str, Any],
    distinct_surface_variant: bool,
) -> dict[str, Any]:
    return {
        "record_id": source_row["record_id"],
        "split": source_row["split"],
        "strategy": strategy,
        "selected_retry_attempt": selected_retry_attempt,
        "duplicate_attempt_count": duplicate_attempt_count,
        "distinct_surface_variant": distinct_surface_variant,
        "text_view_1": text_view_for_row(selected),
    }


def build_distinct_record_rows(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    seen_input_labels: dict[str, str],
    context: str,
    retry_limit: int,
    Chem: Any,
    max_seq_len_view: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows_by_strategy: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    seen_text_views: set[str] = set()

    identity_row, failure = make_identity_row(
        source_row,
        tokenizer,
        context=context,
        Chem=Chem,
        max_seq_len_view=max_seq_len_view,
    )
    if identity_row is None:
        return [], [failure or {"record_id": source_row.get("record_id"), "reason": "identity_failed"}], audit_rows
    rows_by_strategy["identity"] = identity_row
    seen_text_views.add(text_view_for_row(identity_row))

    direction_row, failure, audit = select_rooted_distinct_row(
        source_row,
        tokenizer,
        strategy="direction_flip",
        direction_first=True,
        seen_text_views=seen_text_views,
        context=context,
        retry_limit=retry_limit,
        Chem=Chem,
        max_seq_len_view=max_seq_len_view,
    )
    if direction_row is None:
        failures.append(failure or {"record_id": source_row.get("record_id"), "reason": "direction_flip_failed"})
    else:
        rows_by_strategy["direction_flip"] = direction_row
        seen_text_views.add(text_view_for_row(direction_row))
        if audit is not None:
            audit_rows.append(audit)

    random_row, failure, audit = select_rdkit_random_distinct_row(
        source_row,
        tokenizer,
        seen_text_views=seen_text_views,
        context=context,
        retry_limit=retry_limit,
        Chem=Chem,
        max_seq_len_view=max_seq_len_view,
    )
    if random_row is None:
        failures.append(failure or {"record_id": source_row.get("record_id"), "reason": "rdkit_random_failed"})
    else:
        rows_by_strategy["rdkit_random_smiles"] = random_row
        seen_text_views.add(text_view_for_row(random_row))
        if audit is not None:
            audit_rows.append(audit)

    attachment_row, failure, audit = select_rooted_distinct_row(
        source_row,
        tokenizer,
        strategy="attachment_rooted_smiles",
        direction_first=False,
        seen_text_views=seen_text_views,
        context=context,
        retry_limit=retry_limit,
        Chem=Chem,
        max_seq_len_view=max_seq_len_view,
    )
    if attachment_row is None:
        failures.append(failure or {"record_id": source_row.get("record_id"), "reason": "attachment_rooted_failed"})
    else:
        rows_by_strategy["attachment_rooted_smiles"] = attachment_row
        seen_text_views.add(text_view_for_row(attachment_row))
        if audit is not None:
            audit_rows.append(audit)

    denoise_row, failure, audit = select_light_denoise_distinct_row(
        source_row,
        tokenizer,
        seen_text_views=seen_text_views,
        seen_input_labels=seen_input_labels,
        context=context,
        start_retry_attempt=0,
        retry_limit=retry_limit,
        max_seq_len_view=max_seq_len_view,
    )
    if denoise_row is None:
        failures.append(failure or {"record_id": source_row.get("record_id"), "reason": "light_denoise_failed"})
    else:
        rows_by_strategy["light_denoise"] = denoise_row
        seen_text_views.add(text_view_for_row(denoise_row))
        if audit is not None:
            audit_rows.append(audit)

    if failures:
        return [], failures, audit_rows
    return [rows_by_strategy[strategy] for strategy in V3_STRATEGIES], failures, audit_rows


class LengthAccumulator:
    def __init__(self) -> None:
        self.values = array("I")

    def add(self, value: int) -> None:
        self.values.append(int(value))

    def summary(self) -> dict[str, Any]:
        values = sorted(self.values)
        if not values:
            return {"count": 0, "min": 0, "p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0, "mean": 0.0}

        def percentile(p: float) -> int:
            index = round((len(values) - 1) * p)
            return int(values[index])

        return {
            "count": len(values),
            "min": int(values[0]),
            "p50": percentile(0.50),
            "p90": percentile(0.90),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "max": int(values[-1]),
            "mean": round(statistics.fmean(values), 4),
        }


class TemplateStatsAccumulator:
    def __init__(self, *, max_seq_len_view: int, max_seq_len_restore_label: int) -> None:
        self.max_seq_len_view = max_seq_len_view
        self.max_seq_len_restore_label = max_seq_len_restore_label
        self.total = 0
        self.split_counts: Counter[str] = Counter()
        self.strategy_counts: Counter[str] = Counter()
        self.strategy_counts_by_split: dict[str, Counter[str]] = defaultdict(Counter)
        self.record_strategy_counts: dict[str, Counter[str]] = defaultdict(Counter)
        self.validity_counts: dict[str, Counter[str]] = {key: Counter() for key in ("rdkit_valid", "two_attachment_valid", "canonical_match")}
        self.view_lengths: dict[str, LengthAccumulator] = defaultdict(LengthAccumulator)
        self.restore_lengths: dict[str, LengthAccumulator] = defaultdict(LengthAccumulator)
        self.quality_counts: Counter[str] = Counter()
        self.quality_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_quality_example(self, key: str, row: dict[str, Any], detail: dict[str, Any]) -> None:
        examples = self.quality_examples[key]
        if len(examples) < 20:
            examples.append(
                {
                    "record_id": row.get("record_id"),
                    "split": row.get("split"),
                    "augmentation_strategy": strategy_for_row(row),
                    **detail,
                }
            )

    def validate_roundtrip(self, row: dict[str, Any], tokenizer: Any) -> None:
        if len(row["attention_mask_view1"]) != len(row["input_ids_view1"]):
            self.quality_counts["mask_failure_count"] += 1
            self.add_quality_example(row=row, key="mask_failure_examples", detail={"reason": "attention_mask_length_mismatch"})
        if len(row["restore_label_mask"]) != len(row["restore_labels"]):
            self.quality_counts["mask_failure_count"] += 1
            self.add_quality_example(row=row, key="mask_failure_examples", detail={"reason": "restore_label_mask_length_mismatch"})
        if row["view1_token_length"] > self.max_seq_len_view:
            self.quality_counts["view_length_overflow_count"] += 1
            self.add_quality_example(
                row=row,
                key="view_length_overflow_examples",
                detail={"view1_token_length": row["view1_token_length"]},
            )
        if row["restore_label_length"] > self.max_seq_len_restore_label:
            self.quality_counts["restore_label_length_overflow_count"] += 1
            self.add_quality_example(
                row=row,
                key="restore_label_length_overflow_examples",
                detail={"restore_label_length": row["restore_label_length"]},
            )
        if tokenizer.decode(row["input_ids_view1"], skip_special_tokens=False) != row["input_text_view1"]:
            self.quality_counts["view_roundtrip_failure_count"] += 1
            self.add_quality_example(row=row, key="view_roundtrip_failure_examples", detail={})
        if tokenizer.decode(row["restore_labels"], skip_special_tokens=False) != row["target_text"]:
            self.quality_counts["restore_roundtrip_failure_count"] += 1
            self.add_quality_example(row=row, key="restore_roundtrip_failure_examples", detail={})

    def add_row(self, row: dict[str, Any], tokenizer: Any) -> None:
        split = str(row["split"])
        strategy = strategy_for_row(row)
        self.total += 1
        self.split_counts[split] += 1
        self.strategy_counts[strategy] += 1
        self.strategy_counts_by_split[split][strategy] += 1
        self.record_strategy_counts[str(row["record_id"])][strategy] += 1
        validity = row.get("augmentation_validity") or {}
        for key in ("rdkit_valid", "two_attachment_valid", "canonical_match"):
            value = validity.get(key)
            bucket = "true" if value is True else "false" if value is False else "unknown"
            self.validity_counts[key][bucket] += 1
        self.view_lengths[split].add(int(row["view1_token_length"]))
        self.restore_lengths[split].add(int(row["restore_label_length"]))
        self.validate_roundtrip(row, tokenizer)

    def quality_checks(self) -> dict[str, Any]:
        return {
            "view_roundtrip_failure_count": self.quality_counts["view_roundtrip_failure_count"],
            "view_roundtrip_failure_examples": self.quality_examples["view_roundtrip_failure_examples"],
            "restore_roundtrip_failure_count": self.quality_counts["restore_roundtrip_failure_count"],
            "restore_roundtrip_failure_examples": self.quality_examples["restore_roundtrip_failure_examples"],
            "view_length_overflow_count": self.quality_counts["view_length_overflow_count"],
            "view_length_overflow_examples": self.quality_examples["view_length_overflow_examples"],
            "restore_label_length_overflow_count": self.quality_counts["restore_label_length_overflow_count"],
            "restore_label_length_overflow_examples": self.quality_examples["restore_label_length_overflow_examples"],
            "mask_failure_count": self.quality_counts["mask_failure_count"],
            "mask_failure_examples": self.quality_examples["mask_failure_examples"],
        }

    def record_strategy_quality(self) -> dict[str, Any]:
        bad_records = [
            {"record_id": record_id, "strategy_counts": dict(counts)}
            for record_id, counts in self.record_strategy_counts.items()
            if any(counts.get(strategy, 0) != 1 for strategy in V3_STRATEGIES)
        ]
        return {
            "record_count": len(self.record_strategy_counts),
            "records_with_exactly_five_strategies": len(self.record_strategy_counts) - len(bad_records),
            "bad_record_count": len(bad_records),
            "bad_record_examples": bad_records[:20],
        }

    def summary(self) -> dict[str, Any]:
        return {
            "counts": {
                "total": self.total,
                **{split: self.split_counts.get(split, 0) for split in ("train", "valid", "test")},
            },
            "strategy_counts": dict(sorted(self.strategy_counts.items())),
            "strategy_counts_by_split": {
                split: dict(sorted(self.strategy_counts_by_split[split].items())) for split in ("train", "valid", "test")
            },
            "validity_counts": {
                key: {bucket: counts.get(bucket, 0) for bucket in ("true", "false", "unknown")}
                for key, counts in self.validity_counts.items()
            },
            "splits": {
                split: {
                    "view1_token_length": self.view_lengths[split].summary(),
                    "restore_label_length": self.restore_lengths[split].summary(),
                }
                for split in ("train", "valid", "test")
            },
            "quality_checks": self.quality_checks(),
            "record_strategy_quality": self.record_strategy_quality(),
        }


def write_jsonl_row(handle: Any, row: dict[str, Any]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")


def register_input_label(
    row: dict[str, Any],
    *,
    seen_input_labels: dict[str, str],
    conflict_audit_rows: list[dict[str, Any]],
) -> bool:
    input_view = input_view_for_row(row)
    label = label_for_row(row)
    existing_label = seen_input_labels.get(input_view)
    if existing_label is None:
        seen_input_labels[input_view] = label
        return True
    if existing_label == label:
        return True
    conflict_audit_rows.append(
        {
            "input_text_view1": input_view,
            "existing_label": existing_label,
            "new_label": label,
            "resolution": "unresolved_non_light_denoise_conflict",
            "record_id": row.get("record_id"),
            "split": row.get("split"),
            "view_id": row.get("view_id"),
            "augmentation_strategy": strategy_for_row(row),
        }
    )
    return False


def build_stage_b_restore_v3_template(
    *,
    dataset_dir: Path,
    graph_path: Path,
    tokenizer_dir: Path,
    output_dir: Path,
    max_seq_len_view: int,
    max_seq_len_restore_label: int,
    distinct_retry_limit: int,
    progress_every: int | None = 100_000,
) -> dict[str, Any]:
    from transformers import AutoTokenizer

    Chem = require_rdkit()
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_dir, local_files_only=True, use_fast=True)
    if not tokenizer.eos_token:
        raise ValueError("tokenizer must define eos_token")

    dataset_rows = read_dataset_rows(dataset_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    failures: list[dict[str, Any]] = []
    distinct_audit_rows: list[dict[str, Any]] = []
    conflict_audit_rows: list[dict[str, Any]] = []
    seen_input_labels: dict[str, str] = {}
    stats = TemplateStatsAccumulator(
        max_seq_len_view=max_seq_len_view,
        max_seq_len_restore_label=max_seq_len_restore_label,
    )
    context = "stage_b_restore_v3"

    training_path = output_dir / TRAINING_PREVIEW
    with training_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record_index, source_row in enumerate(dataset_rows, start=1):
            record_rows, record_failures, record_audit = build_distinct_record_rows(
                source_row,
                tokenizer,
                seen_input_labels=seen_input_labels,
                context=context,
                retry_limit=distinct_retry_limit,
                Chem=Chem,
                max_seq_len_view=max_seq_len_view,
            )
            if record_failures:
                failures.extend(record_failures)
                continue
            distinct_audit_rows.extend(record_audit)
            for row in record_rows:
                if not register_input_label(row, seen_input_labels=seen_input_labels, conflict_audit_rows=conflict_audit_rows):
                    failures.append(
                        {
                            "record_id": row["record_id"],
                            "split": row["split"],
                            "strategy": strategy_for_row(row),
                            "reason": "input_label_conflict",
                        }
                    )
                    continue
                stats.add_row(row, tokenizer)
                write_jsonl_row(handle, row)
            if progress_every and record_index % progress_every == 0:
                progress_log(
                    "[template] "
                    f"base_records={record_index} "
                    f"template_rows={stats.total} "
                    f"failures={len(failures)} "
                    f"input_label_conflicts={len(conflict_audit_rows)}"
                )

    for filename, rows in (
        (AUGMENTATION_FAILURES, failures),
        (DISTINCT_VIEW_AUDIT, distinct_audit_rows),
        (INPUT_LABEL_CONFLICT_AUDIT, conflict_audit_rows),
    ):
        with (output_dir / filename).open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                write_jsonl_row(handle, row)

    generated_at = datetime.now(timezone.utc).isoformat()
    template_summary = stats.summary()
    expected_rows = len(dataset_rows) * len(V3_STRATEGIES)
    manifest = {
        "stage": "stage_b_restore_aug_v3_template_preview",
        "generated_at_utc": generated_at,
        "dataset_dir": display_path(dataset_dir),
        "graph_path": display_path(graph_path),
        "output_dir": display_path(output_dir),
        "input_files": {
            "dataset_dir": display_path(dataset_dir),
            "graph_jsonl": display_path(graph_path),
        },
        "outputs": {
            "training_preview_jsonl": display_path(output_dir / TRAINING_PREVIEW),
            "augmentation_failures_jsonl": display_path(output_dir / AUGMENTATION_FAILURES),
            "input_label_conflict_audit_jsonl": display_path(output_dir / INPUT_LABEL_CONFLICT_AUDIT),
            "distinct_view_audit_jsonl": display_path(output_dir / DISTINCT_VIEW_AUDIT),
            "stats_json": display_path(output_dir / "training_template_stats.json"),
            "report_md": display_path(output_dir / "training_template_report.md"),
        },
        "template": {
            "task": "stage_b_restore_only_augmented_v3",
            "augmentation_policy": STAGE_B_RESTORE_AUG_V3,
            "views_per_record": len(V3_STRATEGIES),
            "strategies": list(V3_STRATEGIES),
            "difficulty_by_strategy": {
                strategy: {"level": level, "name": name}
                for strategy, (level, name) in DIFFICULTY_BY_STRATEGY.items()
            },
            "input_text_view1": "<polymer_view_smiles>\\n{text_view_1}\\n</polymer_view_smiles>\\n",
            "target_text": "canonical_text_target + tokenizer.eos_token",
            "uses_graph_sidecar": True,
        },
        "tokenizer": {
            "path": display_path(tokenizer_dir),
            "class": type(tokenizer).__name__,
            "vocab_size": getattr(tokenizer, "vocab_size", None),
            "len": len(tokenizer),
            "is_fast": getattr(tokenizer, "is_fast", None),
            "eos_token": tokenizer.eos_token,
            "eos_token_id": tokenizer.eos_token_id,
            "pad_token": tokenizer.pad_token,
            "pad_token_id": tokenizer.pad_token_id,
            "model_max_length": tokenizer.model_max_length,
        },
        "limits": {
            "max_seq_len_view": max_seq_len_view,
            "max_seq_len_restore_label": max_seq_len_restore_label,
        },
        "previews": {
            "training": template_summary,
        },
        "expected": {
            "base_record_count": len(dataset_rows),
            "training_row_count": expected_rows,
        },
        "input_label_conflicts": {
            "input_label_conflict_final_count": len(conflict_audit_rows),
            "audit_examples": conflict_audit_rows[:20],
        },
        "distinct_views": {
            "distinct_view_policy": "retry_seed_or_root_then_bracket_attachment_surface_variant",
            "distinct_view_audit_row_count": len(distinct_audit_rows),
            "distinct_view_audit_examples": distinct_audit_rows[:20],
        },
        "augmentation_failures": {
            "count": len(failures),
            "examples": failures[:20],
        },
    }
    (output_dir / "training_template_stats.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(output_dir / "training_template_report.md", manifest)
    assert_quality(manifest)
    return manifest


def assert_quality(stats: dict[str, Any]) -> None:
    training = stats["previews"]["training"]
    quality = training["quality_checks"]
    failed: dict[str, Any] = {}
    if training["counts"]["total"] != stats["expected"]["training_row_count"]:
        failed["training_row_count"] = {
            "expected": stats["expected"]["training_row_count"],
            "actual": training["counts"]["total"],
        }
    if training["record_strategy_quality"]["bad_record_count"]:
        failed["bad_record_count"] = training["record_strategy_quality"]["bad_record_count"]
    for key in (
        "view_roundtrip_failure_count",
        "restore_roundtrip_failure_count",
        "view_length_overflow_count",
        "restore_label_length_overflow_count",
        "mask_failure_count",
    ):
        if quality[key]:
            failed[key] = quality[key]
    if stats["augmentation_failures"]["count"]:
        failed["augmentation_failures"] = stats["augmentation_failures"]["count"]
    if stats["input_label_conflicts"]["input_label_conflict_final_count"]:
        failed["input_label_conflicts"] = stats["input_label_conflicts"]["input_label_conflict_final_count"]
    if failed:
        raise SystemExit(f"Stage B restore v3 validation failed: {json.dumps(failed, sort_keys=True)}")


def write_report(path: Path, stats: dict[str, Any]) -> None:
    training = stats["previews"]["training"]
    lines = [
        "# BaseLite Stage B Restore v3 OMG Five-view Template Report",
        "",
        f"- generated_at_utc: `{stats['generated_at_utc']}`",
        f"- dataset_dir: `{stats['dataset_dir']}`",
        f"- graph_path: `{stats['graph_path']}`",
        f"- output_dir: `{stats['output_dir']}`",
        f"- augmentation_policy: `{stats['template']['augmentation_policy']}`",
        f"- base records: `{stats['expected']['base_record_count']}`",
        f"- training rows: `{training['counts']['total']}`",
        f"- expected training rows: `{stats['expected']['training_row_count']}`",
        "",
        "## Strategy Counts",
        "",
    ]
    for strategy, count in training["strategy_counts"].items():
        lines.append(f"- `{strategy}`: `{count}`")
    lines.extend(
        [
            "",
            "## Quality Checks",
            "",
            f"- augmentation failures: `{stats['augmentation_failures']['count']}`",
            f"- input-label conflicts: `{stats['input_label_conflicts']['input_label_conflict_final_count']}`",
            f"- record strategy bad count: `{training['record_strategy_quality']['bad_record_count']}`",
            f"- view roundtrip failures: `{training['quality_checks']['view_roundtrip_failure_count']}`",
            f"- restore roundtrip failures: `{training['quality_checks']['restore_roundtrip_failure_count']}`",
            f"- view length overflow: `{training['quality_checks']['view_length_overflow_count']}`",
            f"- restore label length overflow: `{training['quality_checks']['restore_label_length_overflow_count']}`",
            "",
            "## Length Summary",
            "",
        ]
    )
    for split, summary in training["splits"].items():
        lines.append(
            f"- `{split}` view p95/max: `{summary['view1_token_length']['p95']}` / `{summary['view1_token_length']['max']}`; "
            f"restore p95/max: `{summary['restore_label_length']['p95']}` / `{summary['restore_label_length']['max']}`"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage B Restore v3 OMG five-view augmented template.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--graph-path", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--tokenizer-dir", type=Path, default=DEFAULT_TOKENIZER_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-seq-len-view", type=int, default=512)
    parser.add_argument("--max-seq-len-restore-label", type=int, default=512)
    parser.add_argument("--distinct-view-retry-limit", type=int, default=512)
    parser.add_argument("--progress-every", type=int, default=100_000)
    parser.add_argument("--summary", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_stage_b_restore_v3_template(
        dataset_dir=args.dataset_dir,
        graph_path=args.graph_path,
        tokenizer_dir=args.tokenizer_dir,
        output_dir=args.output_dir,
        max_seq_len_view=args.max_seq_len_view,
        max_seq_len_restore_label=args.max_seq_len_restore_label,
        distinct_retry_limit=args.distinct_view_retry_limit,
        progress_every=args.progress_every,
    )
    if args.summary:
        print(
            json.dumps(
                {
                    "output_dir": str(args.output_dir),
                    "counts": manifest["previews"]["training"]["counts"],
                    "strategy_counts": manifest["previews"]["training"]["strategy_counts"],
                    "augmentation_failures": manifest["augmentation_failures"]["count"],
                    "quality_checks": manifest["previews"]["training"]["quality_checks"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
