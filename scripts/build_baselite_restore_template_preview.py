from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = ROOT / ".codex_py_deps"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))

DEFAULT_DATASET_DIR = ROOT / "data" / "baselite_smiles_v1"
DEFAULT_AUGMENTED_OUTPUT_DIR = ROOT / "data" / "baselite_smiles_aug_v1"
DEFAULT_TOKENIZER_DIR = ROOT / "models" / "qwen2.5-7b-tokenizer"
DEFAULT_SPLITS = ("train", "valid", "test")
AUGMENTATION_POLICY_IDENTITY = "identity"
AUGMENTATION_POLICY_RESTORE_AUG_V1 = "restore_aug_v1"
TRAINING_PREVIEW = "training_template_preview.jsonl"
STAGE_C_TRAINING_PREVIEW = "stage_c_training_template_preview.jsonl"
ROBUSTNESS_EVAL_PREVIEW = "robustness_eval_preview.jsonl"
AUGMENTATION_FAILURES = "augmentation_failures.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")


def stable_hash_int(*parts: object) -> int:
    text = ":".join(str(part) for part in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def percentile(sorted_values: list[int], p: float) -> int:
    if not sorted_values:
        return 0
    index = round((len(sorted_values) - 1) * p)
    return sorted_values[index]


def length_stats(lengths: list[int]) -> dict[str, Any]:
    values = sorted(lengths)
    return {
        "count": len(values),
        "min": values[0] if values else 0,
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": values[-1] if values else 0,
        "mean": round(statistics.fmean(values), 4) if values else 0.0,
    }


def validate_input_row(row: dict[str, Any], split: str, line_no: int) -> None:
    for field in ["record_id", "canonical_smiles", "canonical_hash", "graph_hash"]:
        if field not in row or row[field] in (None, ""):
            raise ValueError(f"{split}:{line_no}: missing {field}")


def build_input_text_view1(text_view_1: str) -> str:
    return f"<polymer_view_smiles>\n{text_view_1}\n</polymer_view_smiles>\n"


def build_preview_record(
    row: dict[str, Any],
    tokenizer: Any,
    *,
    text_view_1: str | None = None,
    text_view_1_strategy: str = "identity",
    include_aug_metadata: bool = False,
    view_id: str | None = None,
    augmentation_strategy: str | None = None,
    augmentation_seed: int | None = None,
    augmentation_validity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical_smiles = str(row["canonical_smiles"])
    if text_view_1 is None:
        text_view_1 = canonical_smiles
    canonical_text_target = canonical_smiles
    input_text_view1 = build_input_text_view1(text_view_1)
    target_text = canonical_text_target + tokenizer.eos_token

    input_ids_view1 = tokenizer.encode(input_text_view1, add_special_tokens=False)
    restore_labels = tokenizer.encode(target_text, add_special_tokens=False)

    preview = {
        "record_id": str(row["record_id"]),
        "split": str(row["split"]),
        "canonical_smiles": canonical_smiles,
        "canonical_hash": str(row["canonical_hash"]),
        "graph_hash": str(row["graph_hash"]),
        "text_view_1_strategy": text_view_1_strategy,
        "text_view_1": text_view_1,
        "canonical_text_target": canonical_text_target,
        "input_text_view1": input_text_view1,
        "target_text": target_text,
        "input_ids_view1": input_ids_view1,
        "attention_mask_view1": [1] * len(input_ids_view1),
        "restore_labels": restore_labels,
        "restore_label_mask": [True] * len(restore_labels),
        "view1_token_length": len(input_ids_view1),
        "restore_label_length": len(restore_labels),
    }
    if include_aug_metadata:
        preview.update(
            {
                "view_id": view_id or f"{preview['record_id']}::{text_view_1_strategy}",
                "augmentation_strategy": augmentation_strategy or text_view_1_strategy,
                "augmentation_seed": augmentation_seed,
                "augmentation_validity": augmentation_validity or {},
            }
        )
    return preview


def build_preview_rows(dataset_dir: Path, tokenizer: Any) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    preview_rows: list[dict[str, Any]] = []
    rows_by_split: dict[str, list[dict[str, Any]]] = {}
    for split in DEFAULT_SPLITS:
        split_rows: list[dict[str, Any]] = []
        for line_no, row in enumerate(read_jsonl(dataset_dir / f"{split}.jsonl"), start=1):
            validate_input_row(row, split, line_no)
            if row.get("split") != split:
                raise ValueError(f"{split}:{line_no}: split field is {row.get('split')!r}, expected {split!r}")
            preview = build_preview_record(row, tokenizer)
            preview_rows.append(preview)
            split_rows.append(preview)
        rows_by_split[split] = split_rows
    return preview_rows, rows_by_split


def decode_equals(tokenizer: Any, token_ids: list[int], expected_text: str) -> bool:
    return tokenizer.decode(token_ids, skip_special_tokens=False) == expected_text


def require_rdkit() -> Any:
    try:
        from rdkit import Chem, RDLogger
    except ImportError as exc:
        raise RuntimeError(
            "restore_aug_v1 requires RDKit. Install requirements-stage-c.txt or run in the GPU environment; "
            "identity template generation does not require RDKit."
        ) from exc
    RDLogger.DisableLog("rdApp.*")
    return Chem


def count_attachment_atoms(mol: Any) -> int:
    return sum(1 for atom in mol.GetAtoms() if atom.GetSymbol() == "*")


def rdkit_validity(smiles: str, Chem: Any) -> dict[str, Any]:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {
            "rdkit_valid": False,
            "two_attachment_valid": False,
            "attachment_count": None,
        }
    attachment_count = count_attachment_atoms(mol)
    return {
        "rdkit_valid": True,
        "two_attachment_valid": attachment_count == 2,
        "attachment_count": attachment_count,
    }


def rdkit_random_smiles(canonical_smiles: str, seed: int, Chem: Any) -> tuple[str | None, dict[str, Any]]:
    mol = Chem.MolFromSmiles(canonical_smiles)
    if mol is None:
        return None, {"rdkit_valid": False, "failure_reason": "source_parse_failed"}
    try:
        from rdkit import rdBase

        rdBase.SeedRandomNumberGenerator(seed & 0xFFFFFFFF)
    except Exception:
        pass
    view = Chem.MolToSmiles(mol, canonical=False, doRandom=True, isomericSmiles=True)
    validity = rdkit_validity(view, Chem)
    return view, validity


def attachment_rooted_smiles(canonical_smiles: str, Chem: Any) -> tuple[str | None, dict[str, Any]]:
    mol = Chem.MolFromSmiles(canonical_smiles)
    if mol is None:
        return None, {"rdkit_valid": False, "failure_reason": "source_parse_failed"}
    attachment_atom_ids = [atom.GetIdx() for atom in mol.GetAtoms() if atom.GetSymbol() == "*"]
    if len(attachment_atom_ids) != 2:
        return None, {
            "rdkit_valid": True,
            "two_attachment_valid": False,
            "attachment_count": len(attachment_atom_ids),
            "failure_reason": "source_attachment_count_not_two",
        }
    view = Chem.MolToSmiles(
        mol,
        canonical=False,
        rootedAtAtom=attachment_atom_ids[1],
        isomericSmiles=True,
    )
    validity = rdkit_validity(view, Chem)
    validity["rooted_attachment_atom_id"] = attachment_atom_ids[1]
    return view, validity


def tokenize_smiles_for_denoise(smiles: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(smiles):
        char = smiles[index]
        if char == "[":
            end = smiles.find("]", index + 1)
            if end != -1:
                tokens.append(smiles[index : end + 1])
                index = end + 1
                continue
        if char == "%" and index + 2 < len(smiles) and smiles[index + 1 : index + 3].isdigit():
            tokens.append(smiles[index : index + 3])
            index += 3
            continue
        if index + 1 < len(smiles) and smiles[index : index + 2] in {"Cl", "Br", "Si", "Na", "Ca", "Cd", "Pb", "Sn", "Se", "Ge"}:
            tokens.append(smiles[index : index + 2])
            index += 2
            continue
        tokens.append(char)
        index += 1
    return tokens


def is_attachment_token(token: str) -> bool:
    return token == "*" or "*" in token


def light_denoise_smiles(canonical_smiles: str, seed: int) -> tuple[str, dict[str, Any]]:
    rng = random.Random(seed)
    tokens = tokenize_smiles_for_denoise(canonical_smiles)
    mutable_indices = [index for index, token in enumerate(tokens) if not is_attachment_token(token)]
    if not mutable_indices:
        return canonical_smiles, {
            "rdkit_valid": None,
            "two_attachment_valid": canonical_smiles.count("*") == 2,
            "denoise_mode": "identity_fallback",
            "attachment_count": canonical_smiles.count("*"),
        }

    use_mask = stable_hash_int("light_denoise_mode", seed) % 2 == 0
    if use_mask:
        change_count = max(1, round(len(mutable_indices) * 0.08))
        selected = set(rng.sample(mutable_indices, min(change_count, len(mutable_indices))))
        denoised_tokens = ["<mask>" if index in selected else token for index, token in enumerate(tokens)]
        mode = "token_mask"
    else:
        max_span = min(2, len(mutable_indices))
        target_drop_count = max(1, round(len(mutable_indices) * 0.05))
        candidates: list[tuple[int, int]] = []
        for start in mutable_indices:
            for span_len in range(1, max_span + 1):
                end = start + span_len
                if end > len(tokens):
                    continue
                if any(is_attachment_token(token) for token in tokens[start:end]):
                    continue
                candidates.append((start, span_len))
        if not candidates:
            selected = {rng.choice(mutable_indices)}
            denoised_tokens = ["<mask>" if index in selected else token for index, token in enumerate(tokens)]
            mode = "token_mask_fallback"
        else:
            start, span_len = rng.choice(candidates)
            span_len = min(span_len, target_drop_count)
            drop_indices = set(range(start, start + span_len))
            denoised_tokens = [token for index, token in enumerate(tokens) if index not in drop_indices]
            mode = "span_dropout"

    view = "".join(denoised_tokens)
    return view, {
        "rdkit_valid": None,
        "two_attachment_valid": view.count("*") == 2,
        "denoise_mode": mode,
        "attachment_count": view.count("*"),
    }


def stage_c_strategy_for_record(row: dict[str, Any]) -> str:
    bucket = stable_hash_int("stage_c_restore_aug_v1", row["record_id"], row["canonical_hash"]) % 10
    if bucket < 3:
        return "identity"
    if bucket < 6:
        return "rdkit_random_smiles"
    if bucket < 8:
        return "attachment_rooted_smiles"
    return "light_denoise"


def augmentation_seed(row: dict[str, Any], strategy: str, context: str) -> int:
    return stable_hash_int("restore_aug_v1", context, row["record_id"], row["canonical_hash"], strategy) & 0x7FFFFFFF


def make_augmented_preview_record(
    row: dict[str, Any],
    tokenizer: Any,
    *,
    strategy: str,
    context: str,
    Chem: Any,
    max_seq_len_view: int,
    allow_identity_fallback: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    seed = augmentation_seed(row, strategy, context)
    canonical_smiles = str(row["canonical_smiles"])
    failure: dict[str, Any] | None = None
    requested_strategy = strategy
    if strategy == "identity":
        text_view = canonical_smiles
        validity = rdkit_validity(text_view, Chem)
    elif strategy == "rdkit_random_smiles":
        text_view, validity = rdkit_random_smiles(canonical_smiles, seed, Chem)
    elif strategy == "attachment_rooted_smiles":
        text_view, validity = attachment_rooted_smiles(canonical_smiles, Chem)
    elif strategy == "light_denoise":
        text_view, validity = light_denoise_smiles(canonical_smiles, seed)
    else:
        raise ValueError(f"unknown augmentation strategy: {strategy}")

    if text_view is None:
        failure = {
            "record_id": row["record_id"],
            "split": row["split"],
            "canonical_hash": row["canonical_hash"],
            "strategy": requested_strategy,
            "context": context,
            "reason": validity.get("failure_reason", "augmentation_failed"),
        }
    elif strategy in {"rdkit_random_smiles", "attachment_rooted_smiles"} and (
        not validity.get("rdkit_valid") or not validity.get("two_attachment_valid")
    ):
        failure = {
            "record_id": row["record_id"],
            "split": row["split"],
            "canonical_hash": row["canonical_hash"],
            "strategy": requested_strategy,
            "context": context,
            "reason": "rdkit_view_invalid_or_attachment_count_not_two",
            "validity": validity,
            "text_view_1": text_view,
        }
    elif strategy == "light_denoise" and not validity.get("two_attachment_valid"):
        failure = {
            "record_id": row["record_id"],
            "split": row["split"],
            "canonical_hash": row["canonical_hash"],
            "strategy": requested_strategy,
            "context": context,
            "reason": "denoise_attachment_count_not_two",
            "validity": validity,
            "text_view_1": text_view,
        }

    if failure is not None:
        if not allow_identity_fallback:
            return None, failure
        text_view = canonical_smiles
        strategy = "identity_fallback"
        validity = {
            **rdkit_validity(text_view, Chem),
            "fallback_from": requested_strategy,
        }

    preview = build_preview_record(
        row,
        tokenizer,
        text_view_1=text_view,
        text_view_1_strategy=strategy,
        include_aug_metadata=True,
        view_id=f"{row['record_id']}::{context}::{strategy}",
        augmentation_strategy=strategy,
        augmentation_seed=seed,
        augmentation_validity=validity,
    )
    if preview["view1_token_length"] > max_seq_len_view:
        overflow_failure = {
            "record_id": row["record_id"],
            "split": row["split"],
            "canonical_hash": row["canonical_hash"],
            "strategy": requested_strategy,
            "context": context,
            "reason": "view_length_overflow",
            "view1_token_length": preview["view1_token_length"],
            "max_seq_len_view": max_seq_len_view,
        }
        if not allow_identity_fallback:
            return None, overflow_failure
        preview = build_preview_record(
            row,
            tokenizer,
            text_view_1=canonical_smiles,
            text_view_1_strategy="identity_fallback",
            include_aug_metadata=True,
            view_id=f"{row['record_id']}::{context}::identity_fallback",
            augmentation_strategy="identity_fallback",
            augmentation_seed=seed,
            augmentation_validity={**rdkit_validity(canonical_smiles, Chem), "fallback_from": requested_strategy},
        )
        return preview, overflow_failure
    return preview, failure


def collect_examples(rows: list[dict[str, Any]], predicate: Any, limit: int = 20) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for row in rows:
        if not predicate(row):
            continue
        examples.append(
            {
                "record_id": row["record_id"],
                "split": row["split"],
                "canonical_smiles": row["canonical_smiles"],
                "view1_token_length": row["view1_token_length"],
                "restore_label_length": row["restore_label_length"],
            }
        )
        if len(examples) >= limit:
            break
    return examples


def empty_rows_by_split() -> dict[str, list[dict[str, Any]]]:
    return {split: [] for split in DEFAULT_SPLITS}


def rows_by_split_from_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = empty_rows_by_split()
    for row in rows:
        split = str(row["split"])
        if split not in grouped:
            raise ValueError(f"unknown split in preview rows: {split!r}")
        grouped[split].append(row)
    return grouped


def augmentation_strategy_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        strategy = str(row.get("augmentation_strategy") or row.get("text_view_1_strategy") or "unknown")
        counts[strategy] = counts.get(strategy, 0) + 1
    return dict(sorted(counts.items()))


def boolean_counts(values: list[Any]) -> dict[str, int]:
    return {
        "true": sum(1 for value in values if value is True),
        "false": sum(1 for value in values if value is False),
        "unknown": sum(1 for value in values if value is None),
    }


def augmentation_validity_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    validity_rows = [row.get("augmentation_validity") or {} for row in rows]
    return {
        "rdkit_valid": boolean_counts([validity.get("rdkit_valid") for validity in validity_rows]),
        "two_attachment_valid": boolean_counts([validity.get("two_attachment_valid") for validity in validity_rows]),
    }


def record_id_uniqueness_by_split(rows_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for split, rows in rows_by_split.items():
        seen: set[str] = set()
        duplicates: list[str] = []
        for row in rows:
            record_id = str(row["record_id"])
            if record_id in seen:
                duplicates.append(record_id)
            else:
                seen.add(record_id)
        result[split] = {
            "row_count": len(rows),
            "unique_record_id_count": len(seen),
            "duplicate_record_id_count": len(duplicates),
            "duplicate_record_id_examples": duplicates[:20],
        }
    return result


def quality_checks_for_rows(
    rows: list[dict[str, Any]],
    tokenizer: Any,
    *,
    max_seq_len_view: int,
    max_seq_len_restore_label: int,
) -> dict[str, Any]:
    view_roundtrip_failures = [
        row
        for row in rows
        if not decode_equals(tokenizer, row["input_ids_view1"], row["input_text_view1"])
    ]
    restore_roundtrip_failures = [
        row
        for row in rows
        if not decode_equals(tokenizer, row["restore_labels"], row["target_text"])
    ]
    view_overflows = [row for row in rows if row["view1_token_length"] > max_seq_len_view]
    restore_overflows = [row for row in rows if row["restore_label_length"] > max_seq_len_restore_label]
    mask_failures = [
        row
        for row in rows
        if len(row["attention_mask_view1"]) != len(row["input_ids_view1"])
        or len(row["restore_label_mask"]) != len(row["restore_labels"])
        or any(value != 1 for value in row["attention_mask_view1"])
        or any(value is not True for value in row["restore_label_mask"])
    ]
    return {
        "view_roundtrip_failure_count": len(view_roundtrip_failures),
        "restore_roundtrip_failure_count": len(restore_roundtrip_failures),
        "view_length_overflow_count": len(view_overflows),
        "restore_label_length_overflow_count": len(restore_overflows),
        "mask_failure_count": len(mask_failures),
        "view_roundtrip_failure_examples": collect_examples(view_roundtrip_failures, lambda _row: True),
        "restore_roundtrip_failure_examples": collect_examples(restore_roundtrip_failures, lambda _row: True),
        "view_length_overflow_examples": collect_examples(view_overflows, lambda _row: True),
        "restore_label_length_overflow_examples": collect_examples(restore_overflows, lambda _row: True),
        "mask_failure_examples": collect_examples(mask_failures, lambda _row: True),
    }


def split_length_stats(rows_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    return {
        split: {
            "count": len(rows),
            "view1_token_length": length_stats([row["view1_token_length"] for row in rows]),
            "restore_label_length": length_stats([row["restore_label_length"] for row in rows]),
            "longest_view1_examples": sorted(
                collect_examples(rows, lambda _row: True, limit=len(rows)),
                key=lambda item: (-item["view1_token_length"], item["record_id"]),
            )[:10],
            "longest_restore_label_examples": sorted(
                collect_examples(rows, lambda _row: True, limit=len(rows)),
                key=lambda item: (-item["restore_label_length"], item["record_id"]),
            )[:10],
        }
        for split, rows in rows_by_split.items()
    }


def build_stats(
    rows_by_split: dict[str, list[dict[str, Any]]],
    tokenizer: Any,
    *,
    tokenizer_dir: Path,
    dataset_dir: Path,
    output_dir: Path,
    max_seq_len_view: int,
    max_seq_len_restore_label: int,
) -> dict[str, Any]:
    all_rows = [row for split in DEFAULT_SPLITS for row in rows_by_split[split]]

    return {
        "stage": "stage_a_restore_only_template_preview",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_dir": str(dataset_dir),
        "output_dir": str(output_dir),
        "input_files": {split: str(dataset_dir / f"{split}.jsonl") for split in DEFAULT_SPLITS},
        "outputs": {
            "preview_jsonl": str(output_dir / "training_template_preview.jsonl"),
            "stats_json": str(output_dir / "training_template_stats.json"),
            "report_md": str(output_dir / "training_template_report.md"),
        },
        "template": {
            "task": "restore_only",
            "text_view_1_strategy": "identity",
            "uses_text_view_2": False,
            "uses_graph_tensor": False,
            "uses_fragment_vocab": False,
            "input_text_view1": "<polymer_view_smiles>\\n{text_view_1}\\n</polymer_view_smiles>\\n",
            "target_text": "canonical_text_target + tokenizer.eos_token",
        },
        "tokenizer": {
            "path": str(tokenizer_dir),
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
        "counts": {
            "total": len(all_rows),
            **{split: len(rows_by_split[split]) for split in DEFAULT_SPLITS},
        },
        "splits": split_length_stats(rows_by_split),
        "quality_checks": quality_checks_for_rows(
            all_rows,
            tokenizer,
            max_seq_len_view=max_seq_len_view,
            max_seq_len_restore_label=max_seq_len_restore_label,
        ),
    }


def build_augmented_stats(
    *,
    output_dir: Path,
    dataset_dir: Path,
    tokenizer_dir: Path,
    tokenizer: Any,
    training_rows: list[dict[str, Any]],
    stage_c_rows: list[dict[str, Any]],
    robustness_rows: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    max_seq_len_view: int,
    max_seq_len_restore_label: int,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    files = {
        "training_preview_jsonl": str(output_dir / TRAINING_PREVIEW),
        "stage_c_training_preview_jsonl": str(output_dir / STAGE_C_TRAINING_PREVIEW),
        "robustness_eval_preview_jsonl": str(output_dir / ROBUSTNESS_EVAL_PREVIEW),
        "augmentation_failures_jsonl": str(output_dir / AUGMENTATION_FAILURES),
        "stats_json": str(output_dir / "training_template_stats.json"),
        "report_md": str(output_dir / "training_template_report.md"),
    }

    def preview_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        rows_by_split = rows_by_split_from_rows(rows)
        return {
            "counts": {
                "total": len(rows),
                **{split: len(rows_by_split[split]) for split in DEFAULT_SPLITS},
            },
            "augmentation_strategy_counts": augmentation_strategy_counts(rows),
            "augmentation_validity_counts": augmentation_validity_counts(rows),
            "augmentation_validity_counts_by_split": {
                split: augmentation_validity_counts(split_rows) for split, split_rows in rows_by_split.items()
            },
            "record_id_uniqueness_by_split": record_id_uniqueness_by_split(rows_by_split),
            "splits": split_length_stats(rows_by_split),
            "quality_checks": quality_checks_for_rows(
                rows,
                tokenizer,
                max_seq_len_view=max_seq_len_view,
                max_seq_len_restore_label=max_seq_len_restore_label,
            ),
        }

    return {
        "stage": "stage_a_restore_aug_v1_template_preview",
        "generated_at_utc": generated_at,
        "dataset_dir": str(dataset_dir),
        "output_dir": str(output_dir),
        "input_files": {split: str(dataset_dir / f"{split}.jsonl") for split in DEFAULT_SPLITS},
        "outputs": files,
        "template": {
            "task": "restore_only_augmented",
            "augmentation_policy": AUGMENTATION_POLICY_RESTORE_AUG_V1,
            "uses_text_view_2": False,
            "uses_graph_tensor": False,
            "uses_fragment_vocab": False,
            "input_text_view1": "<polymer_view_smiles>\\n{text_view_1}\\n</polymer_view_smiles>\\n",
            "target_text": "canonical_text_target + tokenizer.eos_token",
            "stage_b_train_views_per_record": 4,
            "stage_c_train_views_per_record": 1,
            "stage_c_strategy_distribution": {
                "identity": 0.30,
                "rdkit_random_smiles": 0.30,
                "attachment_rooted_smiles": 0.20,
                "light_denoise": 0.20,
            },
        },
        "tokenizer": {
            "path": str(tokenizer_dir),
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
            "training": preview_summary(training_rows),
            "stage_c_training": preview_summary(stage_c_rows),
            "robustness_eval": preview_summary(robustness_rows),
        },
        "augmentation_failures": {
            "count": len(failures),
            "examples": failures[:20],
        },
    }


def write_report(path: Path, stats: dict[str, Any]) -> None:
    quality = stats["quality_checks"]
    lines = [
        "# BaseLite Stage A Restore-Only 模板预览报告",
        "",
        f"- 生成时间 UTC: `{stats['generated_at_utc']}`",
        f"- tokenizer 路径: `{stats['tokenizer']['path']}`",
        f"- tokenizer class: `{stats['tokenizer']['class']}`",
        f"- vocab size: `{stats['tokenizer']['vocab_size']}`",
        f"- eos token: `{stats['tokenizer']['eos_token']}` / `{stats['tokenizer']['eos_token_id']}`",
        f"- pad token: `{stats['tokenizer']['pad_token']}` / `{stats['tokenizer']['pad_token_id']}`",
        f"- 总记录数: `{stats['counts']['total']}`",
        "",
        "## Stage A 口径",
        "",
        "- 本阶段是 restore-only template preview，不训练模型。",
        "- `text_view_1_strategy` 固定为 `identity`，不做扰动。",
        "- 不生成 `text_view_2`。",
        "- 不接 graph tensor。",
        "- 不接 fragment vocab / fragment labels。",
        "- target 单独 tokenize 为 `restore_labels`，不拼入 `input_text_view1`。",
        "",
        "## 模板",
        "",
        "```text",
        "<polymer_view_smiles>",
        "{text_view_1}",
        "</polymer_view_smiles>",
        "```",
        "",
        "restore target:",
        "",
        "```text",
        "{canonical_text_target}<|endoftext|>",
        "```",
        "",
        "## 长度统计",
        "",
        "| split | count | view p50 | view p90 | view p95 | view p99 | view max | restore p50 | restore p90 | restore p95 | restore p99 | restore max |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for split in DEFAULT_SPLITS:
        row = stats["splits"][split]
        view = row["view1_token_length"]
        restore = row["restore_label_length"]
        lines.append(
            f"| {split} | {row['count']} | {view['p50']} | {view['p90']} | {view['p95']} | {view['p99']} | {view['max']} | "
            f"{restore['p50']} | {restore['p90']} | {restore['p95']} | {restore['p99']} | {restore['max']} |"
        )

    lines.extend(
        [
            "",
            "## 质量检查",
            "",
            f"- view template round-trip failures: `{quality['view_roundtrip_failure_count']}`",
            f"- restore label round-trip failures: `{quality['restore_roundtrip_failure_count']}`",
            f"- view length overflow: `{quality['view_length_overflow_count']}`",
            f"- restore label length overflow: `{quality['restore_label_length_overflow_count']}`",
            f"- mask failures: `{quality['mask_failure_count']}`",
            "",
            "## 输出文件",
            "",
            f"- preview JSONL: `{stats['outputs']['preview_jsonl']}`",
            f"- stats JSON: `{stats['outputs']['stats_json']}`",
            f"- report MD: `{stats['outputs']['report_md']}`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_augmented_report(path: Path, stats: dict[str, Any]) -> None:
    lines = [
        "# BaseLite Stage A Restore 增强模板预览报告",
        "",
        f"- 生成时间 UTC: `{stats['generated_at_utc']}`",
        f"- tokenizer 路径: `{stats['tokenizer']['path']}`",
        f"- tokenizer class: `{stats['tokenizer']['class']}`",
        f"- eos token: `{stats['tokenizer']['eos_token']}` / `{stats['tokenizer']['eos_token_id']}`",
        f"- augmentation policy: `{stats['template']['augmentation_policy']}`",
        "",
        "## Stage A 增强口径",
        "",
        "- 本阶段只生成 restore-only 增强模板，不训练模型。",
        "- target 单独 tokenize 为 `restore_labels`，不拼入 `input_text_view1`。",
        "- 不生成 `text_view_2`，不接 fragment vocab / fragment labels。",
        "- Stage B train 每个 record 物化四个 view；Stage C train 每个 record 只保留一个稳定 view，避免 InfoNCE false negative。",
        "- valid/test 主模板保持 identity；鲁棒性评估单独写入 `robustness_eval_preview.jsonl`。",
        "",
        "## 输出文件",
        "",
    ]
    for key, value in stats["outputs"].items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(["", "## 预览集统计", ""])
    for preview_name, preview in stats["previews"].items():
        lines.extend(
            [
                f"### {preview_name}",
                "",
                f"- total: `{preview['counts']['total']}`",
                f"- train/valid/test: `{preview['counts']['train']}` / `{preview['counts']['valid']}` / `{preview['counts']['test']}`",
                f"- strategy counts: `{preview['augmentation_strategy_counts']}`",
                f"- validity counts: `{preview['augmentation_validity_counts']}`",
                "",
                "| split | count | view p50 | view p90 | view p95 | view p99 | view max | restore p50 | restore p90 | restore p95 | restore p99 | restore max |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for split in DEFAULT_SPLITS:
            row = preview["splits"][split]
            view = row["view1_token_length"]
            restore = row["restore_label_length"]
            lines.append(
                f"| {split} | {row['count']} | {view['p50']} | {view['p90']} | {view['p95']} | {view['p99']} | {view['max']} | "
                f"{restore['p50']} | {restore['p90']} | {restore['p95']} | {restore['p99']} | {restore['max']} |"
            )
        quality = preview["quality_checks"]
        lines.extend(
            [
                "",
                f"- view template round-trip failures: `{quality['view_roundtrip_failure_count']}`",
                f"- restore label round-trip failures: `{quality['restore_roundtrip_failure_count']}`",
                f"- view length overflow: `{quality['view_length_overflow_count']}`",
                f"- restore label length overflow: `{quality['restore_label_length_overflow_count']}`",
                f"- mask failures: `{quality['mask_failure_count']}`",
                "",
                "| split | RDKit valid T/F/? | two attachment T/F/? | duplicate record_id |",
                "|---|---:|---:|---:|",
            ]
        )
        for split in DEFAULT_SPLITS:
            rdkit_counts = preview["augmentation_validity_counts_by_split"][split]["rdkit_valid"]
            two_attachment_counts = preview["augmentation_validity_counts_by_split"][split]["two_attachment_valid"]
            duplicate_count = preview["record_id_uniqueness_by_split"][split]["duplicate_record_id_count"]
            lines.append(
                f"| {split} | {rdkit_counts['true']}/{rdkit_counts['false']}/{rdkit_counts['unknown']} | "
                f"{two_attachment_counts['true']}/{two_attachment_counts['false']}/{two_attachment_counts['unknown']} | "
                f"{duplicate_count} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 增强失败记录",
            "",
            f"- count: `{stats['augmentation_failures']['count']}`",
        ]
    )
    if stats["augmentation_failures"]["examples"]:
        lines.append("- examples are written to `augmentation_failures.jsonl`.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_or_fail(rows: list[dict[str, Any]], failures: list[dict[str, Any]], row: dict[str, Any] | None, failure: dict[str, Any] | None) -> None:
    if row is not None:
        rows.append(row)
    if failure is not None:
        failures.append(failure)


def build_augmented_preview_rows(
    dataset_dir: Path,
    tokenizer: Any,
    *,
    max_seq_len_view: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    Chem = require_rdkit()
    training_rows: list[dict[str, Any]] = []
    stage_c_rows: list[dict[str, Any]] = []
    robustness_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for split in DEFAULT_SPLITS:
        for line_no, row in enumerate(read_jsonl(dataset_dir / f"{split}.jsonl"), start=1):
            validate_input_row(row, split, line_no)
            if row.get("split") != split:
                raise ValueError(f"{split}:{line_no}: split field is {row.get('split')!r}, expected {split!r}")

            if split == "train":
                for strategy in ("identity", "rdkit_random_smiles", "attachment_rooted_smiles", "light_denoise"):
                    preview, failure = make_augmented_preview_record(
                        row,
                        tokenizer,
                        strategy=strategy,
                        context="stage_b_train",
                        Chem=Chem,
                        max_seq_len_view=max_seq_len_view,
                    )
                    append_or_fail(training_rows, failures, preview, failure)

                stage_c_strategy = stage_c_strategy_for_record(row)
                stage_c_preview, failure = make_augmented_preview_record(
                    row,
                    tokenizer,
                    strategy=stage_c_strategy,
                    context="stage_c_train",
                    Chem=Chem,
                    max_seq_len_view=max_seq_len_view,
                    allow_identity_fallback=True,
                )
                append_or_fail(stage_c_rows, failures, stage_c_preview, failure)
                continue

            identity_preview, failure = make_augmented_preview_record(
                row,
                tokenizer,
                strategy="identity",
                context="identity_eval",
                Chem=Chem,
                max_seq_len_view=max_seq_len_view,
            )
            append_or_fail(training_rows, failures, identity_preview, failure)
            stage_c_identity, failure = make_augmented_preview_record(
                row,
                tokenizer,
                strategy="identity",
                context="stage_c_identity_eval",
                Chem=Chem,
                max_seq_len_view=max_seq_len_view,
            )
            append_or_fail(stage_c_rows, failures, stage_c_identity, failure)

            for strategy in ("rdkit_random_smiles", "light_denoise"):
                robustness_preview, failure = make_augmented_preview_record(
                    row,
                    tokenizer,
                    strategy=strategy,
                    context="robustness_eval",
                    Chem=Chem,
                    max_seq_len_view=max_seq_len_view,
                )
                append_or_fail(robustness_rows, failures, robustness_preview, failure)

    return training_rows, stage_c_rows, robustness_rows, failures


def assert_quality(stats: dict[str, Any]) -> None:
    if stats.get("stage") == "stage_a_restore_aug_v1_template_preview":
        qualities = {
            f"{name}.{key}": value
            for name, preview in stats["previews"].items()
            for key, value in preview["quality_checks"].items()
            if key.endswith("_count")
        }
        stage_c_duplicate_counts = {
            f"stage_c_training.{split}.duplicate_record_id_count": check["duplicate_record_id_count"]
            for split, check in stats["previews"]["stage_c_training"]["record_id_uniqueness_by_split"].items()
        }
        qualities.update(stage_c_duplicate_counts)
        failed = {name: count for name, count in qualities.items() if count}
        if failed:
            raise SystemExit(f"Stage A validation failed: {json.dumps(failed, sort_keys=True)}")
        return

    quality = stats["quality_checks"]
    failures = {
        "view_roundtrip_failure_count": quality["view_roundtrip_failure_count"],
        "restore_roundtrip_failure_count": quality["restore_roundtrip_failure_count"],
        "view_length_overflow_count": quality["view_length_overflow_count"],
        "restore_label_length_overflow_count": quality["restore_label_length_overflow_count"],
        "mask_failure_count": quality["mask_failure_count"],
    }
    failed = {name: count for name, count in failures.items() if count}
    if failed:
        raise SystemExit(f"Stage A validation failed: {json.dumps(failed, sort_keys=True)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BaseLite Stage A restore-only template preview.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--tokenizer-dir", type=Path, default=DEFAULT_TOKENIZER_DIR)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--max-seq-len-view", type=int, default=512)
    parser.add_argument("--max-seq-len-restore-label", type=int, default=512)
    parser.add_argument(
        "--augmentation-policy",
        choices=[AUGMENTATION_POLICY_IDENTITY, AUGMENTATION_POLICY_RESTORE_AUG_V1],
        default=AUGMENTATION_POLICY_IDENTITY,
    )
    parser.add_argument("--summary", action="store_true")
    return parser.parse_args()


def main() -> None:
    from transformers import AutoTokenizer

    args = parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_dir, local_files_only=True, use_fast=True)
    if not tokenizer.eos_token:
        raise ValueError("tokenizer must define eos_token")

    output_dir = args.output_dir
    if output_dir is None:
        output_dir = DEFAULT_AUGMENTED_OUTPUT_DIR if args.augmentation_policy == AUGMENTATION_POLICY_RESTORE_AUG_V1 else DEFAULT_DATASET_DIR

    if args.augmentation_policy == AUGMENTATION_POLICY_RESTORE_AUG_V1:
        training_rows, stage_c_rows, robustness_rows, failures = build_augmented_preview_rows(
            args.dataset_dir,
            tokenizer,
            max_seq_len_view=args.max_seq_len_view,
        )
        stats = build_augmented_stats(
            output_dir=output_dir,
            dataset_dir=args.dataset_dir,
            tokenizer_dir=args.tokenizer_dir,
            tokenizer=tokenizer,
            training_rows=training_rows,
            stage_c_rows=stage_c_rows,
            robustness_rows=robustness_rows,
            failures=failures,
            max_seq_len_view=args.max_seq_len_view,
            max_seq_len_restore_label=args.max_seq_len_restore_label,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(output_dir / TRAINING_PREVIEW, training_rows)
        write_jsonl(output_dir / STAGE_C_TRAINING_PREVIEW, stage_c_rows)
        write_jsonl(output_dir / ROBUSTNESS_EVAL_PREVIEW, robustness_rows)
        write_jsonl(output_dir / AUGMENTATION_FAILURES, failures)
        (output_dir / "training_template_stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        write_augmented_report(output_dir / "training_template_report.md", stats)
        assert_quality(stats)

        if args.summary:
            summary = {
                "augmentation_policy": args.augmentation_policy,
                "previews": {
                    name: {
                        "counts": preview["counts"],
                        "augmentation_strategy_counts": preview["augmentation_strategy_counts"],
                        "augmentation_validity_counts": preview["augmentation_validity_counts"],
                    }
                    for name, preview in stats["previews"].items()
                },
                "augmentation_failures": stats["augmentation_failures"]["count"],
                "outputs": stats["outputs"],
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return

    preview_rows, rows_by_split = build_preview_rows(args.dataset_dir, tokenizer)
    stats = build_stats(
        rows_by_split,
        tokenizer,
        tokenizer_dir=args.tokenizer_dir,
        dataset_dir=args.dataset_dir,
        output_dir=output_dir,
        max_seq_len_view=args.max_seq_len_view,
        max_seq_len_restore_label=args.max_seq_len_restore_label,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "training_template_preview.jsonl", preview_rows)
    (output_dir / "training_template_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(output_dir / "training_template_report.md", stats)
    assert_quality(stats)

    if args.summary:
        summary = {
            "counts": stats["counts"],
            "quality_checks": {
                key: value
                for key, value in stats["quality_checks"].items()
                if key.endswith("_count")
            },
            "max_lengths": {
                split: {
                    "view1": stats["splits"][split]["view1_token_length"]["max"],
                    "restore_label": stats["splits"][split]["restore_label_length"]["max"],
                }
                for split in DEFAULT_SPLITS
            },
            "outputs": stats["outputs"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
