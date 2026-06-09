from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


DEFAULT_STAGE_C_ARTIFACTS = Path("reports/stage_c_non_vocab_aug_v2_full_30epoch_artifacts")
DEFAULT_STAGE_B_ARTIFACTS = Path("reports/stage_b_restore_aug_v2_full_20epoch_artifacts")
DEFAULT_STAGE_C_REPORT = Path("reports/stage_c_non_vocab_aug_v2_full_30epoch_report.html")
DEFAULT_STAGE_B_STAGE_C_REPORT = Path("reports/stage_b_stage_c_aug_v2_full_comparison_report.html")

STRATEGY_COLORS = {
    "identity": "#16a34a",
    "rdkit_random_smiles": "#f97316",
    "direction_flip": "#9333ea",
    "attachment_rooted_smiles": "#0891b2",
    "light_denoise": "#eab308",
}

STRATEGY_MEANINGS = {
    "identity": "原始规范视图",
    "rdkit_random_smiles": "RDKit random SMILES 视图",
    "direction_flip": "方向翻转视图",
    "attachment_rooted_smiles": "attachment-rooted 视图",
    "light_denoise": "轻量去噪视图",
}

RESTORE_METRICS = {
    "canonical_match": ("Canonical Match", "#2563eb", "语义/规范化匹配"),
    "exact_string_match": ("Exact String Match", "#7c3aed", "字符串完全一致"),
    "rdkit_validity": ("RDKit Validity", "#dc2626", "RDKit 可解析"),
    "two_attachment_validity": ("Two Attachment Validity", "#ea580c", "两个连接点合法"),
}


BASE_CSS = """
:root { --bg:#f5f7fb; --panel:#fff; --ink:#172033; --muted:#647084; --line:#dbe3ee; --soft:#eef3f8; --navy:#101827; --blue:#2563eb; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif; }
header { background:var(--navy); color:#fff; padding:34px 40px 30px; }
header h1 { margin:0 0 8px; font-size:28px; letter-spacing:0; }
header p { margin:0; color:#cbd5e1; max-width:1100px; }
main { max-width:1260px; margin:0 auto; padding:28px 24px 54px; }
section { margin:0 0 24px; }
h2 { font-size:19px; margin:0 0 13px; letter-spacing:0; }
h3 { font-size:15px; margin:0 0 11px; letter-spacing:0; }
.card,.chart-card,.bar-card,.metric,.mini-chart { background:var(--panel); border:1px solid var(--line); border-radius:8px; box-shadow:0 1px 2px rgba(15,23,42,.035); }
.card { padding:18px; }
.grid { display:grid; gap:14px; }
.grid.metrics { grid-template-columns:repeat(3,minmax(0,1fr)); }
.grid.two { grid-template-columns:repeat(2,minmax(0,1fr)); }
.metric { padding:14px 16px; min-height:96px; }
.metric-label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em; }
.metric-value { font-size:27px; font-weight:740; margin:4px 0 2px; letter-spacing:0; }
.metric-note { color:var(--muted); font-size:12px; }
.strategy-box { display:grid; grid-template-columns:1.05fr .95fr; gap:16px; align-items:start; }
.callout { border-left:4px solid var(--blue); background:#eff6ff; border-radius:0 8px 8px 0; padding:12px 14px; }
.table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:#fff; }
table { width:100%; border-collapse:collapse; min-width:760px; }
th,td { padding:9px 11px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }
th { background:#f8fafc; color:#475569; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
tr:last-child td { border-bottom:0; }
code { background:#eef2f7; border:1px solid #d9e2ec; padding:1px 5px; border-radius:5px; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12px; }
.pill { display:inline-block; padding:2px 8px; border-radius:999px; font-weight:680; font-size:12px; }
.pill.ok { background:#d9f5ef; color:#075e54; }
.pill.warn { background:#fff2cc; color:#92400e; }
.pill.good { background:#dbeafe; color:#1d4ed8; }
.dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:7px; vertical-align:middle; }
.chart-card { padding:13px; }
.chart-title { display:flex; justify-content:space-between; gap:12px; align-items:baseline; font-weight:730; margin:0 0 8px; }
.chart-title em { color:var(--muted); font-style:normal; font-weight:500; }
svg { display:block; width:100%; height:auto; }
.gridline { stroke:#e6ebf2; stroke-width:1; }
.axis { fill:#64748b; font-size:11px; }
.axis-line { stroke:#94a3b8; stroke-width:1; }
.legend { display:flex; gap:14px; flex-wrap:wrap; margin-top:8px; color:#475569; }
.legend-item { display:inline-flex; align-items:center; gap:6px; }
.swatch { width:12px; height:12px; border-radius:3px; display:inline-block; }
.mini-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
.mini-chart { padding:12px; }
.mini-head { display:flex; justify-content:space-between; gap:10px; font-weight:730; }
.mini-head b { font-size:17px; }
.mini-desc { color:var(--muted); font-size:12px; margin:3px 0 6px; }
.bar-card { padding:15px; }
.bar-row { display:grid; grid-template-columns:220px 1fr 76px; grid-template-areas:"name track num" "extra track num"; gap:3px 12px; align-items:center; padding:8px 0; border-bottom:1px solid #edf1f6; }
.bar-row:last-child { border-bottom:0; }
.bar-name { grid-area:name; min-width:0; }
.bar-name b { display:block; font-size:13px; color:#1e293b; overflow-wrap:anywhere; }
.bar-name span { display:block; color:var(--muted); font-size:12px; }
.bar-track { grid-area:track; height:18px; background:#eef2f7; border-radius:999px; overflow:hidden; border:1px solid #e2e8f0; }
.bar-fill { height:100%; border-radius:999px; }
.bar-num { grid-area:num; font-weight:760; font-size:14px; text-align:right; color:#111827; }
.bar-extra { grid-area:extra; color:var(--muted); font-size:12px; }
.bar-note,.note { color:var(--muted); font-size:12px; margin-top:8px; }
.cmp-row{display:grid;grid-template-columns:190px 1fr 82px;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid #edf1f6}
.cmp-row:last-child{border-bottom:0}.cmp-label{font-weight:700}.cmp-line{display:grid;grid-template-columns:42px 1fr 70px;gap:8px;align-items:center;margin:3px 0}.cmp-line span{color:var(--muted);font-size:12px}.cmp-track{height:13px;border-radius:999px;background:#eef2f7;overflow:hidden}.cmp-track i{display:block;height:100%;border-radius:999px}.cmp-line b{font-size:12px;text-align:right}.cmp-delta{font-weight:760;text-align:right}.cmp-delta.pos{color:#047857}.cmp-delta.neg{color:#b91c1c}
.delta{font-size:16px;margin-left:8px}.delta.pos{color:#047857}.delta.neg{color:#b91c1c}
footer { color:var(--muted); font-size:12px; margin-top:30px; }
@media (max-width:900px) {
  header { padding:26px 20px; } main { padding:20px 14px 40px; }
  .grid.metrics,.grid.two,.mini-grid,.strategy-box { grid-template-columns:1fr; }
  .bar-row { grid-template-columns:1fr 64px; grid-template-areas:"name num" "track track" "extra extra"; }
  .cmp-row{grid-template-columns:1fr}.cmp-delta{text-align:left}
  table { min-width:720px; }
}
"""


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_optional(path: Path) -> dict[str, Any] | None:
    return read_json(path) if path.exists() else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def num(value: float | int | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:.{digits}f}"


