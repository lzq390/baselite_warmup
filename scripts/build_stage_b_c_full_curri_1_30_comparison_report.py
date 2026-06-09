from __future__ import annotations

import argparse
import base64
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
    "b_full": {
        "label": "Stage B full",
        "short": "B full",
        "artifacts": Path("reports/stage_b_restore_aug_v2_full_40epoch_artifacts_remote"),
        "color": "#64748b",
    },
    "b_curri": {
        "label": "Stage B curri",
        "short": "B curri",
        "artifacts": Path("reports/stage_b_restore_aug_v2_curriculum_full_40epoch_artifacts_remote"),
        "color": "#2563eb",
    },
    "c_full": {
        "label": "Stage C full",
        "short": "C full",
        "artifacts": Path("reports/stage_c_non_vocab_aug_v2_full_30epoch_artifacts"),
        "color": "#f97316",
    },
    "c_curri": {
        "label": "Stage C curri",
        "short": "C curri",
        "artifacts": Path("reports/stage_c_non_vocab_aug_v2_curriculum_full_30epoch_artifacts"),
        "color": "#14b8a6",
    },
}

STRATEGIES = [
    "identity",
    "attachment_rooted_smiles",
    "rdkit_random_smiles",
    "direction_flip",
    "light_denoise",
]

STRATEGY_MEANINGS = {
    "identity": "原始规范视图",
    "attachment_rooted_smiles": "attachment-rooted 视图",
    "rdkit_random_smiles": "RDKit random SMILES 视图",
    "direction_flip": "方向翻转视图",
    "light_denoise": "轻量去噪视图",
}

DEFAULT_OUTPUT = Path("reports/stage_b_c_full_curri_1_30epoch_detailed_comparison_report.html")
DEFAULT_ASSET_DIR = Path("reports/stage_b_c_full_curri_1_30epoch_assets")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def pp(value: float) -> str:
    return f"{value * 100:+.2f} pp"


