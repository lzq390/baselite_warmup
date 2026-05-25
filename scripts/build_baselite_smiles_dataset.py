from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "processed" / "canonical_repeat_units.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "baselite_smiles_v1"
DEFAULT_SEED = "baselite_smiles_v1_split_seed_2026_05_07"
SCHEMA_FIELDS = ["record_id", "canonical_smiles", "canonical_hash", "graph_hash", "split"]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            record_id = row.get("record_id")
            canonical_smiles = row.get("canonical_repeat_unit_string") or row.get("canonical_smiles")
            canonical_hash = row.get("canonical_hash")
            graph_hash = row.get("graph_hash") or canonical_hash
            if not record_id:
                raise ValueError(f"line {line_no}: missing record_id")
            if not canonical_smiles:
                raise ValueError(f"line {line_no}: missing canonical repeat-unit smiles")
            if not canonical_hash:
                canonical_hash = sha256_text(canonical_smiles)
            records.append(
                {
                    "record_id": str(record_id),
                    "canonical_smiles": str(canonical_smiles),
                    "canonical_hash": str(canonical_hash),
                    "graph_hash": str(graph_hash),
                }
            )
    return records


def stable_group_key(split_unit: str, seed: str) -> str:
    return sha256_text(f"{seed}:{split_unit}")


