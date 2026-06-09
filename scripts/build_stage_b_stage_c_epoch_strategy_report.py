from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_STAGE_B_ARTIFACTS = Path("reports/stage_b_restore_aug_v2_full_20epoch_artifacts")
DEFAULT_STAGE_C_ARTIFACTS = Path("reports/stage_c_non_vocab_aug_v2_full_30epoch_artifacts")
DEFAULT_REPORT = Path("reports/stage_b_stage_c_aug_v2_epoch_strategy_valid_full_comparison_report.html")

STRATEGY_ORDER = [
    "identity",
    "attachment_rooted_smiles",
    "rdkit_random_smiles",
    "direction_flip",
    "light_denoise",
]

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

CSS = """
:root{--bg:#f5f7fb;--panel:#fff;--ink:#172033;--muted:#647084;--line:#dbe3ee;--navy:#101827;--blue:#2563eb;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.52 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}header{background:var(--navy);color:#fff;padding:34px 40px 30px}header h1{margin:0 0 8px;font-size:28px;letter-spacing:0}header p{margin:0;color:#cbd5e1;max-width:1160px}main{max-width:1500px;margin:0 auto;padding:28px 24px 54px}section{margin:0 0 24px}h2{font-size:19px;margin:0 0 13px}.card,.metric{background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 1px 2px rgba(15,23,42,.035)}.card{padding:18px}.grid{display:grid;gap:14px}.metrics{grid-template-columns:repeat(4,minmax(0,1fr))}.metric{padding:14px 16px;min-height:94px}.metric-label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}.metric-value{font-size:25px;font-weight:760;margin:4px 0 2px}.metric-note{color:var(--muted);font-size:12px}.callout{border-left:4px solid var(--blue);background:#eff6ff;border-radius:0 8px 8px 0;padding:12px 14px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:8px;background:#fff;max-height:76vh}table{border-collapse:separate;border-spacing:0;width:100%;min-width:1180px}th,td{padding:8px 10px;border-bottom:1px solid var(--line);border-right:1px solid #eef2f7;vertical-align:middle;text-align:left;white-space:nowrap}th{position:sticky;top:0;background:#f8fafc;color:#475569;font-size:12px;text-transform:uppercase;letter-spacing:.04em;z-index:3}tr:nth-child(10n+1),tr:nth-child(10n+2),tr:nth-child(10n+3),tr:nth-child(10n+4),tr:nth-child(10n+5){background:#fcfdff}td:first-child,th:first-child{position:sticky;left:0;background:inherit;z-index:2}th:first-child{z-index:4}.compact table{min-width:900px}.compact .table-wrap{max-height:none}.sub{color:var(--muted);font-size:12px;margin-top:2px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:7px;vertical-align:middle}.val{display:inline-block;min-width:76px;padding:2px 7px;border-radius:5px;border:1px solid rgba(148,163,184,.25);font-weight:650}.delta{font-weight:760}.delta.pos{color:#047857}.delta.neg{color:#b91c1c}.delta.flat{color:#64748b}code{background:#eef2f7;border:1px solid #d9e2ec;padding:1px 5px;border-radius:5px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}.note{color:var(--muted);font-size:12px;margin-top:8px}footer{color:var(--muted);font-size:12px;margin-top:30px}@media(max-width:900px){header{padding:26px 20px}main{padding:20px 14px 40px}.metrics{grid-template-columns:1fr}.table-wrap{max-height:70vh}}
"""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def num(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}"


def pp(value: float) -> str:
    return f"{value * 100:+.2f} pp"


def delta_span(delta: float, *, lower_is_better: bool = False) -> str:
    if abs(delta) < 0.005:
        cls = "flat"
    else:
        good = delta < 0 if lower_is_better else delta > 0
        cls = "pos" if good else "neg"
    text = f"{delta:+.4f}" if lower_is_better else pp(delta)
    return f'<span class="delta {cls}">{esc(text)}</span>'


def metric_card(label: str, value: str, note: str) -> str:
    return (
        '<div class="metric">'
        f'<div class="metric-label">{esc(label)}</div>'
        f'<div class="metric-value">{value}</div>'
        f'<div class="metric-note">{note}</div>'
        "</div>"
    )


def table(headers: list[str], rows: list[list[Any]], *, class_name: str = "") -> str:
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="table-wrap {esc(class_name)}"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def value_bar(value: float) -> str:
    width = max(0.0, min(100.0, value * 100))
    alpha = 0.12 + 0.34 * max(0.0, min(1.0, value))
    return (
        f'<span class="val" style="background:linear-gradient(90deg, '
        f'rgba(37,99,235,{alpha:.3f}) {width:.2f}%, transparent {width:.2f}%);">{pct(value)}</span>'
    )


