from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_DIR = ROOT / "data" / "baselite_smiles_v1"
DEFAULT_TOKENIZER_DIR = ROOT / "models" / "qwen2.5-7b-tokenizer"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if "canonical_smiles" not in row:
                raise ValueError(f"{path}:{line_no}: missing canonical_smiles")
            rows.append(row)
    return rows


def percentile(sorted_values: list[int], p: float) -> int:
    if not sorted_values:
        return 0
    idx = round((len(sorted_values) - 1) * p)
    return sorted_values[idx]


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


def recommended_max_seq_len(max_len: int) -> int:
    if max_len <= 128:
        return 128
    if max_len <= 256:
        return 256
    if max_len <= 512:
        return 512
    if max_len <= 1024:
        return 1024
    return 2048


def analyze_split(tokenizer: Any, split: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    token_lengths: list[int] = []
    char_lengths: list[int] = []
    token_counter: Counter[str] = Counter()
    roundtrip_failures: list[dict[str, Any]] = []
    longest: list[tuple[int, dict[str, Any], list[str]]] = []
    critical_char_rows: Counter[str] = Counter()

    for row in rows:
        smiles = row["canonical_smiles"]
        token_ids = tokenizer.encode(smiles, add_special_tokens=False)
        tokens = tokenizer.convert_ids_to_tokens(token_ids)
        decoded = tokenizer.decode(token_ids, skip_special_tokens=False)

        token_lengths.append(len(token_ids))
        char_lengths.append(len(smiles))
        token_counter.update(tokens)
        longest.append((len(token_ids), row, tokens[:120]))

        for char in ["*", "/", "\\", "[", "]", "%"]:
            if char in smiles:
                critical_char_rows[char] += 1

        if decoded != smiles and len(roundtrip_failures) < 20:
            roundtrip_failures.append(
                {
                    "record_id": row.get("record_id"),
                    "smiles": smiles,
                    "decoded": decoded,
                    "tokens": tokens[:120],
                }
            )

    longest.sort(key=lambda item: (-item[0], item[1].get("record_id", "")))
    max_len = max(token_lengths) if token_lengths else 0
    return {
        "split": split,
        "sample_count": len(rows),
        "token_length": length_stats(token_lengths),
        "char_length": length_stats(char_lengths),
        "recommended_max_seq_len_for_raw_smiles": recommended_max_seq_len(max_len),
        "roundtrip_failure_count": sum(
            1
            for row in rows
            if tokenizer.decode(tokenizer.encode(row["canonical_smiles"], add_special_tokens=False), skip_special_tokens=False)
            != row["canonical_smiles"]
        ),
        "roundtrip_failure_examples": roundtrip_failures,
        "critical_char_row_counts": dict(sorted(critical_char_rows.items())),
        "top_tokens": token_counter.most_common(50),
        "longest_examples": [
            {
                "record_id": row.get("record_id"),
                "split": split,
                "token_length": length,
                "char_length": len(row["canonical_smiles"]),
                "canonical_smiles": row["canonical_smiles"],
                "tokens_head": tokens,
            }
            for length, row, tokens in longest[:10]
        ],
    }


def write_corpus(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(row["canonical_smiles"] + "\n")


def write_report(path: Path, stats: dict[str, Any]) -> None:
    splits = stats["splits"]
    total_failures = sum(row["roundtrip_failure_count"] for row in splits.values())
    max_recommendation = max(row["recommended_max_seq_len_for_raw_smiles"] for row in splits.values())
    lines = [
        "# Qwen2.5-7B tokenizer 统计报告",
        "",
        f"- tokenizer 路径: `{stats['tokenizer']['path']}`",
        f"- vocab size: `{stats['tokenizer']['vocab_size']}`",
        f"- is_fast: `{stats['tokenizer']['is_fast']}`",
        f"- pad token: `{stats['tokenizer']['pad_token']}`",
        f"- eos token: `{stats['tokenizer']['eos_token']}`",
        f"- unk token: `{stats['tokenizer']['unk_token']}`",
        f"- corpus 文件: `{stats['outputs']['tokenizer_corpus']}`",
        "",
        "## 结论",
        "",
        f"- train/valid/test 总 round-trip 失败数: `{total_failures}`",
        f"- raw SMILES 推荐 `max_seq_len`: `{max_recommendation}`",
        "- 本统计只针对 raw `canonical_smiles`，尚未把训练 prompt 模板拼接进去。",
        "",
        "## 各 split 长度统计",
        "",
        "| split | count | token p50 | token p90 | token p95 | token p99 | token max | char max | 推荐 max_seq_len |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for split in ["train", "valid", "test"]:
        row = splits[split]
        token = row["token_length"]
        char = row["char_length"]
        lines.append(
            f"| {split} | {row['sample_count']} | {token['p50']} | {token['p90']} | {token['p95']} | "
            f"{token['p99']} | {token['max']} | {char['max']} | {row['recommended_max_seq_len_for_raw_smiles']} |"
        )

    lines.extend(["", "## 特殊字符覆盖", ""])
    for split in ["train", "valid", "test"]:
        lines.append(f"### {split}")
        for char, count in splits[split]["critical_char_row_counts"].items():
            rendered = "\\\\" if char == "\\" else char
            lines.append(f"- `{rendered}`: `{count}`")
        lines.append("")

    lines.extend(["## 最长样本", ""])
    for split in ["train", "valid", "test"]:
        example = splits[split]["longest_examples"][0]
        lines.append(
            f"- {split}: `{example['record_id']}`，token length `{example['token_length']}`，"
            f"char length `{example['char_length']}`"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build tokenizer corpus and stats for Qwen2.5-7B on BaseLite SMILES v1.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--tokenizer-dir", type=Path, default=DEFAULT_TOKENIZER_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_dir, local_files_only=True, use_fast=True)

    rows_by_split = {
        split: read_jsonl(args.dataset_dir / f"{split}.jsonl")
        for split in ["train", "valid", "test"]
    }

    corpus_path = args.dataset_dir / "tokenizer_corpus.txt"
    stats_path = args.dataset_dir / "token_stats.json"
    report_path = args.dataset_dir / "tokenizer_report.md"
    write_corpus(corpus_path, rows_by_split["train"])

    stats = {
        "tokenizer": {
            "path": str(args.tokenizer_dir),
            "is_fast": getattr(tokenizer, "is_fast", None),
            "vocab_size": len(tokenizer),
            "model_max_length": tokenizer.model_max_length,
            "pad_token": tokenizer.pad_token,
            "pad_token_id": tokenizer.pad_token_id,
            "eos_token": tokenizer.eos_token,
            "eos_token_id": tokenizer.eos_token_id,
            "bos_token": tokenizer.bos_token,
            "bos_token_id": tokenizer.bos_token_id,
            "unk_token": tokenizer.unk_token,
            "unk_token_id": tokenizer.unk_token_id,
            "special_tokens_map": tokenizer.special_tokens_map,
        },
        "dataset": {
            split: len(rows)
            for split, rows in rows_by_split.items()
        },
        "outputs": {
            "tokenizer_corpus": str(corpus_path),
            "token_stats": str(stats_path),
            "tokenizer_report": str(report_path),
        },
        "splits": {
            split: analyze_split(tokenizer, split, rows)
            for split, rows in rows_by_split.items()
        },
    }
    stats["overall"] = {
        "sample_count": sum(stats["dataset"].values()),
        "roundtrip_failure_count": sum(row["roundtrip_failure_count"] for row in stats["splits"].values()),
        "recommended_max_seq_len_for_raw_smiles": max(
            row["recommended_max_seq_len_for_raw_smiles"] for row in stats["splits"].values()
        ),
    }

    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report(report_path, stats)
    print(
        json.dumps(
            {
                "tokenizer_corpus": str(corpus_path),
                "token_stats": str(stats_path),
                "tokenizer_report": str(report_path),
                "overall": stats["overall"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
