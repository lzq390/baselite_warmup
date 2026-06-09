from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from build_stage_b_style_stage_c_reports import (
    STRATEGY_COLORS,
    STRATEGY_MEANINGS,
    artifact_rows,
    build_stage_c_report,
    esc,
    format_report_page,
    metric,
    metric_value,
    num,
    pct,
    pp,
    read_json,
    read_jsonl,
    restore_loss,
    table,
)


DEFAULT_FULL_ARTIFACTS = Path("reports/stage_c_non_vocab_aug_v2_full_30epoch_artifacts")
DEFAULT_CURRICULUM_ARTIFACTS = Path("reports/stage_c_non_vocab_aug_v2_curriculum_full_30epoch_artifacts")
DEFAULT_CURRICULUM_REPORT = Path("reports/stage_c_non_vocab_aug_v2_curriculum_full_30epoch_report.html")
DEFAULT_COMPARISON_REPORT = Path("reports/stage_c_aug_v2_full_vs_curriculum_30epoch_report.html")


def read_eval_bundle(artifacts: Path) -> dict[str, Any]:
    return {
        "valid": read_json(artifacts / "eval_metrics.json"),
        "test": read_json(artifacts / "all_view_test_eval_metrics.json"),
        "robust_valid": read_json(artifacts / "robustness_valid_eval_metrics.json"),
        "robust_test": read_json(artifacts / "robustness_test_eval_metrics.json"),
        "epochs": read_jsonl(artifacts / "epoch_metrics.jsonl"),
        "config": read_json(artifacts / "training_config.json"),
    }


def delta_cell(delta: float, *, lower_is_better: bool = False) -> str:
    good = delta < 0 if lower_is_better else delta > 0
    text = f"{delta:+.4f}" if lower_is_better else pp(delta)
    return f'<span class="delta {"pos" if good else "neg"}">{esc(text)}</span>'


def winner_cell(delta: float, *, lower_is_better: bool = False) -> str:
    curriculum_better = delta < 0 if lower_is_better else delta > 0
    winner = "curriculum better" if curriculum_better else "full better"
    cls = "good" if curriculum_better else "warn"
    return f'<span class="pill {cls}">{winner}</span>'


def cmp_bar_fc(metric_name: str, full: float, curriculum: float, *, lower_is_better: bool = False) -> str:
    max_value = max(full, curriculum, 1e-9)
    full_width = full / max_value * 100
    curr_width = curriculum / max_value * 100
    delta = curriculum - full
    good = delta < 0 if lower_is_better else delta > 0
    delta_text = f"{delta:+.4f}" if lower_is_better else pp(delta)
    return f"""
      <div class="cmp-row">
        <div class="cmp-label">{esc(metric_name)}</div>
        <div class="cmp-bars">
          <div class="cmp-line"><span>full</span><div class="cmp-track"><i style="width:{full_width:.2f}%;background:#475569"></i></div><b>{num(full, 4) if lower_is_better else pct(full)}</b></div>
          <div class="cmp-line"><span>curr</span><div class="cmp-track"><i style="width:{curr_width:.2f}%;background:#2563eb"></i></div><b>{num(curriculum, 4) if lower_is_better else pct(curriculum)}</b></div>
        </div>
        <div class="cmp-delta {'pos' if good else 'neg'}">{esc(delta_text)}</div>
      </div>"""


def comparison_card(label: str, full: float, curriculum: float, *, lower_is_better: bool = False) -> str:
    value = num(curriculum, 4) if lower_is_better else pct(curriculum)
    full_text = num(full, 4) if lower_is_better else pct(full)
    return metric(
        label,
        f"{value} {delta_cell(curriculum - full, lower_is_better=lower_is_better)}",
        f"Full {full_text} · Curriculum vs Full",
    )


def metric_rows(full: dict[str, Any], curriculum: dict[str, Any]) -> list[list[Any]]:
    specs = [
        ("Valid restore loss", "valid", "loss", True),
        ("Valid canonical", "valid", "canonical_match", False),
        ("Valid exact", "valid", "exact_string_match", False),
        ("Valid RDKit validity", "valid", "rdkit_validity", False),
        ("Valid two attachment", "valid", "two_attachment_validity", False),
        ("Test restore loss", "test", "loss", True),
        ("Test canonical", "test", "canonical_match", False),
        ("Robust valid canonical", "robust_valid", "canonical_match", False),
        ("Robust test canonical", "robust_test", "canonical_match", False),
        ("Token accuracy valid", "valid", "token_accuracy", False),
        ("RDKit validity valid", "valid", "rdkit_validity", False),
    ]
    rows: list[list[Any]] = []
    for label, split, key, lower in specs:
        full_value = restore_loss(full[split]) if key == "loss" else metric_value(full[split], key)
        cur_value = restore_loss(curriculum[split]) if key == "loss" else metric_value(curriculum[split], key)
        if full_value is None or cur_value is None:
            continue
        rows.append(
            [
                esc(label),
                num(full_value, 4) if lower else pct(full_value),
                num(cur_value, 4) if lower else pct(cur_value),
                delta_cell(cur_value - full_value, lower_is_better=lower),
                winner_cell(cur_value - full_value, lower_is_better=lower),
            ]
        )
    return rows


