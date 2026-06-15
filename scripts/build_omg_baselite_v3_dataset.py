from __future__ import annotations

import argparse
import csv
import heapq
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.omg_v3_common import (
        OMG_V3_DATASET_NAME,
        OMG_V3_RECORD_PREFIX,
        OMG_V3_SAMPLE_SEED,
        OMG_V3_SPLIT_SEED,
        ROOT,
        SPLITS,
        graph_hash_for_smiles,
        leakage_report,
        load_current_canonical_hashes,
        require_rdkit,
        sha256_file,
        sha256_text,
        stable_hash_int,
        validate_repeat_unit_product,
        write_json,
        write_jsonl,
    )
except ModuleNotFoundError:
    from omg_v3_common import (
        OMG_V3_DATASET_NAME,
        OMG_V3_RECORD_PREFIX,
        OMG_V3_SAMPLE_SEED,
        OMG_V3_SPLIT_SEED,
        ROOT,
        SPLITS,
        graph_hash_for_smiles,
        leakage_report,
        load_current_canonical_hashes,
        require_rdkit,
        sha256_file,
        sha256_text,
        stable_hash_int,
        validate_repeat_unit_product,
        write_json,
        write_jsonl,
    )


DEFAULT_CURRENT_DATASET_DIR = ROOT / "data" / "baselite_smiles_v1"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "baselite_smiles_v3"
DEFAULT_TARGET_COUNT = 1_000_000
DEFAULT_FLOOR_PER_REACTION = 1_000


def numeric_reaction_key(value: str) -> tuple[int, str]:
    try:
        return (int(value), value)
    except ValueError:
        return (10**9, value)


def progress_log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return resolved.name