def num(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def loss(row: dict[str, Any]) -> float:
    return float(row.get("restore_loss", row.get("loss", 0.0)))


def signed(value: float, *, lower_is_better: bool = False) -> str:
    if abs(value) < 0.0005:
        cls = "flat"
    else:
        good = value < 0 if lower_is_better else value > 0
        cls = "pos" if good else "neg"
    text = f"{value:+.4f}" if lower_is_better else pp(value)
    return f'<span class="{cls}">{esc(text)}</span>'


def val_bar(value: float) -> str:
    width = max(0.0, min(100.0, value * 100))
    alpha = 0.10 + 0.34 * max(0.0, min(1.0, value))
    return (
        f'<span class="val" style="background:linear-gradient(90deg, '
        f'rgba(37,99,235,{alpha:.3f}) {width:.2f}%, transparent {width:.2f}%);">{pct(value)}</span>'
    )


def image_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def table(headers: list[str], rows: list[list[Any]], *, class_name: str = "") -> str:
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="table-wrap {esc(class_name)}"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def load_runs() -> dict[str, list[dict[str, Any]]]:
    runs: dict[str, list[dict[str, Any]]] = {}
    for run_id, spec in RUNS.items():
        rows = read_jsonl(spec["artifacts"] / "epoch_metrics.jsonl")
        rows = [row for row in rows if 1 <= int(row["checkpoint_epoch"]) <= 30]
        if len(rows) != 30:
            raise ValueError(f"{run_id} has {len(rows)} rows in epoch 1-30, expected 30")
        runs[run_id] = rows
    return runs


def by_epoch(runs: dict[str, list[dict[str, Any]]]) -> dict[str, dict[int, dict[str, Any]]]:
    return {run_id: {int(row["checkpoint_epoch"]): row for row in rows} for run_id, rows in runs.items()}


def make_charts(runs: dict[str, list[dict[str, Any]]], asset_dir: Path) -> tuple[Path, Path]:
    asset_dir.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", font_scale=0.95)
    records: list[dict[str, Any]] = []
    for run_id, rows in runs.items():
        for row in rows:
            records.append(
                {
                    "Epoch": int(row["checkpoint_epoch"]),
                    "Run": RUNS[run_id]["short"],
                    "Canonical": float(row["canonical_match"]) * 100,
                    "Exact": float(row["exact_string_match"]) * 100,
                    "RDKit": float(row["rdkit_validity"]) * 100,
                    "Loss": loss(row),
                }
            )
    df = pd.DataFrame(records)

    palette = {spec["short"]: spec["color"] for spec in RUNS.values()}
    fig, ax = plt.subplots(figsize=(11.5, 5.6))
    sns.lineplot(data=df, x="Epoch", y="Canonical", hue="Run", marker="o", linewidth=2, ax=ax, palette=palette)
    ax.set_title("Valid canonical over aligned epochs 1-30")
    ax.set_ylabel("Canonical match (%)")
    ax.set_xlabel("Epoch")
    ax.set_xticks([1, 5, 10, 15, 20, 25, 30])
    ax.legend(loc="lower right", frameon=True)
    fig.tight_layout()
    canonical_path = asset_dir / "canonical_epoch_1_30.png"
    fig.savefig(canonical_path, dpi=180)
    plt.close(fig)

    metrics_df = df.melt(id_vars=["Epoch", "Run"], value_vars=["RDKit", "Exact"], var_name="Metric", value_name="Value")
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 5.2), sharex=True)
    for ax, metric in zip(axes, ["Exact", "RDKit"]):
        subset = metrics_df[metrics_df["Metric"] == metric]
        sns.lineplot(data=subset, x="Epoch", y="Value", hue="Run", marker="o", linewidth=2, ax=ax, palette=palette, legend=metric == "RDKit")
        ax.set_title(f"Valid {metric} over epochs 1-30")
        ax.set_ylabel(f"{metric} (%)")
        ax.set_xlabel("Epoch")
        ax.set_xticks([1, 5, 10, 15, 20, 25, 30])
    if axes[1].legend_:
        axes[1].legend(loc="lower right", frameon=True)
    fig.tight_layout()
    exact_rdkit_path = asset_dir / "exact_rdkit_epoch_1_30.png"
    fig.savefig(exact_rdkit_path, dpi=180)
    plt.close(fig)

    return canonical_path, exact_rdkit_path


def metric_cards(runs: dict[str, list[dict[str, Any]]]) -> str:
    cards = []
    for run_id in ["b_full", "b_curri", "c_full", "c_curri"]:
        rows = runs[run_id]
        best = max(rows, key=lambda row: float(row["canonical_match"]))
        final = rows[-1]
        cards.append(
            '<div class="metric">'
            f'<div class="metric-label">{esc(RUNS[run_id]["label"])}</div>'
            f'<div class="metric-value">{pct(float(best["canonical_match"]))}</div>'
            f'<div class="metric-note">best epoch {int(best["checkpoint_epoch"])} · epoch30 {pct(float(final["canonical_match"]))}</div>'
            "</div>"
        )
    return "".join(cards)