def strategy_label(strategy: str) -> str:
    return (
        f'<span class="dot" style="background:{STRATEGY_COLORS.get(strategy, "#2563eb")}"></span>'
        f'<b>{esc(strategy)}</b><div class="sub">{esc(STRATEGY_MEANINGS.get(strategy, ""))}</div>'
    )


def row_loss(row: dict[str, Any], *, stage: str) -> float:
    if stage == "c":
        return float(row.get("restore_loss", row.get("loss", 0.0)))
    return float(row.get("loss", 0.0))


def common_epoch_pairs(stage_b_rows: list[dict[str, Any]], stage_c_rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by_b = {int(row["checkpoint_epoch"]): row for row in stage_b_rows}
    by_c = {int(row["checkpoint_epoch"]): row for row in stage_c_rows}
    return [(by_b[epoch], by_c[epoch]) for epoch in sorted(set(by_b) & set(by_c))]


def macro_rows(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for b_row, c_row in pairs:
        b_loss = row_loss(b_row, stage="b")
        c_loss = row_loss(c_row, stage="c")
        rows.append(
            [
                int(b_row["checkpoint_epoch"]),
                num(b_loss),
                num(c_loss),
                delta_span(c_loss - b_loss, lower_is_better=True),
                pct(float(b_row["canonical_match"])),
                pct(float(c_row["canonical_match"])),
                delta_span(float(c_row["canonical_match"]) - float(b_row["canonical_match"])),
                pct(float(b_row["rdkit_validity"])),
                pct(float(c_row["rdkit_validity"])),
                delta_span(float(c_row["rdkit_validity"]) - float(b_row["rdkit_validity"])),
            ]
        )
    return rows


def delta_matrix_rows(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for b_row, c_row in pairs:
        row: list[Any] = [int(b_row["checkpoint_epoch"])]
        for strategy in STRATEGY_ORDER:
            b_values = b_row["all_view_by_strategy"][strategy]
            c_values = c_row["all_view_by_strategy"][strategy]
            delta = float(c_values["canonical_match"]) - float(b_values["canonical_match"])
            row.append(delta_span(delta))
        rows.append(row)
    return rows


def best_strategy_rows(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    b_rows = [pair[0] for pair in pairs]
    c_rows = [pair[1] for pair in pairs]
    for strategy in STRATEGY_ORDER:
        b_best = max(b_rows, key=lambda row: float(row["all_view_by_strategy"][strategy]["canonical_match"]))
        c_best = max(c_rows, key=lambda row: float(row["all_view_by_strategy"][strategy]["canonical_match"]))
        b_final = b_rows[-1]["all_view_by_strategy"][strategy]
        c_final = c_rows[-1]["all_view_by_strategy"][strategy]
        b_best_value = float(b_best["all_view_by_strategy"][strategy]["canonical_match"])
        c_best_value = float(c_best["all_view_by_strategy"][strategy]["canonical_match"])
        b_final_value = float(b_final["canonical_match"])
        c_final_value = float(c_final["canonical_match"])
        rows.append(
            [
                f'<span class="dot" style="background:{STRATEGY_COLORS.get(strategy, "#2563eb")}"></span><b>{esc(strategy)}</b>',
                f"epoch {int(b_best['checkpoint_epoch'])} · {pct(b_best_value)}",
                f"epoch {int(c_best['checkpoint_epoch'])} · {pct(c_best_value)}",
                delta_span(c_best_value - b_best_value),
                pct(b_final_value),
                pct(c_final_value),
                delta_span(c_final_value - b_final_value),
            ]
        )
    return rows


def detailed_rows(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for b_row, c_row in pairs:
        for strategy in STRATEGY_ORDER:
            b_values = b_row["all_view_by_strategy"][strategy]
            c_values = c_row["all_view_by_strategy"][strategy]
            b_can = float(b_values["canonical_match"])
            c_can = float(c_values["canonical_match"])
            b_exact = float(b_values["exact_string_match"])
            c_exact = float(c_values["exact_string_match"])
            b_rdkit = float(b_values["rdkit_validity"])
            c_rdkit = float(c_values["rdkit_validity"])
            b_attach = float(b_values["two_attachment_validity"])
            c_attach = float(c_values["two_attachment_validity"])
            rows.append(
                [
                    int(b_row["checkpoint_epoch"]),
                    strategy_label(strategy),
                    value_bar(b_can),
                    value_bar(c_can),
                    delta_span(c_can - b_can),
                    value_bar(b_exact),
                    value_bar(c_exact),
                    delta_span(c_exact - b_exact),
                    value_bar(b_rdkit),
                    value_bar(c_rdkit),
                    delta_span(c_rdkit - b_rdkit),
                    value_bar(b_attach),
                    value_bar(c_attach),
                    delta_span(c_attach - b_attach),
                    f"{int(b_values.get('failed_count', 0)):,} / {int(c_values.get('failed_count', 0)):,}",
                ]
            )
    return rows


def build_report(stage_b_artifacts: Path, stage_c_artifacts: Path, output_path: Path) -> None:
    b_rows = read_jsonl(stage_b_artifacts / "epoch_metrics.jsonl")
    c_rows = read_jsonl(stage_c_artifacts / "epoch_metrics.jsonl")
    pairs = common_epoch_pairs(b_rows, c_rows)
    if not pairs:
        raise ValueError("No common checkpoint epochs found")

    b_common = [pair[0] for pair in pairs]
    c_common = [pair[1] for pair in pairs]
    b_best = max(b_common, key=lambda row: float(row["canonical_match"]))
    c_best = max(c_common, key=lambda row: float(row["canonical_match"]))
    b_final = b_common[-1]
    c_final = c_common[-1]
    final_delta = float(c_final["canonical_match"]) - float(b_final["canonical_match"])

    cards = "".join(
        [
            metric_card("Stage B best valid canonical", pct(float(b_best["canonical_match"])), f"epoch {int(b_best['checkpoint_epoch'])}"),
            metric_card("Stage C best valid canonical", pct(float(c_best["canonical_match"])), f"epoch {int(c_best['checkpoint_epoch'])} within common epochs"),
            metric_card("Common-final canonical delta", delta_span(final_delta), f"Stage C {pct(float(c_final['canonical_match']))} vs Stage B {pct(float(b_final['canonical_match']))}"),
            metric_card("Rows in main table", f"{len(pairs) * len(STRATEGY_ORDER):,}", f"{len(pairs)} epochs × {len(STRATEGY_ORDER)} strategies"),
        ]
    )

    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage B vs Stage C Epoch Strategy Valid Comparison</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>Stage B vs Stage C Epoch × Strategy Valid Results</h1>
  <p>按同一个 augmentation strategy 对齐比较 Stage B restore-only full 与 Stage C restore+graph full 的 valid checkpoint 结果。比较范围为两组共同存在的 epoch 1-{len(pairs)}，所有 checkpoint 均为 valid full decode，策略分项样本数为每策略 1,158，总计 5,790。</p>
</header>
<main>
  <section class="grid metrics">{cards}</section>

  <section class="card">
    <h2>Reading Notes</h2>
    <div class="callout">
      表中每行是一个 <b>epoch × strategy</b>。Delta = Stage C - Stage B，正值表示 Stage C 更高；loss 对比使用 Stage B loss 与 Stage C restore_loss。这里专注共同 epoch 的同策略 valid checkpoint 对照，不混入 Stage C epoch 21-30 的额外训练收益。
    </div>
  </section>

  <section class="card compact">
    <h2>Macro Valid Checkpoint Comparison by Epoch</h2>
    {table(["Epoch", "Stage B Loss", "Stage C Restore Loss", "Loss Δ", "Stage B Canonical", "Stage C Canonical", "Canonical Δ", "Stage B RDKit", "Stage C RDKit", "RDKit Δ"], macro_rows(pairs))}
  </section>

  <section class="card compact">
    <h2>Canonical Delta Matrix by Epoch and Strategy</h2>
    {table(["Epoch", *STRATEGY_ORDER], delta_matrix_rows(pairs))}
  </section>

  <section class="card compact">
    <h2>Best Canonical by Strategy</h2>
    {table(["Strategy", "Stage B Best", "Stage C Best", "Best Δ", "Stage B Final@Common", "Stage C Final@Common", "Final Δ"], best_strategy_rows(pairs))}
  </section>

  <section class="card">
    <h2>Detailed Epoch × Strategy Valid Metrics</h2>
    {table(["Epoch", "Strategy", "Stage B Canonical", "Stage C Canonical", "Can Δ", "Stage B Exact", "Stage C Exact", "Exact Δ", "Stage B RDKit", "Stage C RDKit", "RDKit Δ", "Stage B 2-Attach", "Stage C 2-Attach", "2-Attach Δ", "Failed B/C"], detailed_rows(pairs))}
  </section>

  <footer>Generated locally at {esc(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))} from <code>{esc(stage_b_artifacts / 'epoch_metrics.jsonl')}</code> and <code>{esc(stage_c_artifacts / 'epoch_metrics.jsonl')}</code>. Report file: <code>{esc(output_path)}</code>.</footer>
</main>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(body, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage B vs Stage C epoch-strategy valid comparison HTML report.")
    parser.add_argument("--stage-b-artifacts", type=Path, default=DEFAULT_STAGE_B_ARTIFACTS)
    parser.add_argument("--stage-c-artifacts", type=Path, default=DEFAULT_STAGE_C_ARTIFACTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_report(args.stage_b_artifacts, args.stage_c_artifacts, args.output)
    print(json.dumps({"report": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
