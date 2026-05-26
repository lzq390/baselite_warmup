from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = ROOT / ".codex_py_deps"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))

from rdkit import rdBase

from build_fragment_vocab_v1 import (
    DATA_FILE,
    PROCESSED_DIR,
    canonicalize_main_records,
    classify_record,
    normalize_attachment_text,
    read_property_records,
    sha256_file,
)


OUTPUT_CSV = PROCESSED_DIR / "unique_standardized_smiles.csv"
OUTPUT_REPORT = PROCESSED_DIR / "unique_standardized_smiles_report.md"


def csv_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    source_hash = sha256_file(DATA_FILE)
    rows, grouped = read_property_records(DATA_FILE)
    clean_rows, canonical_records, failed_cases, audit = canonicalize_main_records(grouped)

    raw_smiles = [(row.get("smiles") or "").strip() for row in rows]
    raw_unique = sorted(grouped)
    row_star_dist = Counter(s.count("*") for s in raw_smiles)
    unique_star_dist = Counter(s.count("*") for s in raw_unique)

    output_rows = []
    for rec in canonical_records:
        output_rows.append(
            {
                "canonical_id": rec.record_id,
                "standardized_smiles": rec.canonical_smiles,
                "canonical_hash": rec.canonical_hash,
                "graph_hash": rec.graph_hash,
                "source_level2_count": rec.source_count,
                "attachment_normalized_smiles_examples": csv_json(rec.normalized_smiles_examples),
                "raw_smiles_examples": csv_json(rec.raw_smiles_examples),
            }
        )

    standardized_smiles = [row["standardized_smiles"] for row in output_rows]
    duplicate_standardized_smiles = [
        smiles for smiles, count in Counter(standardized_smiles).items() if count > 1
    ]

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "canonical_id",
                "standardized_smiles",
                "canonical_hash",
                "graph_hash",
                "source_level2_count",
                "attachment_normalized_smiles_examples",
                "raw_smiles_examples",
            ],
        )
        writer.writeheader()
        writer.writerows(output_rows)

    existing_jsonl = PROCESSED_DIR / "canonical_repeat_units.jsonl"
    existing_count = None
    existing_same_set = None
    if existing_jsonl.exists():
        existing_smiles = []
        with existing_jsonl.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                existing_smiles.append(json.loads(line)["canonical_repeat_unit_string"])
        existing_count = len(existing_smiles)
        existing_same_set = set(existing_smiles) == set(standardized_smiles)

    generated_at = datetime.now(timezone.utc).isoformat()
    non_main_count = audit["level_1_raw_unique"] - audit["level_1_raw_two_attachment_main_after_text_exclusions"]
    level2_collapsed_count = (
        audit["level_1_raw_two_attachment_main_after_text_exclusions"]
        - audit["level_2_attachment_normalized_main_unique"]
    )
    level3_collapsed_count = (
        audit["level_2_attachment_normalized_main_unique"]
        - audit["level_3_canonical_repeat_unit_unique"]
    )

    report = [
        "# 唯一标准化 SMILES 导出报告",
        "",
        f"- 生成时间 UTC: `{generated_at}`",
        f"- 源文件: `{DATA_FILE}`",
        f"- 源文件 SHA256: `{source_hash}`",
        f"- RDKit 版本: `{rdBase.rdkitVersion}`",
        f"- 输出 CSV: `{OUTPUT_CSV}`",
        "",
        "## 结论",
        "",
        f"- 已导出标准化 SMILES 数量: `{len(output_rows)}`",
        f"- 导出 CSV 中唯一 `standardized_smiles` 数量: `{len(set(standardized_smiles))}`",
        f"- 是否存在重复标准化 SMILES: `{bool(duplicate_standardized_smiles)}`",
        f"- 与既有 `canonical_repeat_units.jsonl` 数量是否一致: `{existing_count == len(output_rows) if existing_count is not None else '未检查'}`",
        f"- 与既有 `canonical_repeat_units.jsonl` SMILES 集合是否一致: `{existing_same_set if existing_same_set is not None else '未检查'}`",
        "",
        "## 标准化过程",
        "",
        "1. 读取原始 CSV，并按 raw `smiles` 字符串聚合 long-format 属性记录。",
        "2. 对 raw unique string 做 record type 分类，只保留恰好两个 attachment point 且不含多组分、共聚物拼接和未定义 R 基的主构建样本。",
        "3. 执行 attachment 文本统一：`[[[*]]] -> *`、`[[*]] -> *`、`[*] -> *`、`[*:1] -> *`、`[*:2] -> *`，以及通用 `[*:n] -> *`。",
        "4. 对 attachment-normalized 主构建 unique SMILES 使用 RDKit `MolFromSmiles` 解析。",
        "5. 使用 RDKit `MolToSmiles(..., canonical=True, isomericSmiles=True)` 生成 canonical repeat-unit string。",
        "6. 按 canonical repeat-unit string 去重，得到最终唯一标准化 SMILES。",
        "",
        "## 数量链路",
        "",
        f"- CSV 总行数: `{len(rows)}`",
        f"- raw unique polymer strings: `{audit['level_1_raw_unique']}`",
        f"- 非主构建 raw unique 数量: `{non_main_count}`",
        f"- 两连接点 main repeat-unit raw candidates: `{audit['level_1_raw_two_attachment_main_after_text_exclusions']}`",
        f"- attachment-normalized main unique: `{audit['level_2_attachment_normalized_main_unique']}`",
        f"- attachment normalization 合并数量: `{level2_collapsed_count}`",
        f"- RDKit canonical repeat-unit unique: `{audit['level_3_canonical_repeat_unit_unique']}`",
        f"- RDKit canonicalization 合并数量: `{level3_collapsed_count}`",
        f"- RDKit 解析失败数量: `{audit['parser_failed_count']}`",
        "",
        "## raw `*` 数量分布",
        "",
        "### CSV 行级分布",
        "",
    ]
    for star_count, count in sorted(row_star_dist.items()):
        report.append(f"- `{star_count}` 个 `*`: `{count}` 行")
    report.extend(["", "### raw unique 分布", ""])
    for star_count, count in sorted(unique_star_dist.items()):
        report.append(f"- `{star_count}` 个 `*`: `{count}` 个 raw unique")

    report.extend(["", "## record type 统计", ""])
    for record_type, count in sorted(audit["record_type_counts_raw_unique"].items()):
        report.append(f"- `{record_type}`: `{count}`")

    report.extend(
        [
            "",
            "## 输出 CSV 字段",
            "",
            "- `canonical_id`: 当前导出中的稳定行 ID。",
            "- `standardized_smiles`: RDKit canonical 后的唯一标准化 repeat-unit SMILES。",
            "- `canonical_hash`: `standardized_smiles` 的 SHA256。",
            "- `graph_hash`: 当前脚本生成的单 repeat-unit graph signature hash，只作 split 防泄漏参考，不等同于严格 graph isomorphism hash。",
            "- `source_level2_count`: 合并到该 canonical SMILES 的 attachment-normalized unique 数量，仅用于追踪去重来源；不写入当前 BaseLite train/valid/test JSONL。",
            "- `attachment_normalized_smiles_examples`: 该 canonical SMILES 对应的 level 2 示例。",
            "- `raw_smiles_examples`: 该 canonical SMILES 对应的原始 SMILES 示例。",
        ]
    )

    if duplicate_standardized_smiles:
        report.extend(["", "## 重复标准化 SMILES 示例", ""])
        for smiles in duplicate_standardized_smiles[:20]:
            report.append(f"- `{smiles}`")

    if failed_cases:
        report.extend(["", "## failed cases 摘要", ""])
        by_stage = Counter(row["stage"] for row in failed_cases)
        for stage, count in sorted(by_stage.items()):
            report.append(f"- `{stage}`: `{count}`")

    OUTPUT_REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "output_csv": str(OUTPUT_CSV),
                "output_report": str(OUTPUT_REPORT),
                "standardized_smiles_count": len(output_rows),
                "unique_standardized_smiles_count": len(set(standardized_smiles)),
                "duplicates": len(duplicate_standardized_smiles),
                "existing_jsonl_count": existing_count,
                "existing_jsonl_same_set": existing_same_set,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