def summary_rows(runs: dict[str, list[dict[str, Any]]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for run_id in ["b_full", "b_curri", "c_full", "c_curri"]:
        run_rows = runs[run_id]
        best_can = max(run_rows, key=lambda row: float(row["canonical_match"]))
        best_loss = min(run_rows, key=loss)
        final = run_rows[-1]
        rows.append(
            [
                esc(RUNS[run_id]["label"]),
                f"epoch {int(best_can['checkpoint_epoch'])} · {pct(float(best_can['canonical_match']))}",
                f"epoch {int(best_loss['checkpoint_epoch'])} · {num(loss(best_loss))}",
                pct(float(final["canonical_match"])),
                pct(float(final["exact_string_match"])),
                pct(float(final["rdkit_validity"])),
                pct(float(final["two_attachment_validity"])),
                num(loss(final)),
            ]
        )
    return rows


def macro_rows(runs: dict[str, list[dict[str, Any]]]) -> list[list[Any]]:
    epoch_map = by_epoch(runs)
    rows: list[list[Any]] = []
    for epoch in range(1, 31):
        bf = epoch_map["b_full"][epoch]
        bc = epoch_map["b_curri"][epoch]
        cf = epoch_map["c_full"][epoch]
        cc = epoch_map["c_curri"][epoch]
        rows.append(
            [
                epoch,
                val_bar(float(bf["canonical_match"])),
                val_bar(float(bc["canonical_match"])),
                val_bar(float(cf["canonical_match"])),
                val_bar(float(cc["canonical_match"])),
                signed(float(cf["canonical_match"]) - float(bf["canonical_match"])),
                signed(float(cc["canonical_match"]) - float(bc["canonical_match"])),
                signed(float(bc["canonical_match"]) - float(bf["canonical_match"])),
                signed(float(cc["canonical_match"]) - float(cf["canonical_match"])),
                num(loss(bf)),
                num(loss(bc)),
                num(loss(cf)),
                num(loss(cc)),
            ]
        )
    return rows


def epoch_strategy_rows(runs: dict[str, list[dict[str, Any]]]) -> list[list[Any]]:
    epoch_map = by_epoch(runs)
    rows: list[list[Any]] = []
    for epoch in range(1, 31):
        for strategy in STRATEGIES:
            values = {
                run_id: epoch_map[run_id][epoch]["all_view_by_strategy"][strategy]
                for run_id in ["b_full", "b_curri", "c_full", "c_curri"]
            }
            rows.append(
                [
                    epoch,
                    f"<b>{esc(strategy)}</b><div class=\"sub\">{esc(STRATEGY_MEANINGS[strategy])}</div>",
                    val_bar(float(values["b_full"]["canonical_match"])),
                    val_bar(float(values["b_curri"]["canonical_match"])),
                    val_bar(float(values["c_full"]["canonical_match"])),
                    val_bar(float(values["c_curri"]["canonical_match"])),
                    signed(float(values["c_full"]["canonical_match"]) - float(values["b_full"]["canonical_match"])),
                    signed(float(values["c_curri"]["canonical_match"]) - float(values["b_curri"]["canonical_match"])),
                    val_bar(float(values["b_full"]["exact_string_match"])),
                    val_bar(float(values["b_curri"]["exact_string_match"])),
                    val_bar(float(values["c_full"]["exact_string_match"])),
                    val_bar(float(values["c_curri"]["exact_string_match"])),
                    val_bar(float(values["b_full"]["rdkit_validity"])),
                    val_bar(float(values["b_curri"]["rdkit_validity"])),
                    val_bar(float(values["c_full"]["rdkit_validity"])),
                    val_bar(float(values["c_curri"]["rdkit_validity"])),
                    f'{int(values["b_full"].get("failed_count", 0)):,} / {int(values["b_curri"].get("failed_count", 0)):,} / {int(values["c_full"].get("failed_count", 0)):,} / {int(values["c_curri"].get("failed_count", 0)):,}',
                ]
            )
    return rows


def strategy_best_rows(runs: dict[str, list[dict[str, Any]]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for strategy in STRATEGIES:
        cells: list[Any] = [f"<b>{esc(strategy)}</b><div class=\"sub\">{esc(STRATEGY_MEANINGS[strategy])}</div>"]
        best_by_run: dict[str, tuple[int, float]] = {}
        final_by_run: dict[str, float] = {}
        for run_id in ["b_full", "b_curri", "c_full", "c_curri"]:
            best = max(runs[run_id], key=lambda row: float(row["all_view_by_strategy"][strategy]["canonical_match"]))
            best_by_run[run_id] = (int(best["checkpoint_epoch"]), float(best["all_view_by_strategy"][strategy]["canonical_match"]))
            final_by_run[run_id] = float(runs[run_id][-1]["all_view_by_strategy"][strategy]["canonical_match"])
            cells.append(f"epoch {best_by_run[run_id][0]} · {pct(best_by_run[run_id][1])}<div class=\"sub\">epoch30 {pct(final_by_run[run_id])}</div>")
        cells.extend(
            [
                signed(best_by_run["c_full"][1] - best_by_run["b_full"][1]),
                signed(best_by_run["c_curri"][1] - best_by_run["b_curri"][1]),
                signed(final_by_run["c_full"] - final_by_run["b_full"]),
                signed(final_by_run["c_curri"] - final_by_run["b_curri"]),
            ]
        )
        rows.append(cells)
    return rows


def build_report(output: Path, asset_dir: Path) -> None:
    runs = load_runs()
    canonical_chart, exact_rdkit_chart = make_charts(runs, asset_dir)
    canonical_chart_uri = image_data_uri(canonical_chart)
    exact_rdkit_chart_uri = image_data_uri(exact_rdkit_chart)
    epoch_map = by_epoch(runs)

    cc30 = epoch_map["c_curri"][30]
    bc30 = epoch_map["b_curri"][30]
    cf30 = epoch_map["c_full"][30]
    bf30 = epoch_map["b_full"][30]
    ccurri_best = max(runs["c_curri"], key=lambda row: float(row["canonical_match"]))
    bcurri_best = max(runs["b_curri"], key=lambda row: float(row["canonical_match"]))

    css = """
:root{--bg:#f5f7fb;--panel:#fff;--ink:#172033;--muted:#647084;--line:#dbe3ee;--navy:#101827;--blue:#2563eb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"Noto Sans CJK SC","Microsoft YaHei",sans-serif}
header{background:var(--navy);color:#fff;padding:34px 40px 30px}header h1{margin:0 0 8px;font-size:28px;letter-spacing:0}header p{margin:0;color:#cbd5e1;max-width:1280px}
main{max-width:1580px;margin:0 auto;padding:28px 24px 54px}section{margin:0 0 24px}.card,.metric{background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 1px 2px rgba(15,23,42,.035)}.card{padding:18px}h2{font-size:19px;margin:0 0 12px}
.grid{display:grid;gap:14px}.metrics{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:22px}.metric{padding:14px 16px;min-height:96px}.metric-label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}.metric-value{font-size:25px;font-weight:760;margin:4px 0}.metric-note{color:var(--muted);font-size:12px}
.callout{border-left:4px solid var(--blue);background:#eff6ff;border-radius:0 8px 8px 0;padding:12px 14px}.chart{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff;margin:12px 0}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:8px;background:#fff;max-height:76vh}table{border-collapse:separate;border-spacing:0;width:100%;min-width:1200px}th,td{padding:8px 10px;border-bottom:1px solid var(--line);border-right:1px solid #eef2f7;vertical-align:middle;text-align:left;white-space:nowrap}th{position:sticky;top:0;background:#f8fafc;color:#475569;font-size:12px;text-transform:uppercase;letter-spacing:.04em;z-index:3}td:first-child,th:first-child{position:sticky;left:0;background:inherit;z-index:2}th:first-child{z-index:4}.compact table{min-width:980px}.sub{color:var(--muted);font-size:12px;margin-top:2px}.val{display:inline-block;min-width:76px;padding:2px 7px;border-radius:5px;border:1px solid rgba(148,163,184,.25);font-weight:650}.pos{color:#047857;font-weight:760}.neg{color:#b91c1c;font-weight:760}.flat{color:#64748b;font-weight:760}code{background:#eef2f7;border:1px solid #d9e2ec;padding:1px 5px;border-radius:5px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}footer{color:var(--muted);font-size:12px;margin-top:30px}@media(max-width:900px){header{padding:26px 20px}main{padding:20px 14px 40px}.metrics{grid-template-columns:1fr}.table-wrap{max-height:70vh}}
"""
    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage B/C Full/Curri Epoch 1-30 Detailed Comparison</title>
<style>{css}</style>
</head>
<body>
<header>
  <h1>Stage B/C Full/Curri Epoch 1-30 Detailed Comparison</h1>
  <p>对齐比较 Stage B full、Stage B curriculum、Stage C full、Stage C curriculum 在 epoch 1-30 的 valid full-decode checkpoint 指标。Stage B 使用 40epoch 完整 artifact，但本报告仅截取 1-30，避免把 Stage B epoch 31-40 的额外训练混入主对比。</p>
</header>
<main>
  <section class="card">
    <h2>Reading Notes</h2>
    <div class="callout">
      每个 run 均使用 <code>epoch_metrics.jsonl</code> 中的 valid checkpoint 指标；Stage C loss 使用 <code>restore_loss</code>，Stage B loss 使用 <code>loss</code>。主要 Delta：<b>C full - B full</b>、<b>C curri - B curri</b>、<b>B curri - B full</b>、<b>C curri - C full</b>。所有比较均限定 epoch 1-30。
    </div>
  </section>

  <section class="grid metrics">{metric_cards(runs)}</section>

  <section class="card">
    <h2>Key Takeaways at Epoch 30</h2>
    <div class="callout">
      epoch30 下，Stage C curri valid canonical 为 {pct(float(cc30["canonical_match"]))}，比 Stage B curri 高 {pp(float(cc30["canonical_match"]) - float(bc30["canonical_match"]))}；Stage C full 为 {pct(float(cf30["canonical_match"]))}，比 Stage B full 高 {pp(float(cf30["canonical_match"]) - float(bf30["canonical_match"]))}。
      在 1-30 范围内，Stage C curri 的 best canonical 是 epoch {int(ccurri_best["checkpoint_epoch"])} · {pct(float(ccurri_best["canonical_match"]))}，Stage B curri 是 epoch {int(bcurri_best["checkpoint_epoch"])} · {pct(float(bcurri_best["canonical_match"]))}。
    </div>
  </section>

  <section class="card">
    <h2>Canonical Trend by Epoch</h2>
    <img class="chart" src="{esc(canonical_chart_uri)}" alt="canonical trend">
  </section>

  <section class="card">
    <h2>Exact and RDKit Trend by Epoch</h2>
    <img class="chart" src="{esc(exact_rdkit_chart_uri)}" alt="exact and rdkit trend">
  </section>

  <section class="card compact">
    <h2>Run Summary within Epoch 1-30</h2>
    {table(["Run", "Best canonical", "Best loss", "Epoch30 canonical", "Epoch30 exact", "Epoch30 RDKit", "Epoch30 2-attach", "Epoch30 loss"], summary_rows(runs))}
  </section>

  <section class="card">
    <h2>Detailed Macro Epoch Metrics</h2>
    {table(["Epoch", "B Full Can", "B Curri Can", "C Full Can", "C Curri Can", "C Full - B Full", "C Curri - B Curri", "B Curri - B Full", "C Curri - C Full", "B Full Loss", "B Curri Loss", "C Full Restore Loss", "C Curri Restore Loss"], macro_rows(runs))}
  </section>

  <section class="card">
    <h2>Best Canonical by Strategy within Epoch 1-30</h2>
    {table(["Strategy", "B Full Best", "B Curri Best", "C Full Best", "C Curri Best", "Best C Full - B Full", "Best C Curri - B Curri", "Epoch30 C Full - B Full", "Epoch30 C Curri - B Curri"], strategy_best_rows(runs))}
  </section>

  <section class="card">
    <h2>Detailed Epoch × Strategy Valid Metrics</h2>
    {table(["Epoch", "Strategy", "B Full Can", "B Curri Can", "C Full Can", "C Curri Can", "Can CFull-BFull", "Can CCurri-BCurri", "B Full Exact", "B Curri Exact", "C Full Exact", "C Curri Exact", "B Full RDKit", "B Curri RDKit", "C Full RDKit", "C Curri RDKit", "Failed BFull/BCurri/CFull/CCurri"], epoch_strategy_rows(runs))}
  </section>

  <section class="card compact">
    <h2>Source Artifacts</h2>
    {table(["Run", "Artifact directory", "Rows used"], [[esc(RUNS[k]["label"]), f"<code>{esc(v['artifacts'])}</code>", "epoch 1-30"] for k, v in RUNS.items()])}
  </section>

  <footer>Generated locally at {esc(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}. Report file: <code>{esc(output)}</code>.</footer>
</main>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage B/C full/curri epoch 1-30 detailed comparison HTML report.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_report(args.output, args.asset_dir)
    print(json.dumps({"report": str(args.output), "asset_dir": str(args.asset_dir)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
