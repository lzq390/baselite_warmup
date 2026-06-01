from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_baselite_restore_template_preview import (  # noqa: E402
    AUGMENTATION_FAILURES,
    DEFAULT_DATASET_DIR,
    DEFAULT_SPLITS,
    DEFAULT_TOKENIZER_DIR,
    ROBUSTNESS_EVAL_PREVIEW,
    TRAINING_PREVIEW,
    build_preview_record,
    light_denoise_smiles,
    quality_checks_for_rows,
    rdkit_random_smiles,
    rdkit_validity,
    read_jsonl,
    require_rdkit,
    rows_by_split_from_rows,
    split_length_stats,
    stable_hash_int,
    validate_input_row,
    write_jsonl,
)


DEFAULT_OUTPUT_DIR = ROOT / "data" / "baselite_smiles_aug_v2"
DEFAULT_DIRECTION_FLIP_PATH = ROOT / "data" / "baselite_smiles_aug_sources" / "training_template_preview_direction_flip.jsonl"
STAGE_B_RESTORE_AUG_V2 = "restore_aug_v2"
INPUT_LABEL_CONFLICT_AUDIT = "input_label_conflict_audit.jsonl"
DISTINCT_VIEW_AUDIT = "distinct_view_audit.jsonl"

V2_STRATEGIES = (
    "identity",
    "rdkit_random_smiles",
    "direction_flip",
    "attachment_rooted_smiles",
    "light_denoise",
)
ROBUSTNESS_V2_STRATEGIES = tuple(strategy for strategy in V2_STRATEGIES if strategy != "identity")
DIFFICULTY_BY_STRATEGY = {
    "identity": (1, "identity"),
    "rdkit_random_smiles": (2, "equivalent_random_smiles"),
    "direction_flip": (3, "direction_flip_equivalent"),
    "attachment_rooted_smiles": (4, "attachment_rooted_equivalent"),
    "light_denoise": (5, "light_denoise"),
}


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        if path.is_absolute():
            return path.name
        return path.as_posix()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_descriptor(path: Path) -> dict[str, str]:
    return {
        "path": display_path(path),
        "sha256": file_sha256(path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage B Restore v2 five-view augmented template.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--tokenizer-dir", type=Path, default=DEFAULT_TOKENIZER_DIR)
    parser.add_argument("--direction-flip-preview-path", type=Path, default=DEFAULT_DIRECTION_FLIP_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-seq-len-view", type=int, default=512)
    parser.add_argument("--max-seq-len-restore-label", type=int, default=512)
    parser.add_argument("--collision-retry-limit", type=int, default=200)
    parser.add_argument("--distinct-view-retry-limit", type=int, default=512)
    parser.add_argument("--summary", action="store_true")
    return parser.parse_args()


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


def text_view_for_row(row: dict[str, Any]) -> str:
    if "text_view_1" in row:
        return str(row["text_view_1"])
    input_text = input_view_for_row(row)
    prefix = "<polymer_view_smiles>\n"
    suffix = "\n</polymer_view_smiles>\n"
    if input_text.startswith(prefix) and input_text.endswith(suffix):
        return input_text[len(prefix) : -len(suffix)]
    return input_text


def add_v2_metadata(
    row: dict[str, Any],
    *,
    strategy: str,
    context: str,
    retry_attempt: int = 0,
) -> dict[str, Any]:
    difficulty_level, difficulty_name = DIFFICULTY_BY_STRATEGY[strategy]
    view_id_suffix = f"{context}::{strategy}"
    if retry_attempt:
        view_id_suffix += f"::retry_{retry_attempt:03d}"
    row.update(
        {
            "view_id": f"{row['record_id']}::{view_id_suffix}",
            "augmentation_policy": STAGE_B_RESTORE_AUG_V2,
            "augmentation_strategy": strategy,
            "augmentation_difficulty_level": difficulty_level,
            "augmentation_difficulty_name": difficulty_name,
            "augmentation_retry_attempt": retry_attempt,
        }
    )
    return row


def canonicalize_smiles(smiles: str, Chem: Any) -> str | None:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)


def canonical_match(text_view: str, canonical_smiles: str, Chem: Any) -> bool | None:
    view_canonical = canonicalize_smiles(text_view, Chem)
    target_canonical = canonicalize_smiles(canonical_smiles, Chem)
    if view_canonical is None or target_canonical is None:
        return None
    return view_canonical == target_canonical


def read_dataset_rows(dataset_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in DEFAULT_SPLITS:
        for line_no, row in enumerate(read_jsonl(dataset_dir / f"{split}.jsonl"), start=1):
            validate_input_row(row, split, line_no)
            if row.get("split") != split:
                raise ValueError(f"{dataset_dir / f'{split}.jsonl'}:{line_no}: split field is {row.get('split')!r}")
            rows.append(row)
    return rows


def read_direction_flip_rows(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for line_no, row in enumerate(read_jsonl(path), start=1):
        split = str(row.get("split"))
        record_id = str(row.get("record_id"))
        strategy = str(row.get("text_view_1_strategy") or row.get("augmentation_strategy"))
        if split not in DEFAULT_SPLITS:
            raise ValueError(f"{path}:{line_no}: unsupported split {split!r}")
        if strategy != "direction_flip":
            raise ValueError(f"{path}:{line_no}: expected direction_flip row, got {strategy!r}")
        key = (split, record_id)
        if key in rows_by_key:
            raise ValueError(f"{path}:{line_no}: duplicate direction_flip row for {key}")
        rows_by_key[key] = row
    return rows_by_key


def augmentation_seed_for_attempt(
    source_row: dict[str, Any],
    *,
    strategy: str,
    context: str,
    retry_attempt: int,
) -> int:
    return stable_hash_int(
        STAGE_B_RESTORE_AUG_V2,
        context,
        source_row["split"],
        source_row["record_id"],
        source_row["canonical_hash"],
        strategy,
        retry_attempt,
    ) & 0x7FFFFFFF


def build_v2_row_from_text(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    strategy: str,
    text_view: str,
    validity: dict[str, Any],
    context: str,
    retry_attempt: int,
    Chem: Any,
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
    add_v2_metadata(preview, strategy=strategy, context=context, retry_attempt=retry_attempt)
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


def equivalent_validity(text_view: str, canonical_smiles: str, Chem: Any) -> dict[str, Any]:
    validity = rdkit_validity(text_view, Chem)
    validity["canonical_match"] = canonical_match(text_view, canonical_smiles, Chem)
    return validity


def bracket_attachment_variants(smiles: str) -> list[str]:
    star_positions = [index for index, char in enumerate(smiles) if char == "*"]
    variants: list[str] = []
    for position in star_positions:
        variant = smiles[:position] + "[*]" + smiles[position + 1 :]
        if variant != smiles and variant not in variants:
            variants.append(variant)
    if len(star_positions) >= 2:
        chars: list[str] = []
        star_set = set(star_positions)
        for index, char in enumerate(smiles):
            chars.append("[*]" if index in star_set else char)
        variant = "".join(chars)
        if variant != smiles and variant not in variants:
            variants.append(variant)
    return variants


def equivalent_surface_variants(text_view: str, canonical_smiles: str, Chem: Any) -> list[tuple[str, dict[str, Any]]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for variant in bracket_attachment_variants(text_view):
        validity = equivalent_validity(variant, canonical_smiles, Chem)
        if (
            validity.get("rdkit_valid") is True
            and validity.get("two_attachment_valid") is True
            and validity.get("canonical_match") is True
        ):
            validity["surface_variant"] = "bracket_attachment"
            validity["surface_variant_of"] = text_view
            candidates.append((variant, validity))
    return candidates


def make_identity_row(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    context: str,
    Chem: Any,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    canonical_smiles = str(source_row["canonical_smiles"])
    return build_v2_row_from_text(
        source_row,
        tokenizer,
        strategy="identity",
        text_view=canonical_smiles,
        validity=equivalent_validity(canonical_smiles, canonical_smiles, Chem),
        context=context,
        retry_attempt=0,
        Chem=Chem,
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
    return build_v2_row_from_text(
        source_row,
        tokenizer,
        strategy="rdkit_random_smiles",
        text_view=text_view,
        validity=validity,
        context=context,
        retry_attempt=retry_attempt,
        Chem=Chem,
        max_seq_len_view=max_seq_len_view,
    )


def attachment_rooted_text_candidates(canonical_smiles: str, Chem: Any) -> list[tuple[str, dict[str, Any]]]:
    mol = Chem.MolFromSmiles(canonical_smiles)
    if mol is None:
        return []
    candidates: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    atom_indices = sorted(
        [atom.GetIdx() for atom in mol.GetAtoms()],
        key=lambda atom_idx: (0 if mol.GetAtomWithIdx(atom_idx).GetSymbol() == "*" else 1, atom_idx),
    )
    for atom_idx in atom_indices:
        try:
            text_view = Chem.MolToSmiles(
                mol,
                canonical=False,
                rootedAtAtom=atom_idx,
                isomericSmiles=True,
            )
        except Exception:
            continue
        if text_view in seen:
            continue
        seen.add(text_view)
        validity = equivalent_validity(text_view, canonical_smiles, Chem)
        validity["rooted_atom_id"] = atom_idx
        if (
            validity.get("rdkit_valid") is True
            and validity.get("two_attachment_valid") is True
            and validity.get("canonical_match") is True
        ):
            candidates.append((text_view, validity))
    return candidates


def make_attachment_rooted_row(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    text_view: str,
    validity: dict[str, Any],
    context: str,
    retry_attempt: int,
    Chem: Any,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    return build_v2_row_from_text(
        source_row,
        tokenizer,
        strategy="attachment_rooted_smiles",
        text_view=text_view,
        validity=validity,
        context=context,
        retry_attempt=retry_attempt,
        Chem=Chem,
        max_seq_len_view=max_seq_len_view,
    )


def make_light_denoise_row(
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
    return build_v2_row_from_text(
        source_row,
        tokenizer,
        strategy="light_denoise",
        text_view=text_view,
        validity=validity,
        context=context,
        retry_attempt=retry_attempt,
        Chem=Chem,
        max_seq_len_view=max_seq_len_view,
    )


def make_direction_flip_row(
    source_row: dict[str, Any],
    direction_row: dict[str, Any],
    tokenizer: Any,
    *,
    direction_flip_source: dict[str, str],
    Chem: Any,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    canonical_smiles = str(source_row["canonical_smiles"])
    direction_target = str(direction_row.get("canonical_text_target") or direction_row.get("canonical_smiles"))
    if direction_target != canonical_smiles:
        return None, {
            "record_id": source_row["record_id"],
            "split": source_row["split"],
            "strategy": "direction_flip",
            "reason": "direction_flip_target_mismatch",
            "canonical_smiles": canonical_smiles,
            "direction_target": direction_target,
        }

    text_view = str(direction_row["text_view_1"])
    validity = rdkit_validity(text_view, Chem)
    validity.update(
        {
            "canonical_match": canonical_match(text_view, canonical_smiles, Chem),
            "source_preview_path": direction_flip_source["path"],
            "source_preview_sha256": direction_flip_source["sha256"],
            "source_text_view_1_strategy": direction_row.get("text_view_1_strategy"),
        }
    )
    if not validity.get("rdkit_valid") or not validity.get("two_attachment_valid"):
        return None, {
            "record_id": source_row["record_id"],
            "split": source_row["split"],
            "strategy": "direction_flip",
            "reason": "direction_flip_invalid_or_attachment_count_not_two",
            "validity": validity,
            "text_view_1": text_view,
        }
    if validity.get("canonical_match") is not True:
        return None, {
            "record_id": source_row["record_id"],
            "split": source_row["split"],
            "strategy": "direction_flip",
            "reason": "direction_flip_not_canonical_equivalent",
            "validity": validity,
            "text_view_1": text_view,
        }

    seed = stable_hash_int(
        STAGE_B_RESTORE_AUG_V2,
        source_row["split"],
        source_row["record_id"],
        source_row["canonical_hash"],
        "direction_flip",
    ) & 0x7FFFFFFF
    preview = build_preview_record(
        source_row,
        tokenizer,
        text_view_1=text_view,
        text_view_1_strategy="direction_flip",
        include_aug_metadata=True,
        view_id=f"{source_row['record_id']}::stage_b_restore_v2::direction_flip",
        augmentation_strategy="direction_flip",
        augmentation_seed=seed,
        augmentation_validity=validity,
    )
    add_v2_metadata(preview, strategy="direction_flip", context="stage_b_restore_v2")
    if preview["view1_token_length"] > max_seq_len_view:
        return None, {
            "record_id": source_row["record_id"],
            "split": source_row["split"],
            "strategy": "direction_flip",
            "reason": "view_length_overflow",
            "view1_token_length": preview["view1_token_length"],
            "max_seq_len_view": max_seq_len_view,
        }
    return preview, None


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


def row_with_surface_variant(
    source_row: dict[str, Any],
    tokenizer: Any,
    row: dict[str, Any],
    *,
    context: str,
    retry_attempt: int,
    Chem: Any,
    max_seq_len_view: int,
) -> list[dict[str, Any]]:
    strategy = strategy_for_row(row)
    variants: list[dict[str, Any]] = []
    for text_view, validity in equivalent_surface_variants(
        text_view_for_row(row),
        str(source_row["canonical_smiles"]),
        Chem,
    ):
        preview, failure = build_v2_row_from_text(
            source_row,
            tokenizer,
            strategy=strategy,
            text_view=text_view,
            validity=validity,
            context=context,
            retry_attempt=retry_attempt,
            Chem=Chem,
            max_seq_len_view=max_seq_len_view,
        )
        if preview is not None and failure is None:
            preview["distinct_surface_variant"] = True
            variants.append(preview)
    return variants


def select_row_distinct_from_seen(
    candidates: list[dict[str, Any]],
    *,
    seen_text_views: set[str],
) -> dict[str, Any] | None:
    for row in candidates:
        if text_view_for_row(row) not in seen_text_views:
            return row
    return None


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
                audit = {
                    "record_id": source_row["record_id"],
                    "split": source_row["split"],
                    "strategy": "rdkit_random_smiles",
                    "selected_retry_attempt": attempt,
                    "duplicate_attempt_count": duplicate_attempts,
                    "distinct_surface_variant": False,
                    "text_view_1": text_view_for_row(row),
                }
            return row, None, audit
        for variant in row_with_surface_variant(
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
            return selected, None, {
                "record_id": source_row["record_id"],
                "split": source_row["split"],
                "strategy": "rdkit_random_smiles",
                "selected_retry_attempt": attempt,
                "duplicate_attempt_count": duplicate_attempts,
                "distinct_surface_variant": True,
                "text_view_1": text_view_for_row(selected),
            }
    return None, last_failure or failure_for_distinct_view(
        source_row,
        strategy="rdkit_random_smiles",
        reason="distinct_view_retry_limit_exceeded",
        seen_text_views=seen_text_views,
        retry_limit=retry_limit,
    ), None


def select_attachment_rooted_distinct_row(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    seen_text_views: set[str],
    context: str,
    retry_limit: int,
    Chem: Any,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    duplicate_attempts = 0
    surface_candidates: list[tuple[int, dict[str, Any]]] = []
    for attempt, (text_view, validity) in enumerate(attachment_rooted_text_candidates(str(source_row["canonical_smiles"]), Chem)):
        if attempt > retry_limit:
            break
        row, failure = make_attachment_rooted_row(
            source_row,
            tokenizer,
            text_view=text_view,
            validity=validity,
            context=context,
            retry_attempt=attempt,
            Chem=Chem,
            max_seq_len_view=max_seq_len_view,
        )
        if row is None:
            continue
        if text_view_for_row(row) not in seen_text_views:
            audit = None
            if attempt:
                audit = {
                    "record_id": source_row["record_id"],
                    "split": source_row["split"],
                    "strategy": "attachment_rooted_smiles",
                    "selected_retry_attempt": attempt,
                    "duplicate_attempt_count": duplicate_attempts,
                    "distinct_surface_variant": False,
                    "text_view_1": text_view_for_row(row),
                }
            return row, None, audit
        for variant in row_with_surface_variant(
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
            return selected, None, {
                "record_id": source_row["record_id"],
                "split": source_row["split"],
                "strategy": "attachment_rooted_smiles",
                "selected_retry_attempt": attempt,
                "duplicate_attempt_count": duplicate_attempts,
                "distinct_surface_variant": True,
                "text_view_1": text_view_for_row(selected),
            }
    return None, failure_for_distinct_view(
        source_row,
        strategy="attachment_rooted_smiles",
        reason="distinct_view_retry_limit_exceeded",
        seen_text_views=seen_text_views,
        retry_limit=retry_limit,
    ), None


def select_light_denoise_distinct_row(
    source_row: dict[str, Any],
    tokenizer: Any,
    *,
    seen_text_views: set[str],
    context: str,
    start_retry_attempt: int,
    retry_limit: int,
    Chem: Any,
    max_seq_len_view: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    last_failure: dict[str, Any] | None = None
    duplicate_attempts = 0
    for attempt in range(start_retry_attempt, retry_limit + 1):
        row, failure = make_light_denoise_row(
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
            if attempt or duplicate_attempts:
                audit = {
                    "record_id": source_row["record_id"],
                    "split": source_row["split"],
                    "strategy": "light_denoise",
                    "selected_retry_attempt": attempt,
                    "duplicate_attempt_count": duplicate_attempts,
                    "distinct_surface_variant": False,
                    "text_view_1": text_view_for_row(row),
                }
            return row, None, audit
        duplicate_attempts += 1
    return None, last_failure or failure_for_distinct_view(
        source_row,
        strategy="light_denoise",
        reason="distinct_view_retry_limit_exceeded",
        seen_text_views=seen_text_views,
        retry_limit=retry_limit,
    ), None


def build_distinct_record_rows(
    source_row: dict[str, Any],
    direction_row: dict[str, Any],
    tokenizer: Any,
    *,
    direction_flip_source: dict[str, str],
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

    direction_row_preview, failure = make_direction_flip_row(
        source_row,
        direction_row,
        tokenizer,
        direction_flip_source=direction_flip_source,
        Chem=Chem,
        max_seq_len_view=max_seq_len_view,
    )
    if direction_row_preview is None:
        failures.append(failure or {"record_id": source_row.get("record_id"), "reason": "direction_flip_failed"})
    else:
        if text_view_for_row(direction_row_preview) in seen_text_views:
            direction_candidates = row_with_surface_variant(
                source_row,
                tokenizer,
                direction_row_preview,
                context=context,
                retry_attempt=0,
                Chem=Chem,
                max_seq_len_view=max_seq_len_view,
            )
            selected_direction = select_row_distinct_from_seen(direction_candidates, seen_text_views=seen_text_views)
            if selected_direction is None:
                failures.append(
                    failure_for_distinct_view(
                        source_row,
                        strategy="direction_flip",
                        reason="direction_flip_duplicates_existing_view",
                        seen_text_views=seen_text_views,
                        retry_limit=retry_limit,
                    )
                )
            else:
                selected_direction["distinct_surface_variant"] = True
                direction_row_preview = selected_direction
                audit_rows.append(
                    {
                        "record_id": source_row["record_id"],
                        "split": source_row["split"],
                        "strategy": "direction_flip",
                        "selected_retry_attempt": 0,
                        "duplicate_attempt_count": 1,
                        "distinct_surface_variant": True,
                        "text_view_1": text_view_for_row(direction_row_preview),
                    }
                )
        if not failures:
            rows_by_strategy["direction_flip"] = direction_row_preview
            seen_text_views.add(text_view_for_row(direction_row_preview))

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

    attachment_row, failure, audit = select_attachment_rooted_distinct_row(
        source_row,
        tokenizer,
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
        context=context,
        start_retry_attempt=0,
        retry_limit=retry_limit,
        Chem=Chem,
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
    return [rows_by_strategy[strategy] for strategy in V2_STRATEGIES], failures, audit_rows


def conflict_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[input_view_for_row(row)].append(index)

    conflicts: list[dict[str, Any]] = []
    for input_view, indices in grouped.items():
        labels = {label_for_row(rows[index]) for index in indices}
        if len(labels) <= 1:
            continue
        conflicts.append(
            {
                "input_text_view1": input_view,
                "label_count": len(labels),
                "row_count": len(indices),
                "labels": sorted(labels),
                "row_indices": indices,
            }
        )
    return conflicts


def conflict_audit_row(group: dict[str, Any], rows: list[dict[str, Any]], *, resolution: str) -> dict[str, Any]:
    return {
        "input_text_view1": group["input_text_view1"],
        "label_count": group["label_count"],
        "row_count": group["row_count"],
        "labels": group["labels"],
        "resolution": resolution,
        "rows": [
            {
                "record_id": rows[index].get("record_id"),
                "split": rows[index].get("split"),
                "view_id": rows[index].get("view_id"),
                "augmentation_strategy": strategy_for_row(rows[index]),
                "augmentation_retry_attempt": rows[index].get("augmentation_retry_attempt", 0),
                "text_view_1": text_view_for_row(rows[index]),
                "canonical_text_target": label_for_row(rows[index]),
            }
            for index in group["row_indices"]
        ],
    }


def resolve_input_label_conflicts(
    rows: list[dict[str, Any]],
    *,
    source_rows_by_key: dict[tuple[str, str], dict[str, Any]],
    tokenizer: Any,
    Chem: Any,
    max_seq_len_view: int,
    retry_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    retry_attempts: dict[tuple[str, str, str], int] = defaultdict(int)
    audit_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    initial_conflict_count = len(conflict_groups(rows))
    retried_row_keys: set[tuple[str, str, str]] = set()

    while True:
        groups = conflict_groups(rows)
        if not groups:
            break

        changed = False
        for group in groups:
            candidate_indices = [
                index
                for index in group["row_indices"]
                if strategy_for_row(rows[index]) == "light_denoise"
                and text_view_for_row(rows[index]) != label_for_row(rows[index])
            ]
            if not candidate_indices:
                audit_rows.append(conflict_audit_row(group, rows, resolution="unresolved_no_light_denoise_candidate"))
                raise ValueError(
                    "input-label conflict cannot be resolved by light_denoise retry: "
                    f"{json.dumps(audit_rows[-1], ensure_ascii=False, sort_keys=True)}"
                )

            audit_rows.append(conflict_audit_row(group, rows, resolution="retry_light_denoise"))
            for index in candidate_indices:
                key = (str(rows[index]["split"]), str(rows[index]["record_id"]), "light_denoise")
                start_retry_attempt = retry_attempts[key] + 1
                if start_retry_attempt > retry_limit:
                    failures.append(
                        {
                            "record_id": rows[index]["record_id"],
                            "split": rows[index]["split"],
                            "strategy": "light_denoise",
                            "reason": "collision_retry_limit_exceeded",
                            "retry_limit": retry_limit,
                        }
                    )
                    continue
                source_row = source_rows_by_key[(str(rows[index]["split"]), str(rows[index]["record_id"]))]
                seen_text_views = {
                    text_view_for_row(other_row)
                    for other_index, other_row in enumerate(rows)
                    if other_index != index
                    and str(other_row["split"]) == str(rows[index]["split"])
                    and str(other_row["record_id"]) == str(rows[index]["record_id"])
                }
                preview, failure, _audit = select_light_denoise_distinct_row(
                    source_row,
                    tokenizer,
                    seen_text_views=seen_text_views,
                    context="stage_b_restore_v2",
                    start_retry_attempt=start_retry_attempt,
                    retry_limit=retry_limit,
                    Chem=Chem,
                    max_seq_len_view=max_seq_len_view,
                )
                if preview is None:
                    failures.append(failure or {"record_id": rows[index].get("record_id"), "reason": "retry_failed"})
                    continue
                rows[index] = preview
                retry_attempts[key] = int(preview.get("augmentation_retry_attempt", start_retry_attempt))
                retried_row_keys.add(key)
                changed = True

        if failures:
            break
        if not changed:
            raise ValueError("input-label conflict resolution made no progress")

    final_conflicts = conflict_groups(rows)
    stats = {
        "input_label_collision_policy": "retry_non_self_light_denoise_until_unambiguous",
        "input_label_conflict_initial_count": initial_conflict_count,
        "input_label_conflict_final_count": len(final_conflicts),
        "input_label_conflict_audit_row_count": len(audit_rows),
        "input_label_collision_retried_row_count": len(retried_row_keys),
        "input_label_collision_retry_total_attempts": sum(retry_attempts.values()),
        "input_label_collision_retry_max_attempt": max(retry_attempts.values(), default=0),
    }
    return rows, stats, audit_rows, failures


def build_stage_b_restore_v2_rows(
    *,
    dataset_dir: Path,
    tokenizer: Any,
    direction_flip_preview_path: Path,
    max_seq_len_view: int,
    retry_limit: int,
    distinct_retry_limit: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    Chem = require_rdkit()
    dataset_rows = read_dataset_rows(dataset_dir)
    source_rows_by_key = {(str(row["split"]), str(row["record_id"])): row for row in dataset_rows}
    direction_rows_by_key = read_direction_flip_rows(direction_flip_preview_path)
    direction_flip_source = source_descriptor(direction_flip_preview_path)
    missing_direction = sorted(set(source_rows_by_key) - set(direction_rows_by_key))
    extra_direction = sorted(set(direction_rows_by_key) - set(source_rows_by_key))
    if missing_direction or extra_direction:
        raise ValueError(
            "direction_flip preview must match dataset split/record ids exactly; "
            f"missing={missing_direction[:10]}, extra={extra_direction[:10]}"
        )

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    distinct_audit_rows: list[dict[str, Any]] = []
    for source_row in dataset_rows:
        record_rows, record_failures, record_audit_rows = build_distinct_record_rows(
            source_row,
            direction_rows_by_key[(str(source_row["split"]), str(source_row["record_id"]))],
            tokenizer,
            direction_flip_source=direction_flip_source,
            context="stage_b_restore_v2",
            retry_limit=distinct_retry_limit,
            Chem=Chem,
            max_seq_len_view=max_seq_len_view,
        )
        rows.extend(record_rows)
        failures.extend(record_failures)
        distinct_audit_rows.extend(record_audit_rows)

    rows, collision_stats, audit_rows, retry_failures = resolve_input_label_conflicts(
        rows,
        source_rows_by_key=source_rows_by_key,
        tokenizer=tokenizer,
        Chem=Chem,
        max_seq_len_view=max_seq_len_view,
        retry_limit=retry_limit,
    )
    failures.extend(retry_failures)
    robustness_rows = [
        row
        for row in rows
        if row["split"] in {"valid", "test"} and strategy_for_row(row) in ROBUSTNESS_V2_STRATEGIES
    ]
    return rows, robustness_rows, failures, collision_stats, audit_rows, distinct_audit_rows


def strategy_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(strategy_for_row(row) for row in rows).items()))


def strategy_counts_by_split(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for split in DEFAULT_SPLITS:
        result[split] = strategy_counts([row for row in rows if row["split"] == split])
    return result


def record_duplicate_view_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows_by_record: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_record[(str(row["split"]), str(row["record_id"]))].append(row)

    duplicate_records: list[dict[str, Any]] = []
    pair_counts: Counter[tuple[str, str]] = Counter()
    unique_count_distribution: Counter[int] = Counter()
    for (split, record_id), record_rows in rows_by_record.items():
        text_by_strategy = {strategy_for_row(row): text_view_for_row(row) for row in record_rows}
        unique_count_distribution[len(set(text_by_strategy.values()))] += 1
        duplicate_pairs: list[dict[str, str]] = []
        strategies = sorted(text_by_strategy)
        for left_index, left_strategy in enumerate(strategies):
            for right_strategy in strategies[left_index + 1 :]:
                if text_by_strategy[left_strategy] != text_by_strategy[right_strategy]:
                    continue
                pair = (left_strategy, right_strategy)
                pair_counts[pair] += 1
                duplicate_pairs.append(
                    {
                        "left_strategy": left_strategy,
                        "right_strategy": right_strategy,
                        "text_view_1": text_by_strategy[left_strategy],
                    }
                )
        if duplicate_pairs:
            duplicate_records.append(
                {
                    "split": split,
                    "record_id": record_id,
                    "unique_view_count": len(set(text_by_strategy.values())),
                    "duplicate_pairs": duplicate_pairs,
                }
            )

    return {
        "record_count": len(rows_by_record),
        "record_duplicate_view_count": len(duplicate_records),
        "record_unique_view_count_distribution": dict(sorted(unique_count_distribution.items())),
        "duplicate_view_pair_counts": {
            f"{left}::{right}": count for (left, right), count in sorted(pair_counts.items())
        },
        "duplicate_view_examples": duplicate_records[:20],
    }


def distinct_generation_stats(distinct_audit_rows: list[dict[str, Any]]) -> dict[str, Any]:
    retry_counter: Counter[str] = Counter()
    surface_counter: Counter[str] = Counter()
    for row in distinct_audit_rows:
        strategy = str(row.get("strategy"))
        if int(row.get("selected_retry_attempt") or 0) > 0:
            retry_counter[strategy] += 1
        if row.get("distinct_surface_variant"):
            surface_counter[strategy] += 1
    return {
        "distinct_view_policy": "retry_seed_or_root_then_bracket_attachment_surface_variant",
        "distinct_view_audit_row_count": len(distinct_audit_rows),
        "distinct_view_retry_count_by_strategy": dict(sorted(retry_counter.items())),
        "distinct_view_surface_variant_count_by_strategy": dict(sorted(surface_counter.items())),
        "distinct_view_audit_examples": distinct_audit_rows[:20],
    }


def validity_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    validity_rows = [row.get("augmentation_validity") or {} for row in rows]
    result: dict[str, Any] = {}
    for key in ("rdkit_valid", "two_attachment_valid", "canonical_match"):
        result[key] = {
            "true": sum(1 for validity in validity_rows if validity.get(key) is True),
            "false": sum(1 for validity in validity_rows if validity.get(key) is False),
            "unknown": sum(1 for validity in validity_rows if validity.get(key) is None),
        }
    return result


def preview_summary(
    rows: list[dict[str, Any]],
    tokenizer: Any,
    *,
    max_seq_len_view: int,
    max_seq_len_restore_label: int,
) -> dict[str, Any]:
    rows_by_split = rows_by_split_from_rows(rows)
    return {
        "counts": {
            "total": len(rows),
            **{split: len(rows_by_split[split]) for split in DEFAULT_SPLITS},
        },
        "strategy_counts": strategy_counts(rows),
        "strategy_counts_by_split": strategy_counts_by_split(rows),
        "validity_counts": validity_counts(rows),
        "splits": split_length_stats(rows_by_split),
        "quality_checks": quality_checks_for_rows(
            rows,
            tokenizer,
            max_seq_len_view=max_seq_len_view,
            max_seq_len_restore_label=max_seq_len_restore_label,
        ),
    }


def build_stats(
    *,
    output_dir: Path,
    dataset_dir: Path,
    tokenizer_dir: Path,
    tokenizer: Any,
    direction_flip_preview_path: Path,
    training_rows: list[dict[str, Any]],
    robustness_rows: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    collision_stats: dict[str, Any],
    audit_rows: list[dict[str, Any]],
    distinct_audit_rows: list[dict[str, Any]],
    max_seq_len_view: int,
    max_seq_len_restore_label: int,
) -> dict[str, Any]:
    direction_flip_source = source_descriptor(direction_flip_preview_path)
    return {
        "stage": "stage_b_restore_aug_v2_template_preview",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_dir": display_path(dataset_dir),
        "direction_flip_preview_path": direction_flip_source["path"],
        "direction_flip_preview_sha256": direction_flip_source["sha256"],
        "output_dir": display_path(output_dir),
        "input_files": {
            **{split: display_path(dataset_dir / f"{split}.jsonl") for split in DEFAULT_SPLITS},
            "direction_flip_preview_jsonl": direction_flip_source["path"],
        },
        "outputs": {
            "training_preview_jsonl": display_path(output_dir / TRAINING_PREVIEW),
            "robustness_eval_preview_jsonl": display_path(output_dir / ROBUSTNESS_EVAL_PREVIEW),
            "augmentation_failures_jsonl": display_path(output_dir / AUGMENTATION_FAILURES),
            "input_label_conflict_audit_jsonl": display_path(output_dir / INPUT_LABEL_CONFLICT_AUDIT),
            "distinct_view_audit_jsonl": display_path(output_dir / DISTINCT_VIEW_AUDIT),
            "stats_json": display_path(output_dir / "training_template_stats.json"),
            "report_md": display_path(output_dir / "training_template_report.md"),
        },
        "template": {
            "task": "stage_b_restore_only_augmented_v2",
            "augmentation_policy": STAGE_B_RESTORE_AUG_V2,
            "stage_b_views_per_record": len(V2_STRATEGIES),
            "stage_b_strategies": list(V2_STRATEGIES),
            "robustness_eval_strategies": list(ROBUSTNESS_V2_STRATEGIES),
            "difficulty_by_strategy": {
                strategy: {"level": level, "name": name}
                for strategy, (level, name) in DIFFICULTY_BY_STRATEGY.items()
            },
            "input_text_view1": "<polymer_view_smiles>\\n{text_view_1}\\n</polymer_view_smiles>\\n",
            "target_text": "canonical_text_target + tokenizer.eos_token",
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
            "training": preview_summary(
                training_rows,
                tokenizer,
                max_seq_len_view=max_seq_len_view,
                max_seq_len_restore_label=max_seq_len_restore_label,
            ),
            "robustness_eval": preview_summary(
                robustness_rows,
                tokenizer,
                max_seq_len_view=max_seq_len_view,
                max_seq_len_restore_label=max_seq_len_restore_label,
            ),
        },
        "input_label_conflicts": {
            **collision_stats,
            "audit_examples": audit_rows[:10],
        },
        "distinct_views": {
            **distinct_generation_stats(distinct_audit_rows),
            **record_duplicate_view_stats(training_rows),
        },
        "augmentation_failures": {
            "count": len(failures),
            "examples": failures[:20],
        },
    }


def assert_quality(stats: dict[str, Any]) -> None:
    failed: dict[str, Any] = {}
    for preview_name, preview in stats["previews"].items():
        quality = preview["quality_checks"]
        for key in (
            "view_roundtrip_failure_count",
            "restore_roundtrip_failure_count",
            "view_length_overflow_count",
            "restore_label_length_overflow_count",
            "mask_failure_count",
        ):
            if quality[key]:
                failed[f"{preview_name}.{key}"] = quality[key]
    if stats["augmentation_failures"]["count"]:
        failed["augmentation_failures"] = stats["augmentation_failures"]["count"]
    if stats["input_label_conflicts"]["input_label_conflict_final_count"]:
        failed["input_label_conflict_final_count"] = stats["input_label_conflicts"][
            "input_label_conflict_final_count"
        ]
    if stats["distinct_views"]["record_duplicate_view_count"]:
        failed["record_duplicate_view_count"] = stats["distinct_views"]["record_duplicate_view_count"]
    if failed:
        raise SystemExit(f"Stage B restore v2 validation failed: {json.dumps(failed, sort_keys=True)}")


def write_report(path: Path, stats: dict[str, Any]) -> None:
    lines = [
        "# BaseLite Stage B Restore v2 五层增强模板报告",
        "",
        f"- 生成时间 UTC: `{stats['generated_at_utc']}`",
        f"- augmentation policy: `{stats['template']['augmentation_policy']}`",
        f"- tokenizer: `{stats['tokenizer']['path']}`",
        f"- direction_flip source: `{stats['direction_flip_preview_path']}`",
        f"- direction_flip sha256: `{stats['direction_flip_preview_sha256']}`",
        "",
        "## 五层干扰强度",
        "",
        "| level | strategy | meaning |",
        "|---:|---|---|",
    ]
    for strategy in V2_STRATEGIES:
        level, name = DIFFICULTY_BY_STRATEGY[strategy]
        lines.append(f"| {level} | `{strategy}` | `{name}` |")

    lines.extend(["", "## 输出文件", ""])
    for key, value in stats["outputs"].items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(["", "## 预览统计", ""])
    for preview_name, preview in stats["previews"].items():
        lines.extend(
            [
                f"### {preview_name}",
                "",
                f"- total: `{preview['counts']['total']}`",
                f"- train/valid/test: `{preview['counts']['train']}` / `{preview['counts']['valid']}` / `{preview['counts']['test']}`",
                f"- strategy counts: `{preview['strategy_counts']}`",
                f"- validity counts: `{preview['validity_counts']}`",
                "",
                "| split | count | identity | random | direction | attachment | denoise | view p50 | view p95 | view max | restore p50 | restore p95 | restore max |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for split in DEFAULT_SPLITS:
            split_counts = preview["strategy_counts_by_split"][split]
            split_stats = preview["splits"][split]
            view = split_stats["view1_token_length"]
            restore = split_stats["restore_label_length"]
            lines.append(
                f"| {split} | {split_stats['count']} | "
                f"{split_counts.get('identity', 0)} | "
                f"{split_counts.get('rdkit_random_smiles', 0)} | "
                f"{split_counts.get('direction_flip', 0)} | "
                f"{split_counts.get('attachment_rooted_smiles', 0)} | "
                f"{split_counts.get('light_denoise', 0)} | "
                f"{view['p50']} | {view['p95']} | {view['max']} | "
                f"{restore['p50']} | {restore['p95']} | {restore['max']} |"
            )
        quality = preview["quality_checks"]
        lines.extend(
            [
                "",
                f"- view round-trip failures: `{quality['view_roundtrip_failure_count']}`",
                f"- restore round-trip failures: `{quality['restore_roundtrip_failure_count']}`",
                f"- view length overflow: `{quality['view_length_overflow_count']}`",
                f"- restore label length overflow: `{quality['restore_label_length_overflow_count']}`",
                f"- mask failures: `{quality['mask_failure_count']}`",
                "",
            ]
        )

    conflicts = stats["input_label_conflicts"]
    distinct = stats["distinct_views"]
    lines.extend(
        [
            "## Input -> Label 冲突处理",
            "",
            f"- policy: `{conflicts['input_label_collision_policy']}`",
            f"- initial conflict groups: `{conflicts['input_label_conflict_initial_count']}`",
            f"- final conflict groups: `{conflicts['input_label_conflict_final_count']}`",
            f"- retried rows: `{conflicts['input_label_collision_retried_row_count']}`",
            f"- retry total attempts: `{conflicts['input_label_collision_retry_total_attempts']}`",
            f"- retry max attempt: `{conflicts['input_label_collision_retry_max_attempt']}`",
            "",
            "## 同 Record View 去重",
            "",
            f"- policy: `{distinct['distinct_view_policy']}`",
            f"- duplicate record count: `{distinct['record_duplicate_view_count']}`",
            f"- unique view count distribution: `{distinct['record_unique_view_count_distribution']}`",
            f"- retry count by strategy: `{distinct['distinct_view_retry_count_by_strategy']}`",
            f"- surface variant count by strategy: `{distinct['distinct_view_surface_variant_count_by_strategy']}`",
            f"- duplicate pair counts: `{distinct['duplicate_view_pair_counts']}`",
            "",
            "## 增强失败记录",
            "",
            f"- count: `{stats['augmentation_failures']['count']}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    from transformers import AutoTokenizer

    args = parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_dir, local_files_only=True, use_fast=True)
    if not tokenizer.eos_token:
        raise ValueError("tokenizer must define eos_token")

    training_rows, robustness_rows, failures, collision_stats, audit_rows, distinct_audit_rows = build_stage_b_restore_v2_rows(
        dataset_dir=args.dataset_dir,
        tokenizer=tokenizer,
        direction_flip_preview_path=args.direction_flip_preview_path,
        max_seq_len_view=args.max_seq_len_view,
        retry_limit=args.collision_retry_limit,
        distinct_retry_limit=args.distinct_view_retry_limit,
    )
    stats = build_stats(
        output_dir=args.output_dir,
        dataset_dir=args.dataset_dir,
        tokenizer_dir=args.tokenizer_dir,
        tokenizer=tokenizer,
        direction_flip_preview_path=args.direction_flip_preview_path,
        training_rows=training_rows,
        robustness_rows=robustness_rows,
        failures=failures,
        collision_stats=collision_stats,
        audit_rows=audit_rows,
        distinct_audit_rows=distinct_audit_rows,
        max_seq_len_view=args.max_seq_len_view,
        max_seq_len_restore_label=args.max_seq_len_restore_label,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / TRAINING_PREVIEW, training_rows)
    write_jsonl(args.output_dir / ROBUSTNESS_EVAL_PREVIEW, robustness_rows)
    write_jsonl(args.output_dir / AUGMENTATION_FAILURES, failures)
    write_jsonl(args.output_dir / INPUT_LABEL_CONFLICT_AUDIT, audit_rows)
    write_jsonl(args.output_dir / DISTINCT_VIEW_AUDIT, distinct_audit_rows)
    (args.output_dir / "training_template_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(args.output_dir / "training_template_report.md", stats)
    assert_quality(stats)

    if args.summary:
        summary = {
            "augmentation_policy": STAGE_B_RESTORE_AUG_V2,
            "training_counts": stats["previews"]["training"]["counts"],
            "training_strategy_counts": stats["previews"]["training"]["strategy_counts"],
            "robustness_counts": stats["previews"]["robustness_eval"]["counts"],
            "robustness_strategy_counts": stats["previews"]["robustness_eval"]["strategy_counts"],
            "input_label_conflicts": stats["input_label_conflicts"],
            "distinct_views": stats["distinct_views"],
            "augmentation_failures": stats["augmentation_failures"]["count"],
            "outputs": stats["outputs"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
