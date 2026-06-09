from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


RUNS = {
    "B_full": {
        "label": "Stage B full",
        "artifacts": Path("reports/stage_b_restore_aug_v2_full_20epoch_artifacts"),
        "test_metrics": "identity_test_eval_metrics.json",
    },
    "B_curri": {
        "label": "Stage B curri",
        "artifacts": Path("reports/stage_b_restore_aug_v2_curriculum_full_20epoch_artifacts"),
        "test_metrics": "identity_test_eval_metrics.json",
    },
    "C_full": {
        "label": "Stage C full",
        "artifacts": Path("reports/stage_c_non_vocab_aug_v2_full_30epoch_artifacts"),
        "test_metrics": "all_view_test_eval_metrics.json",
    },
    "C_curri": {
        "label": "Stage C curri",
        "artifacts": Path("reports/stage_c_non_vocab_aug_v2_curriculum_full_30epoch_artifacts"),
        "test_metrics": "all_view_test_eval_metrics.json",
    },
}

STRATEGY_ORDER = [
    "identity",
    "attachment_rooted_smiles",
    "rdkit_random_smiles",
    "direction_flip",
    "light_denoise",
]

OUTPUT = Path("reports/stage_c_strategy_alignment_analysis_report.html")
ASSET_DIR = Path("reports/stage_c_strategy_analysis_assets")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def pp(value: float) -> str:
    return f"{value * 100:+.2f} pp"


def loss(metric: dict[str, Any]) -> float:
    return float(metric.get("restore_loss", metric.get("loss", 0.0)))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_run(run_id: str) -> dict[str, Any]:
    spec = RUNS[run_id]
    root = spec["artifacts"]
    return {
        "id": run_id,
        "label": spec["label"],
        "root": root,
        "valid": read_json(root / "eval_metrics.json"),
        "test": read_json(root / spec["test_metrics"]),
        "robust_valid": read_json(root / "robustness_valid_eval_metrics.json"),
        "robust_test": read_json(root / "robustness_test_eval_metrics.json"),
        "epochs": read_jsonl(root / "epoch_metrics.jsonl"),
    }


def delta_row(label: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, float | str]:
    return {
        "comparison": label,
        "valid_canonical": right["valid"]["canonical_match"] - left["valid"]["canonical_match"],
        "valid_exact": right["valid"]["exact_string_match"] - left["valid"]["exact_string_match"],
        "test_canonical": right["test"]["canonical_match"] - left["test"]["canonical_match"],
        "robust_valid": right["robust_valid"]["canonical_match"] - left["robust_valid"]["canonical_match"],
        "robust_test": right["robust_test"]["canonical_match"] - left["robust_test"]["canonical_match"],
        "valid_rdkit": right["valid"]["rdkit_validity"] - left["valid"]["rdkit_validity"],
        "valid_loss": loss(right["valid"]) - loss(left["valid"]),
    }


def html_table(headers: list[str], rows: list[list[Any]], *, cls: str = "") -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="table-wrap {esc(cls)}"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def signed_cell(value: float, *, lower_is_better: bool = False) -> str:
    if abs(value) < 0.0005:
        css = "flat"
    else:
        good = value < 0 if lower_is_better else value > 0
        css = "pos" if good else "neg"
    text = f"{value:+.4f}" if lower_is_better else pp(value)
    return f'<span class="{css}">{esc(text)}</span>'


def metric_card(label: str, value: str, note: str, cls: str = "") -> str:
    return (
        f'<div class="metric {esc(cls)}">'
        f'<div class="metric-label">{esc(label)}</div>'
        f'<div class="metric-value">{value}</div>'
        f'<div class="metric-note">{esc(note)}</div>'
        "</div>"
    )


