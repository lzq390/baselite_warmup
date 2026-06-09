from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from build_stage_b_stage_c_epoch_strategy_report import (
    CSS,
    STRATEGY_MEANINGS,
    STRATEGY_ORDER,
    delta_span,
    esc,
    metric_card,
    num,
    pct,
    pp,
    read_jsonl,
    strategy_label,
    table,
    value_bar,
)


DEFAULT_FULL_ARTIFACTS = Path("reports/stage_c_non_vocab_aug_v2_full_30epoch_artifacts")
DEFAULT_CURRICULUM_ARTIFACTS = Path("reports/stage_c_non_vocab_aug_v2_curriculum_full_30epoch_artifacts")
DEFAULT_REPORT = Path("reports/stage_c_aug_v2_epoch_strategy_valid_full_vs_curriculum_report.html")


def common_epoch_pairs(full_rows: list[dict[str, Any]], curri_rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by_full = {int(row["checkpoint_epoch"]): row for row in full_rows}
    by_curri = {int(row["checkpoint_epoch"]): row for row in curri_rows}
    return [(by_full[epoch], by_curri[epoch]) for epoch in sorted(set(by_full) & set(by_curri))]


def curri_weight_cell(curri_row: dict[str, Any], strategy: str) -> str:
    weights = curri_row.get("curriculum_strategy_weights") or {}
    counts = curri_row.get("curriculum_strategy_counts") or {}
    weight = float(weights.get(strategy, 0.0))
    count = int(counts.get(strategy, 0))
    return f"{weight * 100:.0f}%<div class=\"sub\">{count:,} rows</div>"


def macro_rows(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for full_row, curri_row in pairs:
        full_loss = float(full_row.get("restore_loss", full_row.get("loss", 0.0)))
        curri_loss = float(curri_row.get("restore_loss", curri_row.get("loss", 0.0)))
        rows.append(
            [
                int(full_row["checkpoint_epoch"]),
                num(full_loss),
                num(curri_loss),
                delta_span(curri_loss - full_loss, lower_is_better=True),
                pct(float(full_row["canonical_match"])),
                pct(float(curri_row["canonical_match"])),
                delta_span(float(curri_row["canonical_match"]) - float(full_row["canonical_match"])),
                pct(float(full_row["rdkit_validity"])),
                pct(float(curri_row["rdkit_validity"])),
                delta_span(float(curri_row["rdkit_validity"]) - float(full_row["rdkit_validity"])),
            ]
        )
    return rows


def delta_matrix_rows(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for full_row, curri_row in pairs:
        row: list[Any] = [int(full_row["checkpoint_epoch"])]
        for strategy in STRATEGY_ORDER:
            full_values = full_row["all_view_by_strategy"][strategy]
            curri_values = curri_row["all_view_by_strategy"][strategy]
            row.append(delta_span(float(curri_values["canonical_match"]) - float(full_values["canonical_match"])))
        rows.append(row)
    return rows


def best_strategy_rows(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    full_rows = [pair[0] for pair in pairs]
    curri_rows = [pair[1] for pair in pairs]
    for strategy in STRATEGY_ORDER:
        full_best = max(full_rows, key=lambda row: float(row["all_view_by_strategy"][strategy]["canonical_match"]))
        curri_best = max(curri_rows, key=lambda row: float(row["all_view_by_strategy"][strategy]["canonical_match"]))
        full_final = full_rows[-1]["all_view_by_strategy"][strategy]
        curri_final = curri_rows[-1]["all_view_by_strategy"][strategy]
        full_best_value = float(full_best["all_view_by_strategy"][strategy]["canonical_match"])
        curri_best_value = float(curri_best["all_view_by_strategy"][strategy]["canonical_match"])
        full_final_value = float(full_final["canonical_match"])
        curri_final_value = float(curri_final["canonical_match"])
        rows.append(
            [
                strategy_label(strategy),
                f"epoch {int(full_best['checkpoint_epoch'])} · {pct(full_best_value)}",
                f"epoch {int(curri_best['checkpoint_epoch'])} · {pct(curri_best_value)}",
                delta_span(curri_best_value - full_best_value),
                pct(full_final_value),
                pct(curri_final_value),
                delta_span(curri_final_value - full_final_value),
            ]
        )
    return rows


def detailed_rows(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for full_row, curri_row in pairs:
        for strategy in STRATEGY_ORDER:
            full_values = full_row["all_view_by_strategy"][strategy]
            curri_values = curri_row["all_view_by_strategy"][strategy]
            full_can = float(full_values["canonical_match"])
            curri_can = float(curri_values["canonical_match"])
            full_exact = float(full_values["exact_string_match"])
            curri_exact = float(curri_values["exact_string_match"])
            full_rdkit = float(full_values["rdkit_validity"])
            curri_rdkit = float(curri_values["rdkit_validity"])
            full_attach = float(full_values["two_attachment_validity"])
            curri_attach = float(curri_values["two_attachment_validity"])
            rows.append(
                [
                    int(full_row["checkpoint_epoch"]),
                    strategy_label(strategy),
                    curri_weight_cell(curri_row, strategy),
                    value_bar(full_can),
                    value_bar(curri_can),
                    delta_span(curri_can - full_can),
                    value_bar(full_exact),
                    value_bar(curri_exact),
                    delta_span(curri_exact - full_exact),
                    value_bar(full_rdkit),
                    value_bar(curri_rdkit),
                    delta_span(curri_rdkit - full_rdkit),
                    value_bar(full_attach),
                    value_bar(curri_attach),
                    delta_span(curri_attach - full_attach),
                    f"{int(full_values.get('failed_count', 0)):,} / {int(curri_values.get('failed_count', 0)):,}",
                ]
            )
    return rows


def build_report(full_artifacts: Path, curriculum_artifacts: Path, output_path: Path) -> None:
    full_rows = read_jsonl(full_artifacts / "epoch_metrics.jsonl")
    curri_rows = read_jsonl(curriculum_artifacts / "epoch_metrics.jsonl")
    pairs = common_epoch_pairs(full_rows, curri_rows)
    if not pairs:
        raise ValueError("No common checkpoint epochs found")

    full_common = [pair[0] for pair in pairs]
    curri_common = [pair[1] for pair in pairs]
    full_best = max(full_common, key=lambda row: float(row["canonical_match"]))
    curri_best = max(curri_common, key=lambda row: float(row["canonical_match"]))
    full_final = full_common[-1]
    curri_final = curri_common[-1]
    final_delta = float(curri_final["canonical_match"]) - float(full_final["canonical_match"])

    cards = "".join(
        [
            metric_card("Full best valid canonical", pct(float(full_best["canonical_match"])), f"epoch {int(full_best['checkpoint_epoch'])}"),
            metric_card("Curri best valid canonical", pct(float(curri_best["canonical_match"])), f"epoch {int(curri_best['checkpoint_epoch'])}"),
            metric_card("Final canonical delta", delta_span(final_delta), f"Curri {pct(float(curri_final['canonical_match']))} vs Full {pct(float(full_final['canonical_match']))}"),
            metric_card("Rows in main table", f"{len(pairs) * len(STRATEGY_ORDER):,}", f"{len(pairs)} epochs × {len(STRATEGY_ORDER)} strategies"),
        ]
    )

    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage C v2 Epoch Strategy Valid Full vs Curri</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>Stage C v2 Epoch × Strategy Valid Results: Full vs Curriculum</h1>
  <p>按 Stage B full/curri 对照报告的结构，并排比较 Stage C v2 static full all-view 与 progressive curriculum 两组 30 epoch 全量训练结果。所有 checkpoint 均为 valid full decode，策略分项样本数为每策略 1,158，总计 5,790。</p>
</header>
<main>
  <section class="grid metrics">{cards}</section>

  <section class="card">
    <h2>Reading Notes</h2>
    <div class="callout">
      表中每行是一个 <b>epoch × strategy</b>。<code>Curri weight</code> 是 curriculum 当轮训练采样权重和采样行数；full 组每轮都是静态 all-view 全量训练。Delta = curriculum - full，正值表示 curriculum 更高。Failed 显示 full / curriculum 的 failed_count。Stage C loss 使用 restore_loss 作为 checkpoint 对照口径。
    </div>
  </section>

  <section class="card compact">
    <h2>Macro Valid Checkpoint Comparison by Epoch</h2>
    {table(["Epoch", "Full Restore Loss", "Curri Restore Loss", "Loss Δ", "Full Canonical", "Curri Canonical", "Canonical Δ", "Full RDKit", "Curri RDKit", "RDKit Δ"], macro_rows(pairs))}
  </section>

  <section class="card compact">
    <h2>Canonical Delta Matrix by Epoch and Strategy</h2>
    {table(["Epoch", *STRATEGY_ORDER], delta_matrix_rows(pairs))}
  </section>

  <section class="card compact">
    <h2>Best Canonical by Strategy</h2>
    {table(["Strategy", "Full Best", "Curri Best", "Best Δ", "Full Final", "Curri Final", "Final Δ"], best_strategy_rows(pairs))}
  </section>

  <section class="card">
    <h2>Detailed Epoch × Strategy Valid Metrics</h2>
    {table(["Epoch", "Strategy", "Curri weight", "Full Canonical", "Curri Canonical", "Can Δ", "Full Exact", "Curri Exact", "Exact Δ", "Full RDKit", "Curri RDKit", "RDKit Δ", "Full 2-Attach", "Curri 2-Attach", "2-Attach Δ", "Failed full/curri"], detailed_rows(pairs))}
  </section>

  <footer>Generated locally at {esc(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))} from <code>{esc(full_artifacts / 'epoch_metrics.jsonl')}</code> and <code>{esc(curriculum_artifacts / 'epoch_metrics.jsonl')}</code>. Report file: <code>{esc(output_path)}</code>.</footer>
</main>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(body, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage C epoch-strategy valid full-vs-curriculum HTML report.")
    parser.add_argument("--full-artifacts", type=Path, default=DEFAULT_FULL_ARTIFACTS)
    parser.add_argument("--curriculum-artifacts", type=Path, default=DEFAULT_CURRICULUM_ARTIFACTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_report(args.full_artifacts, args.curriculum_artifacts, args.output)
    print(json.dumps({"report": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
