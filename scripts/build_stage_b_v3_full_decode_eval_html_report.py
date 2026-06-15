from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_INPUT_DIR = Path("reports/stage_b_restore_aug_v3_full_decode_eval_remote")
DEFAULT_OUTPUT = Path("reports/stage_b_restore_aug_v3_full_decode_eval_report.html")

DATASETS = {
    "v2": {
        "label": "V2 curated test",
        "description": "当前 v3 checkpoint 在历史 curated/V2 test 模板上的迁移评估。",
        "dir": Path("v2_test") / "v3_epoch001",
    },
    "v3": {
        "label": "V3 OMG test",
        "description": "当前 v3 checkpoint 在 OMG v3 full 五视图 test 模板上的分布内泛化评估。",
        "dir": Path("v3_test") / "v3_epoch001",
    },
}

STRATEGY_ORDER = [
    "identity",
    "rdkit_random_smiles",
    "direction_flip",
    "attachment_rooted_smiles",
    "light_denoise",
]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pct(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.{digits}f}%"


def num(value: float | int | None, digits: int = 5) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return f"{value:,}"
    return f"{float(value):.{digits}f}"


def size_text(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def short_text(value: Any, limit: int = 150) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def metric_bar(value: float | None, *, label: str | None = None) -> str:
    if value is None:
        return "-"
    width = max(0.0, min(100.0, value * 100.0))
    text = label if label is not None else pct(value)
    return f"<div class=\"bar\"><span style=\"width:{width:.2f}%\"></span></div><div class=\"bar-label\">{esc(text)}</div>"


def table(headers: list[str], rows: list[list[Any]], *, class_name: str = "") -> str:
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    return f"<table class=\"{esc(class_name)}\"><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def failure_category(row: dict[str, Any]) -> str:
    if row.get("canonical_match"):
        return "correct"
    if not row.get("rdkit_valid"):
        return "invalid_smiles"
    if not row.get("two_attachment_valid"):
        return "attachment_error"
    return "valid_two_attachment_wrong_canonical"


def display_category(category: str) -> str:
    return {
        "correct": "正确",
        "invalid_smiles": "RDKit 无法解析",
        "attachment_error": "attachment 数错误",
        "valid_two_attachment_wrong_canonical": "合法但 canonical 错误",
    }.get(category, category)


def load_dataset(input_dir: Path, key: str) -> dict[str, Any]:
    dataset_info = DATASETS[key]
    dataset_dir = input_dir / dataset_info["dir"]
    metrics = read_json(dataset_dir / "test_eval_metrics.json")
    prediction_path = dataset_dir / "test_predictions.jsonl"
    failed_path = dataset_dir / "test_failed_cases.jsonl"

    strategy_counts: dict[str, Counter[str]] = defaultdict(Counter)
    strategy_categories: dict[str, Counter[str]] = defaultdict(Counter)
    global_categories: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sample_success: dict[str, list[dict[str, Any]]] = defaultdict(list)
    decoded_rows = 0

    for row in iter_jsonl(prediction_path):
        decoded_rows += 1
        strategy = str(row.get("augmentation_strategy") or row.get("text_view_1_strategy") or "unknown")
        category = failure_category(row)
        counter = strategy_counts[strategy]
        counter["total"] += 1
        counter["canonical"] += int(bool(row.get("canonical_match")))
        counter["exact"] += int(bool(row.get("exact_string_match")))
        counter["rdkit"] += int(bool(row.get("rdkit_valid")))
        counter["two_attachment"] += int(bool(row.get("two_attachment_valid")))
        strategy_categories[strategy][category] += 1
        global_categories[category] += 1
        if category != "correct" and len(examples[strategy]) < 4:
            examples[strategy].append(row)
        if category == "correct" and len(sample_success[strategy]) < 1:
            sample_success[strategy].append(row)

    failed_rows = sum(1 for _ in iter_jsonl(failed_path)) if failed_path.exists() else 0
    return {
        "key": key,
        "label": dataset_info["label"],
        "description": dataset_info["description"],
        "dataset_dir": dataset_dir,
        "metrics": metrics,
        "decoded_rows": decoded_rows,
        "failed_rows": failed_rows,
        "strategy_counts": strategy_counts,
        "strategy_categories": strategy_categories,
        "global_categories": global_categories,
        "examples": examples,
        "sample_success": sample_success,
        "files": {
            "metrics": dataset_dir / "test_eval_metrics.json",
            "predictions": prediction_path,
            "failed_cases": failed_path,
            "report": dataset_dir / "test_eval_report.md",
        },
    }


def strategy_sort_key(strategy: str) -> tuple[int, str]:
    try:
        return (STRATEGY_ORDER.index(strategy), strategy)
    except ValueError:
        return (len(STRATEGY_ORDER), strategy)


def strategy_metric_rows(dataset: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for strategy in sorted(dataset["strategy_counts"], key=strategy_sort_key):
        counts = dataset["strategy_counts"][strategy]
        total = counts["total"]
        canonical = counts["canonical"] / total if total else 0.0
        exact = counts["exact"] / total if total else 0.0
        rdkit = counts["rdkit"] / total if total else 0.0
        two = counts["two_attachment"] / total if total else 0.0
        rows.append(
            [
                f"<strong>{esc(strategy)}</strong>",
                f"{total:,}",
                metric_bar(canonical),
                pct(exact),
                pct(rdkit),
                pct(two),
                f"{total - counts['canonical']:,}",
            ]
        )
    return rows


def strategy_failure_rows(dataset: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for strategy in sorted(dataset["strategy_counts"], key=strategy_sort_key):
        total = dataset["strategy_counts"][strategy]["total"]
        cats = dataset["strategy_categories"][strategy]
        failed = total - cats["correct"]
        rows.append(
            [
                f"<strong>{esc(strategy)}</strong>",
                f"{failed:,}",
                f"{cats['invalid_smiles']:,}",
                f"{cats['attachment_error']:,}",
                f"{cats['valid_two_attachment_wrong_canonical']:,}",
                pct(failed / total if total else 0.0),
            ]
        )
    return rows


def summary_rows(datasets: dict[str, dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for key in ("v2", "v3"):
        dataset = datasets[key]
        metrics = dataset["metrics"]
        rows.append(
            [
                f"<strong>{esc(dataset['label'])}</strong><div class=\"muted\">{esc(dataset['description'])}</div>",
                f"{int(metrics.get('decoded_sample_count') or 0):,}",
                num(metrics.get("loss")),
                pct(metrics.get("token_accuracy"), 3),
                metric_bar(float(metrics.get("canonical_match") or 0.0)),
                pct(metrics.get("exact_string_match")),
                pct(metrics.get("rdkit_validity")),
                pct(metrics.get("two_attachment_validity")),
            ]
        )
    return rows


def category_rows(datasets: dict[str, dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for key in ("v2", "v3"):
        dataset = datasets[key]
        total = dataset["decoded_rows"]
        cats = dataset["global_categories"]
        rows.append(
            [
                esc(dataset["label"]),
                f"{cats['correct']:,}<div class=\"muted\">{pct(cats['correct'] / total if total else 0.0)}</div>",
                f"{cats['valid_two_attachment_wrong_canonical']:,}<div class=\"muted\">{pct(cats['valid_two_attachment_wrong_canonical'] / total if total else 0.0)}</div>",
                f"{cats['invalid_smiles']:,}<div class=\"muted\">{pct(cats['invalid_smiles'] / total if total else 0.0)}</div>",
                f"{cats['attachment_error']:,}<div class=\"muted\">{pct(cats['attachment_error'] / total if total else 0.0)}</div>",
            ]
        )
    return rows


def example_rows(dataset: dict[str, Any], strategy: str, *, limit: int = 4) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in dataset["examples"].get(strategy, [])[:limit]:
        category = failure_category(row)
        rows.append(
            [
                esc(row.get("record_id")),
                esc(display_category(category)),
                f"<code>{esc(short_text(row.get('text_view_1'), 150))}</code>",
                f"<code>{esc(short_text(row.get('target'), 150))}</code>",
                f"<code>{esc(short_text(row.get('decoded_smiles'), 150))}</code>",
            ]
        )
    if not rows:
        rows.append(["-", "无失败样例", "-", "-", "-"])
    return rows


def per_strategy_sections(datasets: dict[str, dict[str, Any]]) -> str:
    sections: list[str] = []
    all_strategies = sorted(
        set().union(*(dataset["strategy_counts"].keys() for dataset in datasets.values())),
        key=strategy_sort_key,
    )
    for strategy in all_strategies:
        compare_rows = []
        for key in ("v2", "v3"):
            dataset = datasets[key]
            counts = dataset["strategy_counts"].get(strategy, Counter())
            total = counts["total"]
            if not total:
                compare_rows.append([esc(dataset["label"]), "-", "-", "-", "-", "-", "-"])
                continue
            cats = dataset["strategy_categories"][strategy]
            compare_rows.append(
                [
                    esc(dataset["label"]),
                    f"{total:,}",
                    metric_bar(counts["canonical"] / total),
                    pct(counts["rdkit"] / total),
                    pct(counts["two_attachment"] / total),
                    f"{cats['invalid_smiles']:,}",
                    f"{cats['valid_two_attachment_wrong_canonical']:,}",
                ]
            )
        sections.append(
            f"""
            <section class="strategy-detail">
              <h3>{esc(strategy)}</h3>
              {table(["eval set", "rows", "canonical", "RDKit valid", "two attachment", "invalid", "valid wrong"], compare_rows)}
              <div class="two-col">
                <div>
                  <h4>V2 失败样例</h4>
                  {table(["record_id", "类型", "input view", "target", "decoded"], example_rows(datasets["v2"], strategy))}
                </div>
                <div>
                  <h4>V3 失败样例</h4>
                  {table(["record_id", "类型", "input view", "target", "decoded"], example_rows(datasets["v3"], strategy))}
                </div>
              </div>
            </section>
            """
        )
    return "\n".join(sections)


def file_rows(input_dir: Path) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for path in sorted(input_dir.rglob("*")):
        if path.is_file():
            rows.append([f"<code>{esc(path.relative_to(input_dir))}</code>", size_text(path.stat().st_size)])
    return rows


def build_report(input_dir: Path, output_path: Path) -> None:
    datasets = {key: load_dataset(input_dir, key) for key in DATASETS}
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    v2 = datasets["v2"]["metrics"]
    v3 = datasets["v3"]["metrics"]
    canonical_gap = float(v3["canonical_match"]) - float(v2["canonical_match"])
    rdkit_gap = float(v3["rdkit_validity"]) - float(v2["rdkit_validity"])

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Stage B v3 Checkpoint 全量 Test Decode 报告</title>
  <style>
    body {{ margin: 0; background: #f5f7fb; color: #172033; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", Arial, sans-serif; }}
    main {{ max-width: 1320px; margin: 0 auto; padding: 34px 30px 60px; }}
    h1 {{ margin: 0 0 8px; font-size: 31px; letter-spacing: 0; }}
    h2 {{ margin: 34px 0 14px; padding-left: 11px; border-left: 4px solid #2563eb; font-size: 22px; }}
    h3 {{ margin: 24px 0 10px; font-size: 18px; }}
    h4 {{ margin: 18px 0 8px; font-size: 15px; }}
    p, li {{ line-height: 1.65; }}
    code {{ font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; word-break: break-all; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d9deea; margin: 12px 0 22px; }}
    th, td {{ border-bottom: 1px solid #e7eaf2; padding: 9px 10px; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #edf2f9; color: #2b3447; font-weight: 700; }}
    tr:last-child td {{ border-bottom: 0; }}
    .muted {{ color: #687386; font-size: 12px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 18px 0; }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    .card {{ background: #fff; border: 1px solid #d9deea; border-radius: 8px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
    .card .k {{ color: #687386; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }}
    .card .v {{ margin-top: 6px; font-size: 24px; font-weight: 750; }}
    .callout {{ background: #fff; border-left: 4px solid #22a06b; padding: 14px 16px; margin: 14px 0; border-radius: 6px; }}
    .warnbox {{ background: #fff; border-left: 4px solid #d97706; padding: 14px 16px; margin: 14px 0; border-radius: 6px; }}
    .bar {{ height: 8px; width: 130px; background: #e8edf5; border-radius: 999px; overflow: hidden; margin-bottom: 3px; }}
    .bar span {{ display: block; height: 100%; background: linear-gradient(90deg, #2563eb, #16a34a); }}
    .bar-label {{ font-size: 12px; color: #2b3447; }}
    .strategy-detail {{ margin-top: 22px; padding-top: 2px; }}
    .ok {{ color: #157347; font-weight: 700; }}
    .bad {{ color: #a15c00; font-weight: 700; }}
    @media (max-width: 960px) {{ .grid, .two-col {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <h1>Stage B v3 Checkpoint 全量 Test Decode 报告</h1>
  <p class="muted">生成时间：{esc(generated_at)} ｜ 输入目录：<code>{esc(input_dir)}</code></p>

  <div class="grid">
    <div class="card"><div class="k">V3 full test canonical</div><div class="v ok">{pct(v3.get("canonical_match"))}</div><div class="muted">{int(v3.get("decoded_sample_count") or 0):,} decoded</div></div>
    <div class="card"><div class="k">V2 curated transfer</div><div class="v bad">{pct(v2.get("canonical_match"))}</div><div class="muted">{int(v2.get("decoded_sample_count") or 0):,} decoded</div></div>
    <div class="card"><div class="k">Canonical gap</div><div class="v">{pct(canonical_gap)}</div><div class="muted">V3 - V2</div></div>
    <div class="card"><div class="k">RDKit gap</div><div class="v">{pct(rdkit_gap)}</div><div class="muted">V3 - V2</div></div>
  </div>

  <div class="callout">
    <strong>结论：</strong>当前 v3 checkpoint 在 OMG v3 test 上全量 decode 表现强，canonical_match={pct(v3.get("canonical_match"))}；
    但迁移到 V2 curated test 明显失败，canonical_match={pct(v2.get("canonical_match"))}。
    因此它适合作为大规模 OMG warmup，不应直接替代 curated Stage B；下一步应在 curated/V2 上继续 fine-tune。
  </div>

  <h2>1. 总体 full-decode 指标</h2>
  {table(["eval set", "decoded", "loss", "token acc", "canonical", "exact", "RDKit valid", "two attachment"], summary_rows(datasets))}

  <h2>2. 每种模板/view 的结果</h2>
  <h3>V3 OMG test 分模板结果</h3>
  {table(["template/view", "rows", "canonical", "exact", "RDKit valid", "two attachment", "failed"], strategy_metric_rows(datasets["v3"]))}
  <h3>V2 curated test 分模板结果</h3>
  {table(["template/view", "rows", "canonical", "exact", "RDKit valid", "two attachment", "failed"], strategy_metric_rows(datasets["v2"]))}

  <h2>3. 失败类型总体分布</h2>
  {table(["eval set", "correct", "valid wrong canonical", "invalid SMILES", "attachment error"], category_rows(datasets))}

  <h2>4. 每种模板的失败类型分布</h2>
  <h3>V3 OMG test</h3>
  {table(["template/view", "failed", "invalid SMILES", "attachment error", "valid wrong canonical", "failure rate"], strategy_failure_rows(datasets["v3"]))}
  <h3>V2 curated test</h3>
  {table(["template/view", "failed", "invalid SMILES", "attachment error", "valid wrong canonical", "failure rate"], strategy_failure_rows(datasets["v2"]))}

  <h2>5. 每种模板的 V2/V3 对比与失败样例</h2>
  <div class="warnbox">
    <strong>读法：</strong>V3 的主要弱项是 <code>light_denoise</code> 和 <code>rdkit_random_smiles</code>；
    V2 上五种模板都不理想，即使 identity 也只有约 29% canonical，说明这是分布迁移问题，不只是干扰模板问题。
  </div>
  {per_strategy_sections(datasets)}

  <h2>6. 文件清单</h2>
  {table(["file", "size"], file_rows(input_dir))}
</main>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build HTML report for Stage B v3 full-decode V2/V3 test evaluation.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_report(input_dir=args.input_dir, output_path=args.output)
    print(args.output)


if __name__ == "__main__":
    main()