def count_reactions(
    input_path: Path,
    *,
    max_source_rows: int | None = None,
    progress_every: int | None = None,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["reaction_idx", "reactant_1", "reactant_2", "product"]:
            raise ValueError(f"unexpected OMG CSV columns: {reader.fieldnames}")
        for row_index, row in enumerate(reader, start=1):
            if max_source_rows is not None and row_index > max_source_rows:
                break
            counts[str(row.get("reaction_idx") or "")] += 1
            if progress_every and row_index % progress_every == 0:
                progress_log(f"[count] rows={row_index} reactions={len(counts)}")
    return counts


def allocate_reaction_quotas(
    reaction_counts: Counter[str],
    *,
    target_count: int,
    floor_per_reaction: int,
) -> dict[str, int]:
    if target_count <= 0:
        raise ValueError("target_count must be positive")
    if floor_per_reaction < 0:
        raise ValueError("floor_per_reaction must be non-negative")
    if sum(reaction_counts.values()) < target_count:
        raise ValueError("target_count exceeds available OMG rows")

    ordered_reactions = sorted(reaction_counts, key=numeric_reaction_key)
    floor = {reaction: min(reaction_counts[reaction], floor_per_reaction) for reaction in ordered_reactions}
    floor_total = sum(floor.values())

    if floor_total <= target_count:
        quotas = dict(floor)
        remaining_target = target_count - floor_total
        remaining_available = {
            reaction: max(0, reaction_counts[reaction] - quotas[reaction]) for reaction in ordered_reactions
        }
    else:
        quotas = {reaction: 0 for reaction in ordered_reactions}
        remaining_target = target_count
        remaining_available = dict(reaction_counts)

    available_total = sum(remaining_available.values())
    if remaining_target and available_total <= 0:
        raise ValueError("no remaining rows available after floor allocation")

    raw_additions = {
        reaction: (remaining_target * remaining_available[reaction] / available_total if available_total else 0.0)
        for reaction in ordered_reactions
    }
    for reaction, raw_value in raw_additions.items():
        quotas[reaction] += int(raw_value)

    leftover = target_count - sum(quotas.values())
    remainders = sorted(
        ((reaction, raw_additions[reaction] - int(raw_additions[reaction])) for reaction in ordered_reactions),
        key=lambda item: (-item[1], numeric_reaction_key(item[0])),
    )
    for reaction, _ in remainders:
        if leftover <= 0:
            break
        if quotas[reaction] >= reaction_counts[reaction]:
            continue
        quotas[reaction] += 1
        leftover -= 1

    if leftover:
        for reaction in ordered_reactions:
            if leftover <= 0:
                break
            can_add = min(leftover, reaction_counts[reaction] - quotas[reaction])
            quotas[reaction] += can_add
            leftover -= can_add

    if sum(quotas.values()) != target_count:
        raise ValueError(f"quota allocation failed: expected {target_count}, got {sum(quotas.values())}")
    return {reaction: quotas[reaction] for reaction in ordered_reactions if quotas[reaction] > 0}


def sample_key_for_candidate(sample_seed: str, reaction_idx: str, canonical_hash: str) -> int:
    return stable_hash_int(sample_seed, "candidate", reaction_idx, canonical_hash)


def split_key(split_seed: str, graph_hash: str) -> int:
    return stable_hash_int(split_seed, graph_hash)


def selected_row_sort_key(row: dict[str, Any]) -> tuple[tuple[int, str], int, str]:
    return (numeric_reaction_key(str(row["source_reaction_idx"])), int(row["_sample_key"]), str(row["canonical_hash"]))


def replacement_row_sort_key(row: dict[str, Any]) -> tuple[int, tuple[int, str], str]:
    return (int(row["_sample_key"]), numeric_reaction_key(str(row["source_reaction_idx"])), str(row["canonical_hash"]))


def select_records(
    *,
    input_path: Path,
    quotas: dict[str, int],
    current_hashes: set[str],
    sample_seed: str,
    Chem: Any,
    max_invalid_examples: int = 20,
    max_source_rows: int | None = None,
    progress_every: int | None = 1_000_000,
    replacement_slack_per_reaction: int = 2_000,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    heaps: dict[str, list[tuple[int, int, dict[str, Any]]]] = {reaction: [] for reaction in quotas}
    seen_canonical_hashes: set[str] = set()
    counters: Counter[str] = Counter()
    reaction_valid_counts: Counter[str] = Counter()
    invalid_reasons: Counter[str] = Counter()
    invalid_examples: list[dict[str, Any]] = []
    seen_product_hashes: set[str] = set()
    tie_counter = 0

    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for source_row_index, row in enumerate(reader, start=1):
            if max_source_rows is not None and source_row_index > max_source_rows:
                break
            counters["csv_rows"] += 1
            reaction_idx = str(row.get("reaction_idx") or "")
            if reaction_idx not in quotas:
                counters["rows_skipped_unneeded_reaction"] += 1
                continue

            product = str(row.get("product") or "").strip()
            if not product:
                counters["rows_invalid"] += 1
                invalid_reasons["missing_product"] += 1
                if len(invalid_examples) < max_invalid_examples:
                    invalid_examples.append(
                        {
                            "source_row_index": source_row_index,
                            "reaction_idx": reaction_idx,
                            "product": product,
                            "reason": "missing_product",
                            "validity": {"valid": False, "reason": "missing_product"},
                        }
                    )
                continue
            if product.count("*") != 2:
                counters["rows_invalid"] += 1
                invalid_reasons["attachment_count_not_two"] += 1
                if len(invalid_examples) < max_invalid_examples:
                    invalid_examples.append(
                        {
                            "source_row_index": source_row_index,
                            "reaction_idx": reaction_idx,
                            "product": product,
                            "reason": "attachment_count_not_two",
                            "validity": {
                                "valid": False,
                                "reason": "attachment_count_not_two",
                                "attachment_count": product.count("*"),
                            },
                        }
                    )
                continue
            if "." in product:
                counters["rows_invalid"] += 1
                invalid_reasons["multi_component_product"] += 1
                if len(invalid_examples) < max_invalid_examples:
                    invalid_examples.append(
                        {
                            "source_row_index": source_row_index,
                            "reaction_idx": reaction_idx,
                            "product": product,
                            "reason": "multi_component_product",
                            "validity": {"valid": False, "reason": "multi_component_product"},
                        }
                    )
                continue

            product_hash = sha256_text(product)
            if product_hash in seen_product_hashes:
                counters["rows_skipped_duplicate_raw_product"] += 1
                continue
            seen_product_hashes.add(product_hash)

            canonical_smiles, validity = validate_repeat_unit_product(product, Chem)
            if canonical_smiles is None:
                counters["rows_invalid"] += 1
                reason = str(validity.get("reason", "unknown"))
                invalid_reasons[reason] += 1
                if len(invalid_examples) < max_invalid_examples:
                    invalid_examples.append(
                        {
                            "source_row_index": source_row_index,
                            "reaction_idx": reaction_idx,
                            "product": product,
                            "reason": reason,
                            "validity": validity,
                        }
                    )
                continue

            canonical_hash = sha256_text(canonical_smiles)
            if canonical_hash in current_hashes:
                counters["rows_skipped_current_overlap"] += 1
                continue
            if canonical_hash in seen_canonical_hashes:
                counters["rows_skipped_duplicate_canonical_hash"] += 1
                continue
            seen_canonical_hashes.add(canonical_hash)

            reaction_valid_counts[reaction_idx] += 1
            sample_key = sample_key_for_candidate(sample_seed, reaction_idx, canonical_hash)
            candidate = {
                "canonical_hash": canonical_hash,
                "canonical_smiles": canonical_smiles,
                "source_dataset": "OMG_polymers",
                "source_product_hash": product_hash,
                "source_reactant_1": str(row.get("reactant_1") or ""),
                "source_reactant_2": str(row.get("reactant_2") or ""),
                "source_reaction_idx": reaction_idx,
                "source_row_index": source_row_index,
            }
            heap = heaps[reaction_idx]
            tie_counter += 1
            item = (-sample_key, tie_counter, candidate)
            heap_capacity = quotas[reaction_idx] + max(0, replacement_slack_per_reaction)
            if len(heap) < heap_capacity:
                heapq.heappush(heap, item)
            elif heap and sample_key < -heap[0][0]:
                heapq.heapreplace(heap, item)

            if max_source_rows is not None and counters["csv_rows"] == max_source_rows:
                progress_log(f"[select] rows={counters['csv_rows']} selected_candidates={sum(len(heap) for heap in heaps.values())}")
            elif progress_every and counters["csv_rows"] % progress_every == 0:
                progress_log(
                    "[select] "
                    f"rows={counters['csv_rows']} "
                    f"unique_products={len(seen_product_hashes)} "
                    f"unique_canonical={len(seen_canonical_hashes)} "
                    f"selected_candidates={sum(len(heap) for heap in heaps.values())}"
                )

    quota_shortfalls: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    replacement_pool: list[dict[str, Any]] = []
    for reaction_idx, heap in heaps.items():
        ranked_rows: list[dict[str, Any]] = []
        for negative_key, _, candidate in heap:
            row = dict(candidate)
            row["_sample_key"] = -negative_key
            ranked_rows.append(row)
        ranked_rows.sort(key=lambda row: (int(row["_sample_key"]), row["canonical_hash"]))
        quota = quotas[reaction_idx]
        selected.extend(ranked_rows[:quota])
        replacement_pool.extend(ranked_rows[quota:])
        if len(ranked_rows) < quota:
            quota_shortfalls[reaction_idx] = quota - len(ranked_rows)

    replacement_rows: list[dict[str, Any]] = []
    deficit = sum(quotas.values()) - len(selected)
    replacement_pool.sort(key=replacement_row_sort_key)
    if deficit:
        if len(replacement_pool) < deficit:
            raise ValueError(
                "not enough valid OMG rows to satisfy total target after quota redistribution: "
                f"shortfalls={quota_shortfalls}, replacement_pool={len(replacement_pool)}, deficit={deficit}"
            )
        for row in replacement_pool[:deficit]:
            row["_quota_replacement"] = True
            replacement_rows.append(row)
        selected.extend(replacement_rows)
        replacement_pool = replacement_pool[deficit:]

    selected.sort(key=selected_row_sort_key)

    unique_graph_selected: list[dict[str, Any]] = []
    seen_graph_hashes: set[str] = set()
    selected_canonical_hashes: set[str] = set()
    graph_duplicate_rows: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        graph_hash = graph_hash_for_smiles(str(row["canonical_smiles"]), Chem)
        row["graph_hash"] = graph_hash
        if graph_hash in seen_graph_hashes:
            graph_duplicate_rows.append(row)
        else:
            seen_graph_hashes.add(graph_hash)
            selected_canonical_hashes.add(str(row["canonical_hash"]))
            unique_graph_selected.append(row)
        if index % 100_000 == 0:
            progress_log(f"[graph_hash] selected_records={index}")

    graph_replacement_rows: list[dict[str, Any]] = []
    graph_deficit = len(selected) - len(unique_graph_selected)
    if graph_deficit:
        progress_log(
            "[graph_dedupe] "
            f"duplicate_graph_hash_records={graph_deficit} "
            f"replacement_pool={len(replacement_pool)}"
        )
        for row in replacement_pool:
            canonical_hash = str(row["canonical_hash"])
            if canonical_hash in selected_canonical_hashes:
                continue
            graph_hash = row.get("graph_hash")
            if graph_hash is None:
                graph_hash = graph_hash_for_smiles(str(row["canonical_smiles"]), Chem)
                row["graph_hash"] = graph_hash
            if str(graph_hash) in seen_graph_hashes:
                continue
            row["_graph_replacement"] = True
            seen_graph_hashes.add(str(graph_hash))
            selected_canonical_hashes.add(canonical_hash)
            unique_graph_selected.append(row)
            graph_replacement_rows.append(row)
            if len(graph_replacement_rows) == graph_deficit:
                break
        if len(graph_replacement_rows) != graph_deficit:
            raise ValueError(
                "not enough valid OMG rows to enforce unique graph_hash: "
                f"duplicate_graph_hash_records={graph_deficit}, replacements={len(graph_replacement_rows)}"
            )

    selected = sorted(unique_graph_selected, key=selected_row_sort_key)
    for index, row in enumerate(selected, start=1):
        row["record_id"] = f"{OMG_V3_RECORD_PREFIX}_{index:07d}"

    audit = {
        "counters": dict(counters),
        "invalid_reasons": dict(sorted(invalid_reasons.items())),
        "invalid_examples": invalid_examples,
        "reaction_valid_unique_counts": dict(sorted(reaction_valid_counts.items(), key=lambda item: numeric_reaction_key(item[0]))),
        "quota_shortfalls_after_filtering": dict(sorted(quota_shortfalls.items(), key=lambda item: numeric_reaction_key(item[0]))),
        "replacement_count": len(replacement_rows),
        "replacement_reaction_counts": dict(
            sorted(
                Counter(str(row["source_reaction_idx"]) for row in replacement_rows).items(),
                key=lambda item: numeric_reaction_key(item[0]),
            )
        ),
        "graph_duplicate_drop_count": len(graph_duplicate_rows),
        "graph_duplicate_examples": [
            {
                "canonical_hash": str(row["canonical_hash"]),
                "canonical_smiles": str(row["canonical_smiles"]),
                "graph_hash": str(row["graph_hash"]),
                "source_reaction_idx": str(row["source_reaction_idx"]),
            }
            for row in graph_duplicate_rows[:20]
        ],
        "graph_replacement_count": len(graph_replacement_rows),
        "graph_replacement_reaction_counts": dict(
            sorted(
                Counter(str(row["source_reaction_idx"]) for row in graph_replacement_rows).items(),
                key=lambda item: numeric_reaction_key(item[0]),
            )
        ),
        "selected_reaction_counts": dict(
            sorted(Counter(str(row["source_reaction_idx"]) for row in selected).items(), key=lambda item: numeric_reaction_key(item[0]))
        ),
    }
    return selected, audit


def assign_splits(
    rows: list[dict[str, Any]],
    *,
    train_ratio: float,
    valid_ratio: float,
    split_seed_value: str,
) -> list[dict[str, Any]]:
    if train_ratio <= 0 or valid_ratio <= 0:
        raise ValueError("train_ratio and valid_ratio must be positive")
    if train_ratio + valid_ratio >= 1:
        raise ValueError("train_ratio + valid_ratio must be less than 1")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["graph_hash"])].append(row)

    total = len(rows)
    train_target = round(total * train_ratio)
    valid_target = round(total * valid_ratio)
    split_sizes = {"train": 0, "valid": 0, "test": 0}
    assigned: list[dict[str, Any]] = []
    ordered_groups = sorted(groups.items(), key=lambda item: split_key(split_seed_value, item[0]))
    for _, group_rows in ordered_groups:
        if split_sizes["train"] < train_target:
            split = "train"
        elif split_sizes["valid"] < valid_target:
            split = "valid"
        else:
            split = "test"
        for row in sorted(group_rows, key=lambda item: item["record_id"]):
            assigned_row = {key: value for key, value in row.items() if not key.startswith("_")}
            assigned_row["split"] = split
            assigned.append(assigned_row)
        split_sizes[split] += len(group_rows)

    return sorted(assigned, key=lambda row: row["record_id"])


