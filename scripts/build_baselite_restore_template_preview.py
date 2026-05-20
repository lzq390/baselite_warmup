from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_DIR = ROOT / "data" / "baselite_smiles_v1"
DEFAULT_TOKENIZER_DIR = ROOT / "models" / "qwen2.5-7b-tokenizer"
DEFAULT_SPLITS = ("train", "valid", "test")


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


def build_preview_record(row: dict[str, Any], tokenizer: Any) -> dict[str, Any]:
    canonical_smiles = str(row["canonical_smiles"])
    text_view_1 = canonical_smiles
    canonical_text_target = canonical_smiles
    input_text_view1 = build_input_text_view1(text_view_1)
    target_text = canonical_text_target + tokenizer.eos_token

    input_ids_view1 = tokenizer.encode(input_text_view1, add_special_tokens=False)
    restore_labels = tokenizer.encode(target_text, add_special_tokens=False)

    return {
        "record_id": str(row["record_id"]),
        "split": str(row["split"]),
        "canonical_smiles": canonical_smiles,
        "canonical_hash": str(row["canonical_hash"]),
        "graph_hash": str(row["graph_hash"]),
        "text_view_1_strategy": "identity",
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
    view_roundtrip_failures = [
        row
        for row in all_rows
        if not decode_equals(tokenizer, row["input_ids_view1"], row["input_text_view1"])
    ]
    restore_roundtrip_failures = [
        row
        for row in all_rows
        if not decode_equals(tokenizer, row["restore_labels"], row["target_text"])
    ]
    view_overflows = [row for row in all_rows if row["view1_token_length"] > max_seq_len_view]
    restore_overflows = [row for row in all_rows if row["restore_label_length"] > max_seq_len_restore_label]
    mask_failures = [
        row
        for row in all_rows
        if len(row["attention_mask_view1"]) != len(row["input_ids_view1"])
        or len(row["restore_label_mask"]) != len(row["restore_labels"])
        or any(value != 1 for value in row["attention_mask_view1"])
        or any(value is not True for value in row["restore_label_mask"])
    ]

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
        "splits": {
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
        },
        "quality_checks": {
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


def assert_quality(stats: dict[str, Any]) -> None:
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
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--max-seq-len-view", type=int, default=512)
    parser.add_argument("--max-seq-len-restore-label", type=int, default=512)
    parser.add_argument("--summary", action="store_true")
    return parser.parse_args()


def main() -> None:
    from transformers import AutoTokenizer

    args = parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_dir, local_files_only=True, use_fast=True)
    if not tokenizer.eos_token:
        raise ValueError("tokenizer must define eos_token")

    preview_rows, rows_by_split = build_preview_rows(args.dataset_dir, tokenizer)
    stats = build_stats(
        rows_by_split,
        tokenizer,
        tokenizer_dir=args.tokenizer_dir,
        dataset_dir=args.dataset_dir,
        output_dir=args.output_dir,
        max_seq_len_view=args.max_seq_len_view,
        max_seq_len_restore_label=args.max_seq_len_restore_label,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "training_template_preview.jsonl", preview_rows)
    (args.output_dir / "training_template_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(args.output_dir / "training_template_report.md", stats)
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