def assign_splits(
    records: list[dict[str, Any]],
    train_ratio: float,
    valid_ratio: float,
    seed: str,
    split_unit_field: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        split_unit = record.get(split_unit_field) or record["canonical_hash"]
        groups[str(split_unit)].append(record)

    ordered_groups = sorted(groups.items(), key=lambda item: stable_group_key(item[0], seed))
    total = len(records)
    train_target = round(total * train_ratio)
    valid_target = round(total * valid_ratio)

    split_counts = {"train": 0, "valid": 0, "test": 0}
    assigned: list[dict[str, Any]] = []
    for _, group in ordered_groups:
        if split_counts["train"] < train_target:
            split = "train"
        elif split_counts["valid"] < valid_target:
            split = "valid"
        else:
            split = "test"
        for record in sorted(group, key=lambda row: row["record_id"]):
            row = dict(record)
            row["split"] = split
            assigned.append(row)
        split_counts[split] += len(group)

    return sorted(assigned, key=lambda row: row["record_id"])


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def split_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_split = {"train": [], "valid": [], "test": []}
    for row in rows:
        by_split[row["split"]].append({field: row[field] for field in SCHEMA_FIELDS})
    return by_split


def leakage_report(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values_by_split: dict[str, set[str]] = {"train": set(), "valid": set(), "test": set()}
    for row in rows:
        values_by_split[row["split"]].add(str(row[field]))

    pairs = {
        "train_valid": values_by_split["train"] & values_by_split["valid"],
        "train_test": values_by_split["train"] & values_by_split["test"],
        "valid_test": values_by_split["valid"] & values_by_split["test"],
    }
    return {
        "field": field,
        "train_valid": len(pairs["train_valid"]),
        "train_test": len(pairs["train_test"]),
        "valid_test": len(pairs["valid_test"]),
        "total_pairwise_leakage": sum(len(values) for values in pairs.values()),
    }


def write_manifest(
    path: Path,
    *,
    input_path: Path,
    input_sha256: str,
    rows: list[dict[str, Any]],
    by_split: dict[str, list[dict[str, Any]]],
    train_ratio: float,
    valid_ratio: float,
    split_unit_field: str,
    seed: str,
    generated_at: str,
) -> None:
    manifest = {
        "dataset_name": "baselite_smiles_v1",
        "generated_at_utc": generated_at,
        "source": {
            "canonical_repeat_units_jsonl": str(input_path),
            "canonical_repeat_units_sha256": input_sha256,
        },
        "schema_fields": SCHEMA_FIELDS,
        "split": {
            "unit": split_unit_field,
            "seed": seed,
            "target_ratios": {
                "train": train_ratio,
                "valid": valid_ratio,
                "test": 1.0 - train_ratio - valid_ratio,
            },
            "counts": {name: len(items) for name, items in by_split.items()},
        },
        "quality_checks": {
            "total_records": len(rows),
            "unique_record_id": len({row["record_id"] for row in rows}),
            "unique_canonical_hash": len({row["canonical_hash"] for row in rows}),
            "unique_graph_hash": len({row["graph_hash"] for row in rows}),
            "canonical_hash_leakage": leakage_report(rows, "canonical_hash"),
            "graph_hash_leakage": leakage_report(rows, "graph_hash"),
        },
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_split_report(
    path: Path,
    *,
    input_path: Path,
    input_sha256: str,
    rows: list[dict[str, Any]],
    by_split: dict[str, list[dict[str, Any]]],
    split_unit_field: str,
    seed: str,
    generated_at: str,
) -> None:
    canonical_leakage = leakage_report(rows, "canonical_hash")
    graph_leakage = leakage_report(rows, "graph_hash")
    lines = [
        "# BaseLite SMILES v1 数据集划分报告",
        "",
        f"- 生成时间 UTC: `{generated_at}`",
        f"- 输入文件: `{input_path}`",
        f"- 输入文件 SHA256: `{input_sha256}`",
        f"- 划分单元: `{split_unit_field}`",
        f"- 划分种子: `{seed}`",
        f"- 字段 schema: `{', '.join(SCHEMA_FIELDS)}`",
        "",
        "## 数量统计",
        "",
        f"- 总记录数: `{len(rows)}`",
        f"- train: `{len(by_split['train'])}`",
        f"- valid: `{len(by_split['valid'])}`",
        f"- test: `{len(by_split['test'])}`",
        f"- 唯一 canonical_hash 数: `{len({row['canonical_hash'] for row in rows})}`",
        f"- 唯一 graph_hash 数: `{len({row['graph_hash'] for row in rows})}`",
        "",
        "## 泄漏检查",
        "",
        f"- canonical_hash 跨 split 成对泄漏数: `{canonical_leakage['total_pairwise_leakage']}`",
        f"- graph_hash 跨 split 成对泄漏数: `{graph_leakage['total_pairwise_leakage']}`",
        "",
        "## 输出文件",
        "",
        "- `train.jsonl`",
        "- `valid.jsonl`",
        "- `test.jsonl`",
        "- `dataset_manifest.json`",
        "- `dataset_card.md`",
        "- `split_report.md`",
        "",
        "## 说明",
        "",
        "- 本数据集是 SMILES-only 训练数据集。",
        "- 不包含性质字段。",
        "- 不包含 fragment 匹配字段。",
        "- 上游仅用于审计的合并来源计数不进入 train/valid/test JSONL。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_dataset_card(
    path: Path,
    *,
    rows: list[dict[str, Any]],
    by_split: dict[str, list[dict[str, Any]]],
    split_unit_field: str,
) -> None:
    lines = [
        "# BaseLite SMILES v1 数据集卡",
        "",
        "本数据集包用于 BaseLite SMILES-only 恢复训练 / warmup 训练。",
        "",
        "## 预期用途",
        "",
        "- 从 canonical repeat-unit SMILES 生成输入视图。",
        "- 训练模型从扰动视图恢复 canonical SMILES。",
        "- 支持 tokenizer 构建和序列长度分析。",
        "",
        "## 不包含内容",
        "",
        "- 性质标签。",
        "- fragment instances。",
        "- fragment presence labels。",
        "",
        "## 字段说明",
        "",
        "| 字段 | 含义 |",
        "|---|---|",
        "| `record_id` | 稳定的 repeat-unit 记录 ID。 |",
        "| `canonical_smiles` | RDKit canonical 后的 repeat-unit SMILES。 |",
        "| `canonical_hash` | canonical SMILES 的稳定哈希，用于追溯和去重检查。 |",
        "| `graph_hash` | 当前 graph signature hash，用于 split 分组和防泄漏检查。 |",
        "| `split` | 数据划分，取值为 train、valid 或 test。 |",
        "",
        "## 数量统计",
        "",
        f"- 总记录数: `{len(rows)}`",
        f"- train: `{len(by_split['train'])}`",
        f"- valid: `{len(by_split['valid'])}`",
        f"- test: `{len(by_split['test'])}`",
        f"- 划分单元: `{split_unit_field}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BaseLite SMILES-only split dataset.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--valid-ratio", type=float, default=0.1)
    parser.add_argument("--split-unit-field", choices=["graph_hash", "canonical_hash"], default="graph_hash")
    parser.add_argument("--seed", default=DEFAULT_SEED)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.train_ratio <= 0 or args.valid_ratio <= 0:
        raise ValueError("train and valid ratios must be positive")
    if args.train_ratio + args.valid_ratio >= 1:
        raise ValueError("train_ratio + valid_ratio must be less than 1")

    records = read_jsonl(args.input)
    assigned = assign_splits(
        records,
        train_ratio=args.train_ratio,
        valid_ratio=args.valid_ratio,
        seed=args.seed,
        split_unit_field=args.split_unit_field,
    )
    by_split = split_rows(assigned)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for split, rows in by_split.items():
        write_jsonl(args.output_dir / f"{split}.jsonl", rows)

    generated_at = datetime.now(timezone.utc).isoformat()
    input_sha256 = sha256_file(args.input)
    write_manifest(
        args.output_dir / "dataset_manifest.json",
        input_path=args.input,
        input_sha256=input_sha256,
        rows=assigned,
        by_split=by_split,
        train_ratio=args.train_ratio,
        valid_ratio=args.valid_ratio,
        split_unit_field=args.split_unit_field,
        seed=args.seed,
        generated_at=generated_at,
    )
    write_split_report(
        args.output_dir / "split_report.md",
        input_path=args.input,
        input_sha256=input_sha256,
        rows=assigned,
        by_split=by_split,
        split_unit_field=args.split_unit_field,
        seed=args.seed,
        generated_at=generated_at,
    )
    write_dataset_card(
        args.output_dir / "dataset_card.md",
        rows=assigned,
        by_split=by_split,
        split_unit_field=args.split_unit_field,
    )

    print(json.dumps({"output_dir": str(args.output_dir), "counts": {k: len(v) for k, v in by_split.items()}}, indent=2))


if __name__ == "__main__":
    main()