def pp(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:+.2f} pp"


def table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<div class=\"table-wrap\"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def metric(label: str, value: str, note: str) -> str:
    return (
        '<div class="metric">'
        f'<div class="metric-label">{esc(label)}</div>'
        f'<div class="metric-value">{value}</div>'
        f'<div class="metric-note">{note}</div>'
        "</div>"
    )


def pill(ok: bool, text: str | None = None) -> str:
    return f'<span class="pill {"ok" if ok else "warn"}">{esc(text or ("PASS" if ok else "CHECK"))}</span>'


def rate_with_count(rate: float | None, total: int | None) -> str:
    if rate is None:
        return "-"
    if total:
        return f"{pct(rate)} <span class=\"note\">({round(rate * total):,}/{total:,})</span>"
    return pct(rate)


def metric_value(metrics: dict[str, Any] | None, key: str) -> float | None:
    if not metrics:
        return None
    value = metrics.get(key)
    return float(value) if value is not None else None


def restore_loss(metrics: dict[str, Any] | None) -> float | None:
    if not metrics:
        return None
    value = metrics.get("restore_loss", metrics.get("loss"))
    return float(value) if value is not None else None


def test_metrics_for_stage_b(artifacts: Path) -> dict[str, Any]:
    return read_json_optional(artifacts / "all_view_test_eval_metrics.json") or read_json(artifacts / "identity_test_eval_metrics.json")


def line_svg(
    values: list[float],
    *,
    color: str,
    width: int = 312,
    height: int = 112,
    y_min: float | None = None,
    y_max: float | None = None,
    label: Callable[[float], str] = lambda value: f"{value:.2f}",
) -> str:
    if not values:
        return ""
    if len(values) == 1:
        values = values + values
    lo = min(values) if y_min is None else y_min
    hi = max(values) if y_max is None else y_max
    if hi <= lo:
        hi = lo + 1.0
    pad_left = 34
    pad_top = 12
    pad_bottom = 24
    plot_width = width - pad_left - 12
    plot_height = height - pad_top - pad_bottom
    coords = []
    for index, value in enumerate(values):
        x = pad_left + index * plot_width / (len(values) - 1)
        y = pad_top + (hi - value) / (hi - lo) * plot_height
        coords.append((x, y))
    path = " ".join(("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}" for i, (x, y) in enumerate(coords))
    grid = []
    for tick in [lo, (lo + hi) / 2, hi]:
        y = pad_top + (hi - tick) / (hi - lo) * plot_height
        grid.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width-12}" y2="{y:.1f}" class="gridline"/>')
        grid.append(f'<text x="{pad_left-7}" y="{y+3:.1f}" class="axis" text-anchor="end">{esc(label(tick))}</text>')
    epoch_labels = [
        (pad_left, "1"),
        (pad_left + plot_width / 2, str(round((len(values) + 1) / 2))),
        (pad_left + plot_width, str(len(values))),
    ]
    axis_labels = "".join(
        f'<text x="{x:.1f}" y="{height-7}" class="axis" text-anchor="middle">{esc(text)}</text>' for x, text in epoch_labels
    )
    circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.4" fill="{color}"/>' for x, y in coords)
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img">'
        f'<rect width="{width}" height="{height}" rx="8" fill="#ffffff"/>'
        + "".join(grid)
        + axis_labels
        + f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/>'
        + circles
        + "</svg>"
    )