def epoch20_rows(runs: dict[str, dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for label, left_id, right_id in [
        ("full: Stage C - Stage B", "B_full", "C_full"),
        ("curri: Stage C - Stage B", "B_curri", "C_curri"),
    ]:
        left = next(row for row in runs[left_id]["epochs"] if int(row["checkpoint_epoch"]) == 20)
        right = next(row for row in runs[right_id]["epochs"] if int(row["checkpoint_epoch"]) == 20)
        rows.append(
            [
                esc(label),
                f"{pct(left['canonical_match'])} -> {pct(right['canonical_match'])}",
                signed_cell(right["canonical_match"] - left["canonical_match"]),
                signed_cell(right["exact_string_match"] - left["exact_string_match"]),
                signed_cell(right["rdkit_validity"] - left["rdkit_validity"]),
                signed_cell(loss(right) - loss(left), lower_is_better=True),
            ]
        )
    return rows


def strategy_delta_rows(left: dict[str, Any], right: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    left_by = left["valid"]["all_view_by_strategy"]
    right_by = right["valid"]["all_view_by_strategy"]
    for strategy in STRATEGY_ORDER:
        a = left_by[strategy]
        b = right_by[strategy]
        rows.append(
            [
                esc(strategy),
                signed_cell(b["canonical_match"] - a["canonical_match"]),
                signed_cell(b["exact_string_match"] - a["exact_string_match"]),
                signed_cell(b["rdkit_validity"] - a["rdkit_validity"]),
                signed_cell(b["two_attachment_validity"] - a["two_attachment_validity"]),
            ]
        )
    return rows


def headline_rows(runs: dict[str, dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for run_id in ["B_full", "B_curri", "C_full", "C_curri"]:
        run = runs[run_id]
        rows.append(
            [
                esc(run["label"]),
                pct(run["valid"]["canonical_match"]),
                pct(run["valid"]["exact_string_match"]),
                pct(run["test"]["canonical_match"]),
                pct(run["robust_valid"]["canonical_match"]),
                pct(run["robust_test"]["canonical_match"]),
                f"{loss(run['valid']):.4f}",
            ]
        )
    return rows


def retrieval_rows(runs: dict[str, dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for run_id in ["C_full", "C_curri"]:
        run = runs[run_id]
        rows.append(
            [
                esc(run["label"]),
                pct(run["valid"]["text_to_graph_top1"]),
                pct(run["valid"]["graph_to_text_top1"]),
                pct(run["test"]["text_to_graph_top1"]),
                pct(run["test"]["graph_to_text_top1"]),
                pct(run["test"]["text_to_graph_top5"]),
                pct(run["test"]["graph_to_text_top5"]),
            ]
        )
    return rows


def make_charts(runs: dict[str, dict[str, Any]], asset_dir: Path) -> tuple[Path, Path]:
    asset_dir.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", font_scale=0.95)

    deltas = [
        delta_row("C full - B full", runs["B_full"], runs["C_full"]),
        delta_row("C curri - B curri", runs["B_curri"], runs["C_curri"]),
    ]
    chart_rows = []
    for row in deltas:
        for key, label in [
            ("valid_canonical", "Valid canonical"),
            ("valid_exact", "Valid exact"),
            ("test_canonical", "Test canonical"),
            ("robust_valid", "Robust valid"),
            ("robust_test", "Robust test"),
        ]:
            chart_rows.append({"Comparison": row["comparison"], "Metric": label, "Delta pp": row[key] * 100})
    df = pd.DataFrame(chart_rows)
    fig, ax = plt.subplots(figsize=(10.8, 5.4))
    sns.barplot(data=df, x="Metric", y="Delta pp", hue="Comparison", ax=ax, palette=["#2563eb", "#14b8a6"])
    ax.axhline(0, color="#475569", linewidth=1)
    ax.set_title("Align joint training improves restore metrics versus Stage B")
    ax.set_xlabel("")
    ax.set_ylabel("Delta, percentage points")
    ax.tick_params(axis="x", rotation=18)
    ax.legend(loc="upper left", frameon=True)
    fig.tight_layout()
    stage_delta_path = asset_dir / "stage_c_vs_stage_b_delta.png"
    fig.savefig(stage_delta_path, dpi=180)
    plt.close(fig)

    curri_rows = []
    left = runs["C_full"]["valid"]["all_view_by_strategy"]
    right = runs["C_curri"]["valid"]["all_view_by_strategy"]
    for strategy in STRATEGY_ORDER:
        curri_rows.append(
            {
                "Strategy": strategy.replace("_", "\n"),
                "Canonical delta pp": (right[strategy]["canonical_match"] - left[strategy]["canonical_match"]) * 100,
                "RDKit delta pp": (right[strategy]["rdkit_validity"] - left[strategy]["rdkit_validity"]) * 100,
            }
        )
    sdf = pd.DataFrame(curri_rows).melt(id_vars="Strategy", var_name="Metric", value_name="Delta pp")
    fig, ax = plt.subplots(figsize=(10.8, 5.8))
    sns.barplot(data=sdf, x="Strategy", y="Delta pp", hue="Metric", ax=ax, palette=["#2563eb", "#f97316"])
    ax.axhline(0, color="#475569", linewidth=1)
    ax.set_title("Stage C curriculum lifts identity but not every augmented view")
    ax.set_xlabel("")
    ax.set_ylabel("Curriculum - full, percentage points")
    ax.legend(loc="upper right", frameon=True)
    fig.tight_layout()
    curri_path = asset_dir / "stage_c_curri_vs_full_strategy_delta.png"
    fig.savefig(curri_path, dpi=180)
    plt.close(fig)
    return stage_delta_path, curri_path


def build_report(output: Path, asset_dir: Path) -> None:
    runs = {run_id: load_run(run_id) for run_id in RUNS}
    stage_chart, curri_chart = make_charts(runs, asset_dir)

    c_full_delta = delta_row("C full - B full", runs["B_full"], runs["C_full"])
    c_curri_delta = delta_row("C curri - B curri", runs["B_curri"], runs["C_curri"])
    stage_c_delta = delta_row("C curri - C full", runs["C_full"], runs["C_curri"])
    stage_b_delta = delta_row("B curri - B full", runs["B_full"], runs["B_curri"])

    cards = "".join(
        [
            metric_card("Stage C full vs B full", signed_cell(c_full_delta["valid_canonical"]), "valid canonical, final checkpoints"),
            metric_card("Stage C curri vs B curri", signed_cell(c_curri_delta["valid_canonical"]), "valid canonical, final checkpoints"),
            metric_card("Stage C curri vs full", signed_cell(stage_c_delta["valid_canonical"]), "valid canonical, smaller than Stage B curri gain"),
            metric_card("Epoch 20 C-B gain", "+1.64 / +1.30 pp", "full / curri valid canonical at same epoch"),
        ]
    )

    headline_table = html_table(
        ["Run", "Valid canonical", "Valid exact", "Test canonical", "Robust valid", "Robust test", "Valid loss"],
        headline_rows(runs),
    )

    bc_table = html_table(
        ["Comparison", "Valid canonical", "Valid exact", "Test canonical", "Robust valid", "Robust test", "Valid loss"],
        [
            [
                "Stage C full - Stage B full",
                signed_cell(c_full_delta["valid_canonical"]),
                signed_cell(c_full_delta["valid_exact"]),
                signed_cell(c_full_delta["test_canonical"]),
                signed_cell(c_full_delta["robust_valid"]),
                signed_cell(c_full_delta["robust_test"]),
                signed_cell(c_full_delta["valid_loss"], lower_is_better=True),
            ],
            [
                "Stage C curri - Stage B curri",
                signed_cell(c_curri_delta["valid_canonical"]),
                signed_cell(c_curri_delta["valid_exact"]),
                signed_cell(c_curri_delta["test_canonical"]),
                signed_cell(c_curri_delta["robust_valid"]),
                signed_cell(c_curri_delta["robust_test"]),
                signed_cell(c_curri_delta["valid_loss"], lower_is_better=True),
            ],
            [
                "Stage B curri - Stage B full",
                signed_cell(stage_b_delta["valid_canonical"]),
                signed_cell(stage_b_delta["valid_exact"]),
                signed_cell(stage_b_delta["test_canonical"]),
                signed_cell(stage_b_delta["robust_valid"]),
                signed_cell(stage_b_delta["robust_test"]),
                signed_cell(stage_b_delta["valid_loss"], lower_is_better=True),
            ],
            [
                "Stage C curri - Stage C full",
                signed_cell(stage_c_delta["valid_canonical"]),
                signed_cell(stage_c_delta["valid_exact"]),
                signed_cell(stage_c_delta["test_canonical"]),
                signed_cell(stage_c_delta["robust_valid"]),
                signed_cell(stage_c_delta["robust_test"]),
                signed_cell(stage_c_delta["valid_loss"], lower_is_better=True),
            ],
        ],
    )

    css = """
:root{--bg:#f6f8fb;--panel:#fff;--ink:#142033;--muted:#647084;--line:#dbe3ee;--blue:#2563eb;--green:#047857;--red:#b91c1c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"Noto Sans CJK SC","Microsoft YaHei",sans-serif}
header{background:#101827;color:white;padding:36px 42px 32px}header h1{margin:0 0 10px;font-size:28px;letter-spacing:0}header p{margin:0;color:#cbd5e1;max-width:1160px}
main{max-width:1180px;margin:0 auto;padding:28px 22px 58px}section{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:20px;margin:0 0 22px;box-shadow:0 1px 2px rgba(15,23,42,.035)}
h2{margin:0 0 12px;font-size:20px}h3{margin:18px 0 8px;font-size:16px}.summary{background:#eff6ff;border-left:5px solid var(--blue)}.summary ul{margin:8px 0 0;padding-left:20px}.summary li{margin:7px 0}
.grid{display:grid;gap:14px}.metrics{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:22px}.metric{background:white;border:1px solid var(--line);border-radius:8px;padding:14px;min-height:98px}.metric-label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}.metric-value{font-size:24px;font-weight:760;margin:5px 0}.metric-note{font-size:12px;color:var(--muted)}
.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:8px;margin-top:12px}table{border-collapse:separate;border-spacing:0;width:100%;min-width:760px}th,td{padding:9px 11px;border-bottom:1px solid var(--line);border-right:1px solid #eef2f7;text-align:left;vertical-align:top}th{background:#f8fafc;color:#475569;font-size:12px;text-transform:uppercase;letter-spacing:.04em}tr:last-child td{border-bottom:0}
.pos{color:var(--green);font-weight:760}.neg{color:var(--red);font-weight:760}.flat{color:#64748b;font-weight:760}.note{color:var(--muted);font-size:13px}.chart{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff;margin:12px 0 8px}code{background:#eef2f7;border:1px solid #d9e2ec;padding:1px 5px;border-radius:5px;font-size:12px}footer{color:var(--muted);font-size:12px;margin-top:28px}
@media(max-width:900px){header{padding:28px 20px}main{padding:18px 12px 42px}.metrics{grid-template-columns:1fr}table{min-width:900px}}
"""

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage C Full/Curri 策略与 Align 共同训练分析报告</title>
<style>{css}</style>
</head>
<body>
<header>
  <h1>Stage C Full/Curri 策略与 Align 共同训练分析报告</h1>
  <p>基于本地四组 artifact：Stage B full、Stage B curriculum、Stage C full、Stage C curriculum。报告重点判断 Stage C 两种策略差异，以及 align 共同训练是否帮助字符串恢复和 SMILES 视图理解。</p>
</header>
<main>
  <section class="summary">
    <h2>Technical Summary</h2>
    <ul>
      <li><b>Align 共同训练总体值得保留。</b>Stage C full 相比 Stage B full，在 final valid canonical 上提升 {pp(c_full_delta["valid_canonical"])}，test canonical 提升 {pp(c_full_delta["test_canonical"])}，robust test canonical 提升 {pp(c_full_delta["robust_test"])}；Stage C curri 相比 Stage B curri 也分别提升 {pp(c_curri_delta["valid_canonical"])}、{pp(c_curri_delta["test_canonical"])}、{pp(c_curri_delta["robust_test"])}。</li>
      <li><b>同 epoch 20 下仍有提升。</b>Stage C full 对 Stage B full 的 valid canonical 提升 +1.64 pp，Stage C curri 对 Stage B curri 提升 +1.30 pp，说明收益不是单纯来自 Stage C 多跑到 30 epoch。</li>
      <li><b>Stage C curriculum 的边际收益小于 Stage B。</b>Stage B curri 相比 full 的 valid canonical 是 {pp(stage_b_delta["valid_canonical"])}，Stage C curri 相比 full 只有 {pp(stage_c_delta["valid_canonical"])}；align 共同训练已经把 full baseline 抬高，压缩了 curriculum 的额外空间。</li>
      <li><b>Stage C curri 更像提升 final/test 恢复，不是全面提升结构合法性。</b>它比 Stage C full 的 valid/test canonical 更高，但 valid RDKit 为 {pp(stage_c_delta["valid_rdkit"])}，robust valid canonical 为 {pp(stage_c_delta["robust_valid"])}，说明部分增强视图和合法性指标没有同步提高。</li>
    </ul>
  </section>

  <div class="grid metrics">{cards}</div>

  <section>
    <h2>Align 共同训练提升了 restore 指标，尤其体现在 robust 和非 identity 视图</h2>
    <p>Stage C 在 full 和 curriculum 两条策略线上都优于对应的 Stage B。这个结论同时成立于 final checkpoint 与共同 epoch 20 的 checkpoint，因此可以把收益主要归因于 Stage C 的 restore + graph/align 共同训练，而不是训练轮数差异。</p>
    <img class="chart" src="{esc(stage_chart.relative_to(output.parent))}" alt="Stage C versus Stage B delta chart">
    {bc_table}
    <p class="note">口径：Stage B test 使用 identity test metrics；Stage C test 使用 all-view test metrics。Stage C 的 loss 使用 restore_loss 与 Stage B loss 对齐。</p>
  </section>

  <section>
    <h2>Stage C curriculum 提升 final/test canonical，但收益集中在 identity</h2>
    <p>Stage C curri 相比 Stage C full 的总体 valid canonical 提升 {pp(stage_c_delta["valid_canonical"])}，test canonical 提升 {pp(stage_c_delta["test_canonical"])}，但 final valid 的逐策略分解显示，主要增益来自 identity；attachment-rooted、random、direction 的 canonical 基本持平或略降。</p>
    <img class="chart" src="{esc(curri_chart.relative_to(output.parent))}" alt="Stage C curriculum versus full strategy delta chart">
    {html_table(["Strategy", "Canonical Δ", "Exact Δ", "RDKit Δ", "2-attach Δ"], strategy_delta_rows(runs["C_full"], runs["C_curri"]))}
  </section>

  <section>
    <h2>非 identity 视图显示 align 更像是在提升 SMILES 视图理解</h2>
    <p>Stage C full 对 Stage B full 的 final valid 分项提升集中在增强视图：rdkit_random +5.79 pp、direction_flip +6.65 pp、light_denoise +7.34 pp，而 identity 只提升 +1.81 pp。这说明共同训练不是只让模型更会复现规范字符串，而是提高了对不同 SMILES 表达视图的恢复稳定性。</p>
    {html_table(["Strategy", "Canonical Δ", "Exact Δ", "RDKit Δ", "2-attach Δ"], strategy_delta_rows(runs["B_full"], runs["C_full"]))}
  </section>

  <section>
    <h2>Retrieval 指标支持“字符串-图结构表征对齐”确实发生了</h2>
    <p>Stage C 才有 retrieval 指标，因此不能和 Stage B 直接横向比较 retrieval；但 Stage C 的 restore 指标没有被 retrieval/align 任务拖垮，同时 test text-to-graph top1 从 full 的 81.69% 到 curri 的 84.54%，说明字符串和图结构之间的表征对齐具备可观质量。</p>
    {html_table(["Run", "Valid text->graph top1", "Valid graph->text top1", "Test text->graph top1", "Test graph->text top1", "Test text->graph top5", "Test graph->text top5"], retrieval_rows(runs))}
  </section>

  <section>
    <h2>同 epoch 20 对照排除了“只因多训练”这一解释</h2>
    <p>Stage C final 30 epoch 确实比 Stage B 20 epoch多训练，但共同 epoch 20 下 Stage C 仍然高于 Stage B。这是判断 align 共同训练有效性的关键稳健性检查。</p>
    {html_table(["Comparison", "Canonical pair", "Canonical Δ", "Exact Δ", "RDKit Δ", "Loss Δ"], epoch20_rows(runs))}
  </section>

  <section>
    <h2>Scope, Definitions, and Caveats</h2>
    <p><b>比较对象。</b>Stage B 是 restore-only；Stage C 是 restore + align/retrieval 共同训练。Full 是静态 all-view；curriculum 是按 epoch 改变 strategy 权重但保持每 epoch 46,320 行训练量。</p>
    <p><b>主要指标。</b>Canonical/exact 衡量字符串恢复；RDKit validity 和 two-attachment validity 衡量结构合法性；robust valid/test 衡量增强/扰动视图上的泛化；retrieval 指标只存在于 Stage C，用于判断字符串和图结构表征对齐。</p>
    <p><b>限制。</b>Stage B final 是 20 epoch，Stage C final 是 30 epoch，因此 final-level B/C 对比包含训练轮数差异；本报告用 epoch 20 检查做了补充。Stage B 没有 retrieval 指标，所以 retrieval 只能作为 Stage C 内部证据，不能直接证明 B/C retrieval 差异。</p>
  </section>

  <section>
    <h2>Recommended Next Steps</h2>
    <ul>
      <li>保留 Stage C align 共同训练，因为它对 restore 没有负迁移，并且显著提升 robust 与增强视图表现。</li>
      <li>如果目标是最高 final/test canonical，优先 Stage C curriculum；如果目标是增强视图均衡和结构合法性，Stage C full 更稳。</li>
      <li>下一轮建议跑 Stage B 40 epoch 或 Stage C 20 epoch controlled ablation，以进一步隔离训练轮数、align loss 权重和 curriculum 的影响。</li>
      <li>建议单独扫描 random/direction/rooted 的 failure cases，看 Stage C curri 为什么 final valid 合法性略低于 full。</li>
    </ul>
  </section>

  <section>
    <h2>Headline Metrics Audit Table</h2>
    {headline_table}
  </section>

  <footer>Generated locally at {esc(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}. Source artifacts are under <code>reports/*_artifacts</code>; charts are static PNG assets in <code>{esc(asset_dir)}</code>.</footer>
</main>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage C strategy and align analysis HTML report.")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--asset-dir", type=Path, default=ASSET_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_report(args.output, args.asset_dir)
    print(json.dumps({"report": str(args.output), "asset_dir": str(args.asset_dir)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