def write_split_files(output_dir: Path, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows_by_split: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
    for row in rows:
        rows_by_split[str(row["split"])].append(row)
    output_dir.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        write_jsonl(output_dir / f"{split}.jsonl", rows_by_split[split])
    return rows_by_split


def build_manifest(
    *,
    input_path: Path,
    current_dataset_dir: Path,
    output_dir: Path,
    generated_at: str,
    reaction_counts: Counter[str],
    quotas: dict[str, int],
    rows: list[dict[str, Any]],
    rows_by_split: dict[str, list[dict[str, Any]]],
    audit: dict[str, Any],
    target_count: int,
    floor_per_reaction: int,
    train_ratio: float,
    valid_ratio: float,
    sample_seed: str,
    split_seed_value: str,
    current_hash_count: int,
    max_source_rows: int | None,
) -> dict[str, Any]:
    return {
        "dataset_name": OMG_V3_DATASET_NAME,
        "generated_at_utc": generated_at,
        "source": {
            "omg_csv": display_path(input_path),
            "omg_csv_sha256": sha256_file(input_path),
            "current_dataset_dir": display_path(current_dataset_dir),
            "current_dataset_canonical_hash_count": current_hash_count,
            "max_source_rows": max_source_rows,
        },
        "selection": {
            "target_count": target_count,
            "floor_per_reaction": floor_per_reaction,
            "sample_seed": sample_seed,
            "raw_reaction_counts": dict(sorted(reaction_counts.items(), key=lambda item: numeric_reaction_key(item[0]))),
            "target_reaction_quotas": quotas,
            "selected_reaction_counts": audit["selected_reaction_counts"],
        },
        "split": {
            "unit": "graph_hash",
            "seed": split_seed_value,
            "target_ratios": {
                "train": train_ratio,
                "valid": valid_ratio,
                "test": 1.0 - train_ratio - valid_ratio,
            },
            "counts": {split: len(rows_by_split[split]) for split in SPLITS},
        },
        "quality_checks": {
            "total_records": len(rows),
            "unique_record_id": len({row["record_id"] for row in rows}),
            "unique_canonical_hash": len({row["canonical_hash"] for row in rows}),
            "unique_graph_hash": len({row["graph_hash"] for row in rows}),
            "canonical_hash_leakage": leakage_report(rows, "canonical_hash"),
            "graph_hash_leakage": leakage_report(rows, "graph_hash"),
            "current_dataset_overlap_by_canonical_hash": 0,
        },
        "audit": audit,
        "outputs": {
            **{split: display_path(output_dir / f"{split}.jsonl") for split in SPLITS},
            "dataset_manifest": display_path(output_dir / "dataset_manifest.json"),
            "split_report": display_path(output_dir / "split_report.md"),
        },
    }


def write_split_report(path: Path, manifest: dict[str, Any]) -> None:
    quality = manifest["quality_checks"]
    lines = [
        "# BaseLite OMG v3 Dataset Split Report",
        "",
        f"- generated_at_utc: `{manifest['generated_at_utc']}`",
        f"- source OMG CSV: `{manifest['source']['omg_csv']}`",
        f"- dataset name: `{manifest['dataset_name']}`",
        f"- target count: `{manifest['selection']['target_count']}`",
        f"- floor per reaction: `{manifest['selection']['floor_per_reaction']}`",
        f"- split unit: `{manifest['split']['unit']}`",
        f"- split counts: `{manifest['split']['counts']}`",
        "",
        "## Quality Checks",
        "",
        f"- total records: `{quality['total_records']}`",
        f"- unique record_id: `{quality['unique_record_id']}`",
        f"- unique canonical_hash: `{quality['unique_canonical_hash']}`",
        f"- unique graph_hash: `{quality['unique_graph_hash']}`",
        f"- canonical hash leakage: `{quality['canonical_hash_leakage']['total_pairwise_leakage']}`",
        f"- graph hash leakage: `{quality['graph_hash_leakage']['total_pairwise_leakage']}`",
        f"- current dataset overlap by canonical_hash: `{quality['current_dataset_overlap_by_canonical_hash']}`",
        "",
        "## Reaction Counts",
        "",
    ]
    for reaction_idx, count in manifest["selection"]["selected_reaction_counts"].items():
        quota = manifest["selection"]["target_reaction_quotas"][reaction_idx]
        lines.append(f"- reaction_idx `{reaction_idx}`: selected `{count}`, quota `{quota}`")
    if manifest["audit"].get("quota_shortfalls_after_filtering"):
        lines.extend(
            [
                "",
                "## Quota Redistribution",
                "",
                f"- quota shortfalls after filtering: `{manifest['audit']['quota_shortfalls_after_filtering']}`",
                f"- replacement count: `{manifest['audit']['replacement_count']}`",
                f"- replacement reaction counts: `{manifest['audit']['replacement_reaction_counts']}`",
            ]
        )
    if manifest["audit"].get("graph_duplicate_drop_count"):
        lines.extend(
            [
                "",
                "## Graph Hash Deduplication",
                "",
                f"- graph duplicate drop count: `{manifest['audit']['graph_duplicate_drop_count']}`",
                f"- graph replacement count: `{manifest['audit']['graph_replacement_count']}`",
                f"- graph replacement reaction counts: `{manifest['audit']['graph_replacement_reaction_counts']}`",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assert_manifest_quality(manifest: dict[str, Any]) -> None:
    quality = manifest["quality_checks"]
    target_count = manifest["selection"]["target_count"]
    failures = {
        "total_records": quality["total_records"] != target_count,
        "unique_record_id": quality["unique_record_id"] != target_count,
        "unique_canonical_hash": quality["unique_canonical_hash"] != target_count,
        "unique_graph_hash": quality["unique_graph_hash"] != target_count,
        "canonical_hash_leakage": quality["canonical_hash_leakage"]["total_pairwise_leakage"] != 0,
        "graph_hash_leakage": quality["graph_hash_leakage"]["total_pairwise_leakage"] != 0,
        "current_dataset_overlap": quality["current_dataset_overlap_by_canonical_hash"] != 0,
    }
    failed = [name for name, failed_value in failures.items() if failed_value]
    if failed:
        raise SystemExit(f"OMG v3 dataset validation failed: {failed}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BaseLite OMG v3 canonical dataset.")
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to the source OMG_polymers.csv file.",
    )
    parser.add_argument("--current-dataset-dir", type=Path, default=DEFAULT_CURRENT_DATASET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-count", type=int, default=DEFAULT_TARGET_COUNT)
    parser.add_argument("--floor-per-reaction", type=int, default=DEFAULT_FLOOR_PER_REACTION)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--valid-ratio", type=float, default=0.1)
    parser.add_argument("--sample-seed", default=OMG_V3_SAMPLE_SEED)
    parser.add_argument("--split-seed", default=OMG_V3_SPLIT_SEED)
    parser.add_argument("--max-source-rows", type=int, default=None)
    parser.add_argument("--progress-every", type=int, default=1_000_000)
    parser.add_argument("--replacement-slack-per-reaction", type=int, default=2_000)
    parser.add_argument("--summary", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    Chem = require_rdkit()
    reaction_counts = count_reactions(
        args.input,
        max_source_rows=args.max_source_rows,
        progress_every=args.progress_every,
    )
    quotas = allocate_reaction_quotas(
        reaction_counts,
        target_count=args.target_count,
        floor_per_reaction=args.floor_per_reaction,
    )
    current_hashes = load_current_canonical_hashes(args.current_dataset_dir)
    selected_rows, audit = select_records(
        input_path=args.input,
        quotas=quotas,
        current_hashes=current_hashes,
        sample_seed=args.sample_seed,
        Chem=Chem,
        max_source_rows=args.max_source_rows,
        progress_every=args.progress_every,
        replacement_slack_per_reaction=args.replacement_slack_per_reaction,
    )
    assigned_rows = assign_splits(
        selected_rows,
        train_ratio=args.train_ratio,
        valid_ratio=args.valid_ratio,
        split_seed_value=args.split_seed,
    )
    rows_by_split = write_split_files(args.output_dir, assigned_rows)
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = build_manifest(
        input_path=args.input,
        current_dataset_dir=args.current_dataset_dir,
        output_dir=args.output_dir,
        generated_at=generated_at,
        reaction_counts=reaction_counts,
        quotas=quotas,
        rows=assigned_rows,
        rows_by_split=rows_by_split,
        audit=audit,
        target_count=args.target_count,
        floor_per_reaction=args.floor_per_reaction,
        train_ratio=args.train_ratio,
        valid_ratio=args.valid_ratio,
        sample_seed=args.sample_seed,
        split_seed_value=args.split_seed,
        current_hash_count=len(current_hashes),
        max_source_rows=args.max_source_rows,
    )
    write_json(args.output_dir / "dataset_manifest.json", manifest)
    write_split_report(args.output_dir / "split_report.md", manifest)
    assert_manifest_quality(manifest)
    if args.summary:
        print(
            json.dumps(
                {
                    "output_dir": str(args.output_dir),
                    "counts": manifest["split"]["counts"],
                    "selected_reaction_counts": manifest["selection"]["selected_reaction_counts"],
                    "quality_checks": manifest["quality_checks"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