def multi_line_svg(
    series: list[tuple[str, list[float], str]],
    *,
    width: int = 900,
    height: int = 260,
    y_min: float | None = None,
    y_max: float | None = None,
    y_label: Callable[[float], str] = lambda value: f"{value:.2f}",
) -> str:
    values = [value for _, seq, _ in series for value in seq]
    if not values:
        return ""
    n = max(len(seq) for _, seq, _ in series)
    lo = min(values) if y_min is None else y_min
    hi = max(values) if y_max is None else y_max
    if hi <= lo:
        hi = lo + 1.0
    pad_left = 58
    pad_top = 28
    pad_bottom = 42
    plot_width = width - pad_left - 20
    plot_height = height - pad_top - pad_bottom
    grid = []
    for tick in [lo, lo + (hi - lo) / 4, lo + (hi - lo) / 2, lo + 3 * (hi - lo) / 4, hi]:
        y = pad_top + (hi - tick) / (hi - lo) * plot_height
        grid.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width-20}" y2="{y:.1f}" class="gridline"/>')
        grid.append(f'<text x="{pad_left-10}" y="{y+4:.1f}" class="axis" text-anchor="end">{esc(y_label(tick))}</text>')
    axis = (
        f'<line x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{height-pad_bottom}" class="axis-line"/>'
        f'<line x1="{pad_left}" y1="{height-pad_bottom}" x2="{width-20}" y2="{height-pad_bottom}" class="axis-line"/>'
        f'<text x="{pad_left:.1f}" y="{height-16}" class="axis" text-anchor="middle">1</text>'
        f'<text x="{pad_left + plot_width/2:.1f}" y="{height-16}" class="axis" text-anchor="middle">{round((n + 1) / 2)}</text>'
        f'<text x="{width-20:.1f}" y="{height-16}" class="axis" text-anchor="middle">{n}</text>'
    )
    paths = []
    for _, seq, color in series:
        coords = []
        for index, value in enumerate(seq):
            x = pad_left + index * plot_width / (len(seq) - 1)
            y = pad_top + (hi - value) / (hi - lo) * plot_height
            coords.append((x, y))
        path = " ".join(("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}" for i, (x, y) in enumerate(coords))
        paths.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>')
    return f'<svg viewBox="0 0 {width} {height}" role="img"><rect width="{width}" height="{height}" rx="8" fill="#fff"/>' + "".join(grid) + axis + "".join(paths) + "</svg>"


def bar_row(strategy: str, values: dict[str, Any]) -> str:
    rate = float(values["canonical_match"])
    sample_count = int(values.get("sample_count") or 0)
    failed_count = int(values.get("failed_count") or round((1 - rate) * sample_count))
    color = STRATEGY_COLORS.get(strategy, "#2563eb")
    return f"""
      <div class="bar-row">
        <div class="bar-name"><b>{esc(strategy)}</b><span>{esc(STRATEGY_MEANINGS.get(strategy, ""))}</span></div>
        <div class="bar-track"><div class="bar-fill" style="width:{rate * 100:.2f}%; background:{color}"></div></div>
        <div class="bar-num">{pct(rate)}</div>
        <div class="bar-extra">n={sample_count:,} · failed={failed_count:,}</div>
      </div>"""


def sorted_strategy_items(values: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return sorted(values.items(), key=lambda item: float(item[1].get("canonical_match", 0)), reverse=True)


def strategy_inventory_rows(metrics: dict[str, Any], key: str = "all_view_by_strategy") -> list[list[Any]]:
    rows = []
    for strategy, values in sorted_strategy_items(metrics.get(key) or {}):
        rows.append(
            [
                f'<span class="dot" style="background:{STRATEGY_COLORS.get(strategy, "#2563eb")}"></span><b>{esc(strategy)}</b>',
                esc(STRATEGY_MEANINGS.get(strategy, "")),
                f"{int(values.get('sample_count', 0)):,}",
                pct(float(values.get("canonical_match", 0))),
                pct(float(values.get("rdkit_validity", 0))),
            ]
        )
    return rows


def human_size(byte_count: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(byte_count)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{byte_count:,} B"


def derived_failure_reason(row: dict[str, Any]) -> str:
    reason = row.get("failure_reason")
    if reason:
        return str(reason)
    if not row.get("rdkit_valid"):
        return "rdkit_parse_failed"
    if not row.get("two_attachment_valid"):
        return "attachment_count_not_two"
    return "canonical_mismatch"


def artifact_rows(artifacts: Path) -> list[list[Any]]:
    rows = []
    for path in sorted(artifacts.iterdir(), key=lambda item: item.name):
        if path.is_file():
            rows.append([f"<code>{esc(path.name)}</code>", esc(human_size(path.stat().st_size))])
    return rows


def formal_rows_stage_c(
    final_valid: dict[str, Any],
    final_test: dict[str, Any],
    robustness_valid: dict[str, Any],
    robustness_test: dict[str, Any],
) -> list[list[Any]]:
    rows = []
    for label, metrics in [
        ("Final valid", final_valid),
        ("Final test", final_test),
        ("Robustness valid", robustness_valid),
        ("Robustness test", robustness_test),
    ]:
        rows.append(
            [
                esc(label),
                f"{int(metrics.get('sample_count', 0)):,}",
                f"{int(metrics.get('decoded_sample_count', 0)):,}",
                f"{int(metrics.get('retrieval_sample_count', 0)):,}",
                num(float(metrics.get("loss", 0)), 4),
                num(restore_loss(metrics), 4),
                pct(float(metrics.get("token_accuracy", 0))),
                pct(float(metrics.get("exact_string_match", 0))),
                pct(float(metrics.get("canonical_match", 0))),
                pct(float(metrics.get("rdkit_validity", 0))),
                pct(float(metrics.get("two_attachment_validity", 0))),
            ]
        )
    return rows


def format_report_page(title: str, subtitle: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{BASE_CSS}</style>
</head>
<body>
<header>
  <h1>{esc(title)}</h1>
  <p>{subtitle}</p>
</header>
<main>
{body}
</main>
</body>
</html>
"""


def build_stage_c_report(stage_c_artifacts: Path, output_path: Path) -> None:
    epoch_rows = read_jsonl(stage_c_artifacts / "epoch_metrics.jsonl")
    final_valid = read_json(stage_c_artifacts / "eval_metrics.json")
    final_test = read_json(stage_c_artifacts / "all_view_test_eval_metrics.json")
    robustness_valid = read_json(stage_c_artifacts / "robustness_valid_eval_metrics.json")
    robustness_test = read_json(stage_c_artifacts / "robustness_test_eval_metrics.json")
    config = read_json(stage_c_artifacts / "training_config.json")
    reload_check = read_json(stage_c_artifacts / "reload_check.json")

    final_epoch = epoch_rows[-1]
    first_epoch = epoch_rows[0]
    monitor_best = final_valid.get("best_early_stopping_checkpoint") or min(epoch_rows, key=lambda row: float(row["restore_loss"]))["checkpoint_name"]
    monitor_best_metric = final_valid.get("best_early_stopping_metric")
    raw_restore_best = min(epoch_rows, key=lambda row: float(row["restore_loss"]))
    canonical_best = max(epoch_rows, key=lambda row: float(row["canonical_match"]))

    cards = "".join(
        [
            metric("Final valid canonical", pct(final_valid["canonical_match"]), f"all-view macro · {int(final_valid['decoded_sample_count']):,} decode"),
            metric("Final test canonical", pct(final_test["canonical_match"]), f"all-view macro · {int(final_test['decoded_sample_count']):,} decode"),
            metric("Robustness valid canonical", pct(robustness_valid["canonical_match"]), f"4 non-identity strategies · {int(robustness_valid['decoded_sample_count']):,} decode"),
            metric("Robustness test canonical", pct(robustness_test["canonical_match"]), f"4 non-identity strategies · {int(robustness_test['decoded_sample_count']):,} decode"),
            metric("Best monitor checkpoint", esc(monitor_best), f"restore_loss {num(float(monitor_best_metric), 4)}"),
            metric("Final checkpoint", esc(final_epoch["checkpoint_name"]), f"loss {num(float(final_valid['loss']), 4)} · step {int(final_valid['optimizer_steps']):,}"),
        ]
    )

    strategy_table = table(["Strategy", "Meaning", "Valid Samples", "Final Canonical", "Final RDKit Valid"], strategy_inventory_rows(final_valid))

    full_decode_rows = [
        ["v2 数据路径", pill(config.get("preview_path") == "data/baselite_smiles_aug_v2/training_template_preview.jsonl"), esc(config.get("preview_path"))],
        ["训练 epoch 数", pill(final_valid.get("completed_epochs") == config.get("max_epochs")), f"completed={final_valid.get('completed_epochs')}, max={config.get('max_epochs')}"],
        ["每个 checkpoint valid 全量 decode", pill(all(row.get("decoded_sample_count") == row.get("sample_count") for row in epoch_rows)), f"{len(epoch_rows)} checkpoints × {int(final_valid['valid_sample_count']):,}"],
        ["final valid 全量 decode", pill(final_valid.get("decoded_sample_count") == final_valid.get("sample_count")), f"{int(final_valid['decoded_sample_count']):,}/{int(final_valid['sample_count']):,}"],
        ["final test 全量 decode", pill(final_test.get("decoded_sample_count") == final_test.get("sample_count")), f"{int(final_test['decoded_sample_count']):,}/{int(final_test['sample_count']):,}"],
        ["robustness valid 全量 decode", pill(robustness_valid.get("decoded_sample_count") == robustness_valid.get("sample_count")), f"{int(robustness_valid['decoded_sample_count']):,}/{int(robustness_valid['sample_count']):,}"],
        ["robustness test 全量 decode", pill(robustness_test.get("decoded_sample_count") == robustness_test.get("sample_count")), f"{int(robustness_test['decoded_sample_count']):,}/{int(robustness_test['sample_count']):,}"],
        ["正式 eval 未使用 decode 限制", pill(config.get("checkpoint_eval_decode_samples") == 0 and config.get("eval_decode_samples") == 0), "checkpoint_eval_decode_samples=0, eval_decode_samples=0"],
        ["retrieval 去重评估", pill(final_valid.get("formal_eval_dedup_retrieval") is True), f"valid/test retrieval_sample_count={int(final_valid['retrieval_sample_count']):,}"],
        ["早停只监控不打断", pill(final_valid.get("early_stopping_monitor_only") is True and not final_valid.get("early_stopped")), "monitor_only=True, early_stopped=False"],
        ["reload check", pill(reload_check.get("status") == "passed"), esc(reload_check.get("status"))],
    ]

    mini_charts = []
    for key, (label_text, color, desc) in RESTORE_METRICS.items():
        values = [float(row[key]) for row in epoch_rows]
        mini_charts.append(
            f"""<div class="mini-chart">
          <div class="mini-head"><span><span class="dot" style="background:{color}"></span>{esc(label_text)}</span><b>{pct(float(final_valid[key]))}</b></div>
          <div class="mini-desc">{esc(desc)} · first {pct(float(first_epoch[key]))} · best {pct(max(values))}</div>
          {line_svg(values, color=color, y_min=0, y_max=1, label=lambda value: f"{value*100:.0f}%")}
        </div>"""
        )

    loss_svg = multi_line_svg(
        [
            ("total loss", [float(row["loss"]) for row in epoch_rows], "#2563eb"),
            ("restore loss", [float(row["restore_loss"]) for row in epoch_rows], "#0f766e"),
            ("0.2 x align", [float(row["weighted_align_loss"]) for row in epoch_rows], "#64748b"),
        ],
        y_label=lambda value: f"{value:.2f}",
    )
    retrieval_svg = multi_line_svg(
        [
            ("text->graph top1", [float(row["text_to_graph_top1"]) for row in epoch_rows], "#2563eb"),
            ("graph->text top1", [float(row["graph_to_text_top1"]) for row in epoch_rows], "#b8a037"),
            ("text->graph top5", [float(row["text_to_graph_top5"]) for row in epoch_rows], "#0f766e"),
            ("graph->text top5", [float(row["graph_to_text_top5"]) for row in epoch_rows], "#ea580c"),
        ],
        y_min=0,
        y_max=1,
        y_label=lambda value: f"{value*100:.0f}%",
    )

    final_strategy_bars = "".join(bar_row(strategy, values) for strategy, values in sorted_strategy_items(final_valid.get("all_view_by_strategy") or {}))
    robustness_strategy_bars = "".join(bar_row(strategy, values) for strategy, values in sorted_strategy_items(robustness_test.get("robustness_by_strategy") or {}))

    best_rows = [
        ["First checkpoint", esc(first_epoch["checkpoint_name"]), num(float(first_epoch["restore_loss"]), 4), pct(float(first_epoch["canonical_match"])), pct(float(first_epoch["token_accuracy"]))],
        ["Monitor best checkpoint", esc(monitor_best), num(float(monitor_best_metric), 4), pct(next(float(row["canonical_match"]) for row in epoch_rows if row["checkpoint_name"] == monitor_best)), "restore_loss monitor"],
        ["Raw restore-loss best", esc(raw_restore_best["checkpoint_name"]), num(float(raw_restore_best["restore_loss"]), 4), pct(float(raw_restore_best["canonical_match"])), pct(float(raw_restore_best["token_accuracy"]))],
        ["Best valid canonical", esc(canonical_best["checkpoint_name"]), num(float(canonical_best["restore_loss"]), 4), pct(float(canonical_best["canonical_match"])), pct(float(canonical_best["token_accuracy"]))],
        ["Final checkpoint", esc(final_epoch["checkpoint_name"]), num(float(final_valid["restore_loss"]), 4), pct(float(final_valid["canonical_match"])), pct(float(final_valid["token_accuracy"]))],
    ]

    retrieval_rows = [
        ["Final valid", f"{int(final_valid['retrieval_sample_count']):,}", pct(final_valid["text_to_graph_top1"]), pct(final_valid["text_to_graph_top5"]), pct(final_valid["graph_to_text_top1"]), pct(final_valid["graph_to_text_top5"]), num(float(final_valid["mean_positive_similarity"]), 4), num(float(final_valid["mean_negative_similarity"]), 4)],
        ["Final test", f"{int(final_test['retrieval_sample_count']):,}", pct(final_test["text_to_graph_top1"]), pct(final_test["text_to_graph_top5"]), pct(final_test["graph_to_text_top1"]), pct(final_test["graph_to_text_top5"]), num(float(final_test["mean_positive_similarity"]), 4), num(float(final_test["mean_negative_similarity"]), 4)],
    ]

    robustness_breakdown_rows = []
    for label, metrics in [("Robustness valid", robustness_valid), ("Robustness test", robustness_test)]:
        for strategy, values in sorted_strategy_items(metrics.get("robustness_by_strategy") or {}):
            robustness_breakdown_rows.append(
                [
                    esc(label),
                    f'<span class="dot" style="background:{STRATEGY_COLORS.get(strategy, "#2563eb")}"></span><b>{esc(strategy)}</b>',
                    f"{int(values.get('sample_count', 0)):,}",
                    f"{int(values.get('failed_count', 0)):,}",
                    pct(float(values.get("exact_string_match", 0))),
                    pct(float(values.get("canonical_match", 0))),
                    pct(float(values.get("rdkit_validity", 0))),
                    pct(float(values.get("two_attachment_validity", 0))),
                ]
            )

    epoch_checkpoint_rows = []
    for row in epoch_rows:
        early_stopping = row.get("early_stopping") or {}
        epoch_checkpoint_rows.append(
            [
                int(row.get("checkpoint_epoch", 0)),
                esc(row.get("checkpoint_name")),
                f"{int(row.get('checkpoint_optimizer_step', 0)):,}",
                num(float(row.get("loss", 0)), 4),
                num(float(row.get("restore_loss", 0)), 4),
                num(float(row.get("weighted_align_loss", 0)), 4),
                pct(float(row.get("token_accuracy", 0))),
                pct(float(row.get("canonical_match", 0))),
                pct(float(row.get("rdkit_validity", 0))),
                pct(float(row.get("two_attachment_validity", 0))),
                esc(early_stopping.get("best_checkpoint")),
                f'<span class="pill {"warn" if early_stopping.get("would_stop_training") else "ok"}">{"would stop" if early_stopping.get("would_stop_training") else "continue"}</span>',
            ]
        )

    failure_rows = []
    first_failure_examples = []
    for label, file_name in [
        ("Final valid", "failed_cases.jsonl"),
        ("Final test", "all_view_test_failed_cases.jsonl"),
        ("Robustness valid", "robustness_valid_failed_cases.jsonl"),
        ("Robustness test", "robustness_test_failed_cases.jsonl"),
    ]:
        rows = read_jsonl(stage_c_artifacts / file_name)
        invalid_count = sum(1 for row in rows if not row.get("rdkit_valid"))
        attachment_invalid_count = sum(1 for row in rows if not row.get("two_attachment_valid"))
        strategy_counts = Counter(row.get("augmentation_strategy", "unknown") for row in rows)
        reason_counts = Counter(derived_failure_reason(row) for row in rows)
        total = len(rows)
        failure_rows.append(
            [
                esc(label),
                f"{total:,}",
                f"{invalid_count:,}",
                f"{attachment_invalid_count:,}",
                esc(", ".join(f"{key}: {value}" for key, value in strategy_counts.most_common(3))),
                esc(", ".join(f"{key}: {value}" for key, value in reason_counts.most_common(3))),
            ]
        )
        if label == "Final valid":
            for index, row in enumerate(rows[:8], start=1):
                first_failure_examples.append(
                    [
                        index,
                        esc(row.get("record_id")),
                        esc(row.get("augmentation_strategy")),
                        esc(derived_failure_reason(row)),
                        f"<code>{esc(row.get('text_view_1'))}</code>",
                        f"<code>{esc(row.get('decoded_smiles'))}</code>",
                        f"<code>{esc(row.get('target'))}</code>",
                    ]
                )

    body = f"""
  <section class="grid metrics">{cards}</section>

  <section class="card">
    <h2>Training Strategy</h2>
    <div class="strategy-box">
      <div class="callout">
        <b>当前策略：Stage C static full all-view。</b> 每个 epoch 固定遍历 v2 train 全量 46,320 行；模型在 restore 目标之外额外启用 graph encoder / projectors，并优化 <code>L_restore + 0.2 * L_align</code>。
      </div>
      {table(["Item", "Value"], [
          ["Strategy label", "<b>Stage C static full all-view training</b>"],
          ["Dataset", f"<code>{esc(config.get('preview_path'))}</code>"],
          ["Graph source", f"<code>{esc(config.get('graph_path'))}</code>"],
          ["Epoch policy", f"每个 epoch 固定使用 v2 train 全量 <b>{int(final_valid['train_sample_count']):,}</b> 行；不按 epoch 改变策略权重。"],
          ["Objective", f"<code>L_restore * {config.get('restore_loss_weight')} + L_align * {config.get('align_loss_weight')}</code>"],
          ["Strategy coverage", "5 个 v2 策略全量覆盖：identity、rdkit_random_smiles、direction_flip、attachment_rooted_smiles、light_denoise。"],
          ["Contrast target", "用于对照 Stage B restore-only full；横比时只直接比较 restore 指标，不比较 Stage C joint loss。"],
          ["Output dir", f"<code>{esc(config.get('output_dir'))}</code>"],
      ])}
    </div>
    <h3 style="margin-top:16px">Strategy Inventory</h3>
    {strategy_table}
  </section>

  <section class="card">
    <h2>Full-Decode Standard Check</h2>
    {table(["Check", "Status", "Detail"], full_decode_rows)}
    <p class="note">Quick eval 仍是轻量观察口径；正式 checkpoint/final/robustness 指标均使用全量 decode。Robustness split 的 retrieval 指标按设计跳过，因为这些样本是重复 graph view。</p>
  </section>

  <section class="card">
    <h2>Formal Metrics</h2>
    {table(["Split", "Samples", "Decoded", "Retrieval", "Loss", "Restore Loss", "Token Acc.", "Exact", "Canonical", "RDKit Valid", "Two Attach."], formal_rows_stage_c(final_valid, final_test, robustness_valid, robustness_test))}
  </section>

  <section class="card">
    <h2>Figure 1 · Checkpoint Metric Trends</h2>
    <p class="note">四个 restore 指标拆成独立小图，保持和 Stage B full 报告一致；Stage C 的 extra retrieval/align 信息放在后续图表。</p>
    <div class="mini-grid">{''.join(mini_charts)}</div>
  </section>

  <section class="grid two">
    <div class="chart-card">
      <div class="chart-title"><span>Checkpoint Loss Trend</span><em>joint objective</em></div>
      {loss_svg}
      <div class="legend"><span class="legend-item"><span class="swatch" style="background:#2563eb"></span>total loss</span><span class="legend-item"><span class="swatch" style="background:#0f766e"></span>restore loss</span><span class="legend-item"><span class="swatch" style="background:#64748b"></span>0.2 x align</span></div>
    </div>
    <div class="chart-card">
      <div class="chart-title"><span>Retrieval Trend</span><em>deduplicated graph records</em></div>
      {retrieval_svg}
      <div class="legend"><span class="legend-item"><span class="swatch" style="background:#2563eb"></span>text→graph top1</span><span class="legend-item"><span class="swatch" style="background:#b8a037"></span>graph→text top1</span><span class="legend-item"><span class="swatch" style="background:#0f766e"></span>text→graph top5</span><span class="legend-item"><span class="swatch" style="background:#ea580c"></span>graph→text top5</span></div>
    </div>
  </section>

  <section class="card">
    <h2>Best vs Final</h2>
    {table(["Point", "Checkpoint", "Restore Loss", "Canonical", "Token Acc."], best_rows)}
    <p class="note">Early-stopping monitor 使用 min_delta=0.001，因此记录的 monitor best 与 raw restore-loss 最低点可能不同；本报告两者都列出。</p>
  </section>

  <section class="card">
    <h2>Figure 2 · Strategy Comparison</h2>
    <div class="grid two">
      <div class="bar-card"><h3>Final Valid Canonical Match by Strategy</h3>{final_strategy_bars}</div>
      <div class="bar-card"><h3>Robustness Test Canonical Match by Strategy</h3>{robustness_strategy_bars}<p class="bar-note">Robustness test 排除 identity，只看 4 个非 identity view。</p></div>
    </div>
  </section>

  <section class="card">
    <h2>Stage C Retrieval Summary</h2>
    {table(["Split", "Retrieval Samples", "Text→Graph Top1", "Text→Graph Top5", "Graph→Text Top1", "Graph→Text Top5", "Mean Positive Sim.", "Mean Negative Sim."], retrieval_rows)}
  </section>

  <section class="card">
    <h2>Robustness Breakdown</h2>
    {table(["Split", "Strategy", "Samples", "Failed", "Exact", "Canonical", "RDKit Valid", "Two Attach."], robustness_breakdown_rows)}
  </section>

  <section class="card">
    <h2>Epoch Checkpoints</h2>
    {table(["Epoch", "Checkpoint", "Step", "Loss", "Restore Loss", "Weighted Align", "Token Acc.", "Canonical", "RDKit Valid", "Two Attach.", "Best Ckpt", "Monitor"], epoch_checkpoint_rows)}
  </section>

  <section class="card">
    <h2>Failure Summary</h2>
    {table(["Dataset", "Failed Cases", "RDKit Invalid", "Attachment Invalid", "Top Strategies", "Top Reasons"], failure_rows)}
    <h3 style="margin-top:16px">First Final-Valid Failure Examples</h3>
    {table(["#", "Record", "Strategy", "Reason", "Input View", "Decoded", "Target"], first_failure_examples)}
  </section>

  <section class="card">
    <h2>Artifacts Included Locally</h2>
    {table(["File", "Size"], artifact_rows(stage_c_artifacts))}
  </section>

  <footer>Generated locally at {esc(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))} from <code>{esc(stage_c_artifacts)}</code>. Report file: <code>{esc(output_path)}</code>.</footer>
"""
    subtitle = "本报告对应 Stage C full 对照组：每个 epoch 都使用 v2 train 全量 all-view 数据；版式和 Stage B full 报告保持一致，便于逐项对比。"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(format_report_page("Stage C v2 Full Static All-View Report", subtitle, body), encoding="utf-8")


def cmp_bar(metric_name: str, stage_b: float, stage_c: float, *, lower_is_better: bool = False) -> str:
    max_value = max(stage_b, stage_c, 1e-9)
    b_width = stage_b / max_value * 100
    c_width = stage_c / max_value * 100
    delta = stage_c - stage_b
    good = delta < 0 if lower_is_better else delta > 0
    delta_text = f"{delta:+.4f}" if lower_is_better else pp(delta)
    return f"""
      <div class="cmp-row">
        <div class="cmp-label">{esc(metric_name)}</div>
        <div class="cmp-bars">
          <div class="cmp-line"><span>B</span><div class="cmp-track"><i style="width:{b_width:.2f}%;background:#475569"></i></div><b>{num(stage_b, 4) if lower_is_better else pct(stage_b)}</b></div>
          <div class="cmp-line"><span>C</span><div class="cmp-track"><i style="width:{c_width:.2f}%;background:#2563eb"></i></div><b>{num(stage_c, 4) if lower_is_better else pct(stage_c)}</b></div>
        </div>
        <div class="cmp-delta {'pos' if good else 'neg'}">{esc(delta_text)}</div>
      </div>"""


def comparison_metric_card(label: str, stage_b: float, stage_c: float, *, lower_is_better: bool = False) -> str:
    delta = stage_c - stage_b
    good = delta < 0 if lower_is_better else delta > 0
    value = num(stage_c, 4) if lower_is_better else pct(stage_c)
    delta_text = f"{delta:+.4f}" if lower_is_better else pp(delta)
    return metric(label, f'{value} <span class="delta {"pos" if good else "neg"}">{esc(delta_text)}</span>', f"Stage B {num(stage_b, 4) if lower_is_better else pct(stage_b)} · Stage C vs B")


def build_stage_b_stage_c_comparison(stage_b_artifacts: Path, stage_c_artifacts: Path, output_path: Path) -> None:
    b_valid = read_json(stage_b_artifacts / "eval_metrics.json")
    b_test = test_metrics_for_stage_b(stage_b_artifacts)
    b_robust_valid = read_json(stage_b_artifacts / "robustness_valid_eval_metrics.json")
    b_robust_test = read_json(stage_b_artifacts / "robustness_test_eval_metrics.json")
    c_valid = read_json(stage_c_artifacts / "eval_metrics.json")
    c_test = read_json(stage_c_artifacts / "all_view_test_eval_metrics.json")
    c_robust_valid = read_json(stage_c_artifacts / "robustness_valid_eval_metrics.json")
    c_robust_test = read_json(stage_c_artifacts / "robustness_test_eval_metrics.json")
    c_config = read_json(stage_c_artifacts / "training_config.json")
    b_config = read_json(stage_b_artifacts / "training_config.json")
    b_epoch_rows = read_jsonl(stage_b_artifacts / "epoch_metrics.jsonl")
    c_epoch_rows = read_jsonl(stage_c_artifacts / "epoch_metrics.jsonl")
    common_epoch = min(
        max(int(row["checkpoint_epoch"]) for row in b_epoch_rows),
        max(int(row["checkpoint_epoch"]) for row in c_epoch_rows),
    )
    b_same_epoch = next(row for row in b_epoch_rows if int(row["checkpoint_epoch"]) == common_epoch)
    c_same_epoch = next(row for row in c_epoch_rows if int(row["checkpoint_epoch"]) == common_epoch)

    cards = "".join(
        [
            comparison_metric_card("Final valid canonical", float(b_valid["canonical_match"]), float(c_valid["canonical_match"])),
            comparison_metric_card("Final test canonical", float(b_test["canonical_match"]), float(c_test["canonical_match"])),
            comparison_metric_card("Robustness valid canonical", float(b_robust_valid["canonical_match"]), float(c_robust_valid["canonical_match"])),
            comparison_metric_card("Robustness test canonical", float(b_robust_test["canonical_match"]), float(c_robust_test["canonical_match"])),
            comparison_metric_card("Final valid restore loss", restore_loss(b_valid) or 0.0, restore_loss(c_valid) or 0.0, lower_is_better=True),
            comparison_metric_card("Final test restore loss", restore_loss(b_test) or 0.0, restore_loss(c_test) or 0.0, lower_is_better=True),
        ]
    )

    headline_specs = [
        ("Final valid restore loss", b_valid, c_valid, "loss", True),
        ("Final valid canonical", b_valid, c_valid, "canonical_match", False),
        ("Final test restore loss", b_test, c_test, "loss", True),
        ("Final test canonical", b_test, c_test, "canonical_match", False),
        ("Robustness valid canonical", b_robust_valid, c_robust_valid, "canonical_match", False),
        ("Robustness test canonical", b_robust_test, c_robust_test, "canonical_match", False),
        ("Token accuracy valid", b_valid, c_valid, "token_accuracy", False),
        ("RDKit validity valid", b_valid, c_valid, "rdkit_validity", False),
    ]
    headline_rows = []
    for label, b_metrics, c_metrics, key, lower in headline_specs:
        b_value = restore_loss(b_metrics) if key == "loss" else metric_value(b_metrics, key)
        c_value = restore_loss(c_metrics) if key == "loss" else metric_value(c_metrics, key)
        if b_value is None or c_value is None:
            continue
        delta = c_value - b_value
        good = delta < 0 if lower else delta > 0
        headline_rows.append(
            [
                esc(label),
                num(b_value, 4) if lower else pct(b_value),
                num(c_value, 4) if lower else pct(c_value),
                f"{delta:+.4f}" if lower else pp(delta),
                '<span class="pill good">Stage C better</span>' if good else '<span class="pill warn">Stage B better</span>',
            ]
        )

    same_epoch_specs = [
        ("Valid restore loss", "loss", True),
        ("Valid canonical", "canonical_match", False),
        ("Valid exact", "exact_string_match", False),
        ("Valid RDKit validity", "rdkit_validity", False),
        ("Valid two attachment", "two_attachment_validity", False),
        ("Valid token accuracy", "token_accuracy", False),
    ]
    same_epoch_rows = []
    for label, key, lower in same_epoch_specs:
        b_value = restore_loss(b_same_epoch) if key == "loss" else metric_value(b_same_epoch, key)
        c_value = restore_loss(c_same_epoch) if key == "loss" else metric_value(c_same_epoch, key)
        if b_value is None or c_value is None:
            continue
        delta = c_value - b_value
        same_epoch_rows.append(
            [
                esc(label),
                num(b_value, 4) if lower else pct(b_value),
                num(c_value, 4) if lower else pct(c_value),
                f"{delta:+.4f}" if lower else pp(delta),
                '<span class="pill good">Stage C better</span>'
                if (delta < 0 if lower else delta > 0)
                else '<span class="pill warn">Stage B better</span>',
            ]
        )

    same_epoch_strategy_rows = []
    for strategy in sorted((b_same_epoch.get("all_view_by_strategy") or {}).keys()):
        b_values = (b_same_epoch.get("all_view_by_strategy") or {}).get(strategy)
        c_values = (c_same_epoch.get("all_view_by_strategy") or {}).get(strategy)
        if not b_values or not c_values:
            continue
        b_rate = float(b_values["canonical_match"])
        c_rate = float(c_values["canonical_match"])
        same_epoch_strategy_rows.append(
            [
                f'<span class="dot" style="background:{STRATEGY_COLORS.get(strategy, "#2563eb")}"></span><b>{esc(strategy)}</b>',
                pct(b_rate),
                pct(c_rate),
                pp(c_rate - b_rate),
            ]
        )

    c_extra_epoch_rows = []
    for label, key, lower in same_epoch_specs:
        c_same = restore_loss(c_same_epoch) if key == "loss" else metric_value(c_same_epoch, key)
        c_final = restore_loss(c_valid) if key == "loss" else metric_value(c_valid, key)
        if c_same is None or c_final is None:
            continue
        delta = c_final - c_same
        c_extra_epoch_rows.append(
            [
                esc(label),
                num(c_same, 4) if lower else pct(c_same),
                num(c_final, 4) if lower else pct(c_final),
                f"{delta:+.4f}" if lower else pp(delta),
            ]
        )

    chart_rows = "".join(
        [
            cmp_bar("Canonical Match", float(b_valid["canonical_match"]), float(c_valid["canonical_match"])),
            cmp_bar("Exact String Match", float(b_valid["exact_string_match"]), float(c_valid["exact_string_match"])),
            cmp_bar("RDKit Validity", float(b_valid["rdkit_validity"]), float(c_valid["rdkit_validity"])),
            cmp_bar("Two Attachment Validity", float(b_valid["two_attachment_validity"]), float(c_valid["two_attachment_validity"])),
            cmp_bar("Restore Loss", restore_loss(b_valid) or 0.0, restore_loss(c_valid) or 0.0, lower_is_better=True),
        ]
    )

    parity_rows = [
        ["Stage B full", str(b_valid.get("completed_epochs", b_config.get("max_epochs"))), f"{int(b_valid['decoded_sample_count']):,}/{int(b_valid['sample_count']):,}", f"{int(b_test['decoded_sample_count']):,}/{int(b_test['sample_count']):,}", f"{int(b_robust_valid['decoded_sample_count']):,}/{int(b_robust_valid['sample_count']):,}", f"{int(b_robust_test['decoded_sample_count']):,}/{int(b_robust_test['sample_count']):,}", "restore-only"],
        ["Stage C full", str(c_valid.get("completed_epochs", c_config.get("max_epochs"))), f"{int(c_valid['decoded_sample_count']):,}/{int(c_valid['sample_count']):,}", f"{int(c_test['decoded_sample_count']):,}/{int(c_test['sample_count']):,}", f"{int(c_robust_valid['decoded_sample_count']):,}/{int(c_robust_valid['sample_count']):,}", f"{int(c_robust_test['decoded_sample_count']):,}/{int(c_robust_test['sample_count']):,}", "restore + graph + align"],
    ]

    def strategy_compare_rows(b_metrics: dict[str, Any], c_metrics: dict[str, Any], source_key: str) -> list[list[Any]]:
        rows = []
        strategies = sorted(set((b_metrics.get(source_key) or {}).keys()) | set((c_metrics.get(source_key) or {}).keys()))
        for strategy in strategies:
            b_values = (b_metrics.get(source_key) or {}).get(strategy)
            c_values = (c_metrics.get(source_key) or {}).get(strategy)
            if not b_values or not c_values:
                continue
            b_rate = float(b_values["canonical_match"])
            c_rate = float(c_values["canonical_match"])
            rows.append(
                [
                    f'<span class="dot" style="background:{STRATEGY_COLORS.get(strategy, "#2563eb")}"></span><b>{esc(strategy)}</b>',
                    pct(b_rate),
                    pct(c_rate),
                    pp(c_rate - b_rate),
                    cmp_bar(strategy, b_rate, c_rate),
                ]
            )
        return sorted(rows, key=lambda row: row[0])

    stage_c_only_rows = [
        ["Valid text→graph top1/top5", f"{pct(c_valid['text_to_graph_top1'])} / {pct(c_valid['text_to_graph_top5'])}"],
        ["Valid graph→text top1/top5", f"{pct(c_valid['graph_to_text_top1'])} / {pct(c_valid['graph_to_text_top5'])}"],
        ["Test text→graph top1/top5", f"{pct(c_test['text_to_graph_top1'])} / {pct(c_test['text_to_graph_top5'])}"],
        ["Test graph→text top1/top5", f"{pct(c_test['graph_to_text_top1'])} / {pct(c_test['graph_to_text_top5'])}"],
        ["Final weighted align loss", num(float(c_valid["weighted_align_loss"]), 4)],
        ["Final align-to-restore ratio", num(float(c_valid["align_to_restore_ratio"]), 4)],
    ]

    body = f"""
  <section class="grid metrics">{cards}</section>

  <section class="card">
    <h2>Strategy Definitions</h2>
    {table(["Run", "Description"], [
        ["Stage B full", "restore-only, static full all-view；每个 epoch 使用 v2 train 全量 46,320 行。"],
        ["Stage C full", "restore + graph + align, static full all-view；每个 epoch 使用同一 v2 train 全量 46,320 行，并优化 L_restore + 0.2 * L_align。"],
        ["Main comparison rule", "只直接横比 restore 指标：restore_loss、canonical/exact、RDKit validity、two-attachment validity 和 strategy aggregates。"],
        ["Not directly comparable", "Stage B 的 loss 是 restore-only；Stage C 的 total loss 是 joint loss，因此对比表使用 Stage C restore_loss。"],
        ["Epoch budget caveat", f"Stage B max_epochs={b_config.get('max_epochs')}，Stage C max_epochs={c_config.get('max_epochs')}；本报告对比最终产物，不单独归因到架构或 epoch 数。"],
    ])}
  </section>

  <section class="card">
    <h2>Headline Metric Comparison</h2>
    {table(["Metric", "Stage B full", "Stage C full", "Delta", "Winner"], headline_rows)}
  </section>

  <section class="card">
    <h2>Same-Epoch Valid Comparison</h2>
    {table(["Metric", f"Stage B epoch {common_epoch}", f"Stage C epoch {common_epoch}", "Delta", "Winner"], same_epoch_rows)}
    <p class="note">Same-epoch 口径只比较 checkpoint validation 全量 decode 指标；当前本地 artifacts 没有 Stage C epoch {common_epoch} 的 test/robustness final eval。</p>
  </section>

  <section class="grid two">
    <div class="card">
      <h2>Same-Epoch Strategy Comparison</h2>
      {table(["Strategy", f"Stage B epoch {common_epoch}", f"Stage C epoch {common_epoch}", "Delta"], same_epoch_strategy_rows)}
    </div>
    <div class="card">
      <h2>Stage C Extra-Epoch Gain</h2>
      {table(["Metric", f"Stage C epoch {common_epoch}", "Stage C final", "Delta"], c_extra_epoch_rows)}
    </div>
  </section>

  <section class="grid two">
    <div class="bar-card"><h3>Final Valid Restore Metrics</h3>{chart_rows}</div>
    <div class="card">
      <h2>Full-Decode Parity Check</h2>
      {table(["Run", "Epochs", "Valid Decode", "Test Decode", "Robust Valid", "Robust Test", "Objective"], parity_rows)}
    </div>
  </section>

  <section class="card">
    <h2>Final Valid Strategy Comparison</h2>
    {table(["Strategy", "Stage B full", "Stage C full", "Delta", "Visual"], strategy_compare_rows(b_valid, c_valid, "all_view_by_strategy"))}
  </section>

  <section class="card">
    <h2>Robustness Test Strategy Comparison</h2>
    {table(["Strategy", "Stage B full", "Stage C full", "Delta", "Visual"], strategy_compare_rows(b_robust_test, c_robust_test, "robustness_by_strategy"))}
  </section>

  <section class="card">
    <h2>Stage C-only Alignment Metrics</h2>
    {table(["Metric", "Value"], stage_c_only_rows)}
  </section>

  <section class="card">
    <h2>Interpretation</h2>
    <div class="callout">Stage C full 在 final valid/test canonical、robustness valid/test canonical、token accuracy 与 RDKit validity 上均高于本地 Stage B full；restore loss 也更低。由于 Stage C 使用 30 epoch 且加入 graph/align 分支，这个结果说明当前 Stage C full 产物更强，但不能单独作为架构 ablation 归因。</div>
  </section>

  <section class="card">
    <h2>Caveats</h2>
    <ul>
      <li>Stage B full 为 20 epoch，Stage C full 为 30 epoch。</li>
      <li>同 epoch 比较目前只覆盖 valid checkpoint；test/robustness 的同 epoch 严格横比需要补跑 Stage C epoch {common_epoch} checkpoint 的对应评测。</li>
      <li>Stage C 的 total loss 不和 Stage B loss 直接比较；所有 loss 横比使用 restore_loss 口径。</li>
      <li>Stage C retrieval / align 指标只用于分析多任务训练效果，不能和 Stage B restore-only 直接横比。</li>
    </ul>
  </section>

  <footer>Generated locally at {esc(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))} from <code>{esc(stage_b_artifacts)}</code> and <code>{esc(stage_c_artifacts)}</code>. Report file: <code>{esc(output_path)}</code>.</footer>
"""
    subtitle = "本报告并排比较 Stage B v2 full restore-only 与 Stage C v2 full restore+graph+align 的最终产物；所有横比只使用 restore 相关正式指标。"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(format_report_page("Stage B v2 Full vs Stage C v2 Full Comparison", subtitle, body), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage C Stage-B-style and Stage B vs Stage C full HTML reports.")
    parser.add_argument("--stage-c-artifacts", type=Path, default=DEFAULT_STAGE_C_ARTIFACTS)
    parser.add_argument("--stage-b-artifacts", type=Path, default=DEFAULT_STAGE_B_ARTIFACTS)
    parser.add_argument("--stage-c-report", type=Path, default=DEFAULT_STAGE_C_REPORT)
    parser.add_argument("--comparison-report", type=Path, default=DEFAULT_STAGE_B_STAGE_C_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_stage_c_report(args.stage_c_artifacts, args.stage_c_report)
    build_stage_b_stage_c_comparison(args.stage_b_artifacts, args.stage_c_artifacts, args.comparison_report)
    print(
        json.dumps(
            {
                "stage_c_report": str(args.stage_c_report),
                "comparison_report": str(args.comparison_report),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