def strategy_rows(
    full_metrics: dict[str, Any],
    curriculum_metrics: dict[str, Any],
    key: str,
    *,
    include_meaning: bool = False,
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    full_by_strategy = full_metrics.get(key) or {}
    cur_by_strategy = curriculum_metrics.get(key) or {}
    for strategy in sorted(set(full_by_strategy) | set(cur_by_strategy)):
        if strategy not in full_by_strategy or strategy not in cur_by_strategy:
            continue
        full_rate = float(full_by_strategy[strategy]["canonical_match"])
        cur_rate = float(cur_by_strategy[strategy]["canonical_match"])
        row = [
            f'<span class="dot" style="background:{STRATEGY_COLORS.get(strategy, "#2563eb")}"></span><b>{esc(strategy)}</b>',
        ]
        if include_meaning:
            row.append(esc(STRATEGY_MEANINGS.get(strategy, "")))
        row.extend(
            [
                pct(full_rate),
                pct(cur_rate),
                pp(cur_rate - full_rate),
                cmp_bar_fc(strategy, full_rate, cur_rate),
            ]
        )
        rows.append(row)
    return rows


def checkpoint_summary_rows(full: dict[str, Any], curriculum: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for label, bundle in [("Full", full), ("Curriculum", curriculum)]:
        epochs = bundle["epochs"]
        best_restore = min(epochs, key=lambda row: float(row["restore_loss"]))
        best_canonical = max(epochs, key=lambda row: float(row["canonical_match"]))
        final = epochs[-1]
        rows.extend(
            [
                [
                    esc(label),
                    "Raw restore-loss best",
                    esc(best_restore["checkpoint_name"]),
                    num(float(best_restore["restore_loss"]), 4),
                    pct(float(best_restore["canonical_match"])),
                    pct(float(best_restore["rdkit_validity"])),
                ],
                [
                    esc(label),
                    "Best valid canonical",
                    esc(best_canonical["checkpoint_name"]),
                    num(float(best_canonical["restore_loss"]), 4),
                    pct(float(best_canonical["canonical_match"])),
                    pct(float(best_canonical["rdkit_validity"])),
                ],
                [
                    esc(label),
                    "Final checkpoint",
                    esc(final["checkpoint_name"]),
                    num(float(final["restore_loss"]), 4),
                    pct(float(final["canonical_match"])),
                    pct(float(final["rdkit_validity"])),
                ],
            ]
        )
    return rows


def checkpoint_rows_stageb_style(full: dict[str, Any], curriculum: dict[str, Any]) -> list[list[Any]]:
    full_epochs = full["epochs"]
    curr_epochs = curriculum["epochs"]
    full_best_loss = min(full_epochs, key=lambda row: float(row["restore_loss"]))
    curr_best_loss = min(curr_epochs, key=lambda row: float(row["restore_loss"]))
    full_final = full_epochs[-1]
    curr_final = curr_epochs[-1]
    return [
        [
            "Full best restore-loss checkpoint",
            esc(full_best_loss["checkpoint_name"]),
            num(float(full_best_loss["restore_loss"]), 4),
            pct(float(full_best_loss["canonical_match"])),
        ],
        [
            "Curriculum best restore-loss checkpoint",
            esc(curr_best_loss["checkpoint_name"]),
            num(float(curr_best_loss["restore_loss"]), 4),
            pct(float(curr_best_loss["canonical_match"])),
        ],
        [
            "Full final checkpoint",
            esc(full_final["checkpoint_name"]),
            num(float(full_final["restore_loss"]), 4),
            pct(float(full_final["canonical_match"])),
        ],
        [
            "Curriculum final checkpoint",
            esc(curr_final["checkpoint_name"]),
            num(float(curr_final["restore_loss"]), 4),
            pct(float(curr_final["canonical_match"])),
        ],
    ]


def parity_rows(full: dict[str, Any], curriculum: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for label, bundle in [("Full", full), ("Curriculum", curriculum)]:
        valid = bundle["valid"]
        test = bundle["test"]
        robust_valid = bundle["robust_valid"]
        robust_test = bundle["robust_test"]
        rows.append(
            [
                esc(label),
                esc(valid.get("completed_epochs", bundle["config"].get("max_epochs"))),
                f"{int(valid.get('decoded_sample_count', 0)):,}/{int(valid.get('sample_count', 0)):,}",
                f"{int(test.get('decoded_sample_count', 0)):,}/{int(test.get('sample_count', 0)):,}",
                f"{int(robust_valid.get('decoded_sample_count', 0)):,}/{int(robust_valid.get('sample_count', 0)):,}",
                f"{int(robust_test.get('decoded_sample_count', 0)):,}/{int(robust_test.get('sample_count', 0)):,}",
                f"monitor_only={valid.get('early_stopping_monitor_only')}, stopped={valid.get('early_stopped')}",
            ]
        )
    return rows


def retrieval_rows(full: dict[str, Any], curriculum: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    specs = [
        ("Valid text->graph top1", "valid", "text_to_graph_top1"),
        ("Valid graph->text top1", "valid", "graph_to_text_top1"),
        ("Test text->graph top1", "test", "text_to_graph_top1"),
        ("Test graph->text top1", "test", "graph_to_text_top1"),
        ("Valid text->graph top5", "valid", "text_to_graph_top5"),
        ("Valid graph->text top5", "valid", "graph_to_text_top5"),
    ]
    for label, split, key in specs:
        full_value = metric_value(full[split], key)
        cur_value = metric_value(curriculum[split], key)
        if full_value is None or cur_value is None:
            continue
        rows.append([esc(label), pct(full_value), pct(cur_value), delta_cell(cur_value - full_value)])
    return rows


def build_full_curriculum_comparison(full_artifacts: Path, curriculum_artifacts: Path, output_path: Path) -> None:
    full = read_eval_bundle(full_artifacts)
    curriculum = read_eval_bundle(curriculum_artifacts)

    cards = "".join(
        [
            comparison_card(
                "Final valid canonical",
                float(full["valid"]["canonical_match"]),
                float(curriculum["valid"]["canonical_match"]),
            ),
            comparison_card(
                "Final test canonical",
                float(full["test"]["canonical_match"]),
                float(curriculum["test"]["canonical_match"]),
            ),
            comparison_card(
                "Robust valid canonical",
                float(full["robust_valid"]["canonical_match"]),
                float(curriculum["robust_valid"]["canonical_match"]),
            ),
            comparison_card(
                "Robust test canonical",
                float(full["robust_test"]["canonical_match"]),
                float(curriculum["robust_test"]["canonical_match"]),
            ),
            comparison_card(
                "Valid restore loss",
                restore_loss(full["valid"]) or 0.0,
                restore_loss(curriculum["valid"]) or 0.0,
                lower_is_better=True,
            ),
            comparison_card(
                "Test restore loss",
                restore_loss(full["test"]) or 0.0,
                restore_loss(curriculum["test"]) or 0.0,
                lower_is_better=True,
            ),
        ]
    )

    final_metric_bars = "".join(
        [
            cmp_bar_fc(
                "Canonical Match",
                float(full["valid"]["canonical_match"]),
                float(curriculum["valid"]["canonical_match"]),
            ),
            cmp_bar_fc(
                "Exact String Match",
                float(full["valid"]["exact_string_match"]),
                float(curriculum["valid"]["exact_string_match"]),
            ),
            cmp_bar_fc(
                "RDKit Validity",
                float(full["valid"]["rdkit_validity"]),
                float(curriculum["valid"]["rdkit_validity"]),
            ),
            cmp_bar_fc(
                "Two Attachment Validity",
                float(full["valid"]["two_attachment_validity"]),
                float(curriculum["valid"]["two_attachment_validity"]),
            ),
            cmp_bar_fc(
                "Restore Loss",
                restore_loss(full["valid"]) or 0.0,
                restore_loss(curriculum["valid"]) or 0.0,
                lower_is_better=True,
            ),
        ]
    )

    body = f"""
  <section class="grid metrics">{cards}</section>

  <section class="card">
    <h2>Strategy Definitions</h2>
    {table(["Item", "Description"], [
        ["Full strategy", "Stage C static full all-view：每个 epoch 直接使用 v2 train 全量 46,320 行，五种策略等量覆盖，并优化 L_restore + 0.2 * L_align。"],
        ["Curriculum strategy", "Stage C progressive curriculum：每个 epoch 仍采样 46,320 行，但从 identity/random 偏重逐步过渡到 random/direction/rooted/denoise 权重。"],
        ["Shared dataset", "<code>data/baselite_smiles_aug_v2/training_template_preview.jsonl</code>"],
        ["Graph source", "<code>data/processed/repeat_unit_graphs.jsonl</code>"],
        ["Formal eval rule", "checkpoint valid 5,790、final valid/test 5,790、robustness valid/test 4,632，均为 full decode；retrieval 对 valid/test 使用 graph 去重口径。"],
        ["Artifacts", f"full: <code>{esc(full_artifacts)}</code><br>curriculum: <code>{esc(curriculum_artifacts)}</code>"],
    ])}
  </section>

  <section class="card">
    <h2>Headline Metric Comparison</h2>
    {table(["Metric", "Full", "Curriculum", "Delta", "Winner"], metric_rows(full, curriculum))}
  </section>

  <section class="grid two">
    <div class="bar-card"><h3>Final Checkpoint Metrics</h3>{final_metric_bars}</div>
    <div class="card">
      <h2>Full-Decode Parity Check</h2>
      {table(["Run", "Epochs", "Valid Decode", "Test Decode", "Robust Valid", "Robust Test", "Early Stop"], parity_rows(full, curriculum))}
    </div>
  </section>

  <section class="card">
    <h2>Final Valid Strategy Comparison</h2>
    {table(["Strategy", "Meaning", "Full", "Curriculum", "Delta", "Visual"], strategy_rows(full["valid"], curriculum["valid"], "all_view_by_strategy", include_meaning=True))}
  </section>

  <section class="card">
    <h2>Robustness Test Strategy Comparison</h2>
    {table(["Strategy", "Full", "Curriculum", "Delta", "Visual"], strategy_rows(full["robust_test"], curriculum["robust_test"], "robustness_by_strategy"))}
  </section>

  <section class="card">
    <h2>Checkpoint Comparison</h2>
    {table(["Point", "Checkpoint", "Restore Loss", "Canonical"], checkpoint_rows_stageb_style(full, curriculum))}
  </section>

  <section class="card">
    <h2>Retrieval Comparison</h2>
    {table(["Metric", "Full", "Curriculum", "Delta"], retrieval_rows(full, curriculum))}
  </section>

  <section class="card">
    <h2>Interpretation</h2>
    <div class="callout">Curriculum 在 final valid/test canonical 与 final restore loss 上均高于 static full，test canonical 提升更明显（+1.35 pp）。Robustness valid 基本持平略低（-0.13 pp），robustness test 略高（+0.63 pp）。两组都跑满 30 epoch，formal decode 口径一致，因此可以直接作为 Stage C 内部策略对照。</div>
  </section>

  <section class="card">
    <h2>Artifacts Included Locally</h2>
    {table(["Curriculum File", "Size"], artifact_rows(curriculum_artifacts))}
  </section>

  <footer>Generated locally at {esc(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))} from <code>{esc(full_artifacts)}</code> and <code>{esc(curriculum_artifacts)}</code>. Report file: <code>{esc(output_path)}</code>.</footer>
"""
    subtitle = "本报告并排比较 Stage C v2 的 static full all-view 与 progressive curriculum 两组 30 epoch 全量训练结果，所有正式指标均采用 full decode 口径。"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(format_report_page("Stage C v2 Full vs Curriculum Comparison", subtitle, body), encoding="utf-8")


def build_curriculum_report(curriculum_artifacts: Path, output_path: Path) -> None:
    build_stage_c_report(curriculum_artifacts, output_path)
    html = output_path.read_text(encoding="utf-8")
    replacements = {
        "Stage C v2 Full Static All-View Report": "Stage C v2 Curriculum Full All-View Report",
        "Stage C static full all-view": "Stage C curriculum full all-view",
        "Stage C static": "Stage C curriculum",
        "每个 epoch 固定遍历 v2 train 全量 46,320 行": "每个 epoch 仍使用 46,320 行，按 curriculum 调整策略采样权重",
        "Stage C full 对照组：每个 epoch 都使用 v2 train 全量 all-view 数据": "Stage C curriculum full 对照组：每个 epoch 使用 v2 train 等量样本，并按阶段调整 all-view 策略权重",
        "Stage C static full all-view training": "Stage C curriculum full all-view training",
        "不按 epoch 改变策略权重": "按 curriculum 阶段改变策略权重",
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    output_path.write_text(html, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage C curriculum report and full-vs-curriculum comparison.")
    parser.add_argument("--full-artifacts", type=Path, default=DEFAULT_FULL_ARTIFACTS)
    parser.add_argument("--curriculum-artifacts", type=Path, default=DEFAULT_CURRICULUM_ARTIFACTS)
    parser.add_argument("--curriculum-report", type=Path, default=DEFAULT_CURRICULUM_REPORT)
    parser.add_argument("--comparison-report", type=Path, default=DEFAULT_COMPARISON_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_curriculum_report(args.curriculum_artifacts, args.curriculum_report)
    build_full_curriculum_comparison(args.full_artifacts, args.curriculum_artifacts, args.comparison_report)
    print(
        json.dumps(
            {
                "curriculum_report": str(args.curriculum_report),
                "comparison_report": str(args.comparison_report),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
