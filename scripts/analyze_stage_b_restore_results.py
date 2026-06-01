from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("outputs/stage_b_restore_aug_full_20epoch")
DEFAULT_PREVIEW_PATH = Path("data/baselite_smiles_aug_v1/training_template_preview.jsonl")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "stage_b_restore_aug_full_20epoch_detailed_analysis_zh.html"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_optional(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
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
        return str(value)
    return f"{value:.{digits}f}"


def rate_count(value: float | None, total: int | None) -> str:
    if value is None:
        return "-"
    if total:
        count = int(round(value * total))
        return f"{pct(value)} <span class=\"muted\">({count}/{total})</span>"
    return pct(value)


def truncate(value: str, limit: int = 140) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def table(headers: list[str], rows: list[list[Any]], *, class_name: str = "") -> str:
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table class=\"{esc(class_name)}\"><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def metric_bar(value: float | None, label: str | None = None) -> str:
    if value is None:
        return "-"
    width = max(0.0, min(100.0, value * 100))
    text = label if label is not None else pct(value)
    return f"<div class=\"bar\"><span style=\"width:{width:.2f}%\"></span></div><div class=\"bar-label\">{text}</div>"


def sparkline_svg(values: list[float], *, width: int = 720, height: int = 180, color: str = "#2563eb") -> str:
    if not values:
        return ""
    if len(values) == 1:
        values = values + values
    lo = min(values)
    hi = max(values)
    if hi == lo:
        hi = lo + 1.0
    pad = 16
    points = []
    for index, value in enumerate(values):
        x = pad + index * (width - 2 * pad) / (len(values) - 1)
        y = height - pad - ((value - lo) / (hi - lo)) * (height - 2 * pad)
        points.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(points)
    return (
        f"<svg class=\"chart\" viewBox=\"0 0 {width} {height}\" role=\"img\">"
        f"<line x1=\"{pad}\" y1=\"{height-pad}\" x2=\"{width-pad}\" y2=\"{height-pad}\" class=\"axis\"/>"
        f"<line x1=\"{pad}\" y1=\"{pad}\" x2=\"{pad}\" y2=\"{height-pad}\" class=\"axis\"/>"
        f"<polyline points=\"{polyline}\" fill=\"none\" stroke=\"{color}\" stroke-width=\"3\"/>"
        f"<text x=\"{pad}\" y=\"{pad}\" class=\"chart-label\">max {hi:.4f}</text>"
        f"<text x=\"{pad}\" y=\"{height-2}\" class=\"chart-label\">min {lo:.4f}</text>"
        "</svg>"
    )


def split_counts(preview_path: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    with preview_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            counts[str(row.get("split", ""))] += 1
    return dict(sorted(counts.items()))


def load_test_preview_info(preview_path: Path) -> dict[str, dict[str, Any]]:
    info: dict[str, dict[str, Any]] = {}
    with preview_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("split") != "test":
                continue
            record_id = str(row["record_id"])
            canonical = str(row.get("canonical_smiles", ""))
            info[record_id] = {
                "restore_token_len": len(row.get("restore_labels", [])),
                "view_token_len": len(row.get("input_ids_view1", [])),
                "char_len": len(canonical),
                "canonical_smiles": canonical,
            }
    return info


def length_bucket(length: int) -> str:
    if length <= 64:
        return "<=64"
    if length <= 128:
        return "65-128"
    if length <= 256:
        return "129-256"
    return ">256"


def failure_category(row: dict[str, Any]) -> str:
    if row.get("canonical_match"):
        return "correct"
    if not row.get("rdkit_valid"):
        return "invalid_smiles"
    if not row.get("two_attachment_valid"):
        return "attachment_count_not_two"
    return "valid_two_attachment_wrong_canonical"


def candidate_dirs(candidate_summary: list[dict[str, Any]], candidate_root: Path) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    for row in candidate_summary:
        name = str(row["candidate_name"])
        result.append((name, candidate_root / name))
    return result


def build_report(*, output_dir: Path, preview_path: Path, report_path: Path) -> None:
    epoch_metrics = read_jsonl(output_dir / "epoch_metrics.jsonl")
    quick_metrics = read_jsonl(output_dir / "quick_eval_metrics.jsonl")
    final_valid = read_json(output_dir / "eval_metrics.json")
    identity_test = read_json(output_dir / "identity_test_eval_metrics.json")
    robustness_valid = read_json(output_dir / "robustness_valid_eval_metrics.json")
    robustness_test = read_json(output_dir / "robustness_test_eval_metrics.json")
    reload_smoke = read_json(output_dir / "reload_smoke.json")
    training_config = read_json(output_dir / "training_config.json")
    candidate_root = output_dir / "candidate_test_eval_full"
    candidate_summary_data = read_json_optional(candidate_root / "test_candidate_eval_summary.json")
    candidate_summary = candidate_summary_data if isinstance(candidate_summary_data, list) else []
    has_candidate_eval = bool(candidate_summary)
    test_preview = load_test_preview_info(preview_path)
    preview_counts = split_counts(preview_path)

    best_loss_epoch = min(epoch_metrics, key=lambda row: float(row["loss"]))
    best_canonical_epoch = max(epoch_metrics, key=lambda row: float(row["canonical_match"]))
    final_epoch = epoch_metrics[-1]
    candidate_rows = []
    candidate_predictions: dict[str, list[dict[str, Any]]] = {}
    candidate_failures: dict[str, list[dict[str, Any]]] = {}
    if has_candidate_eval:
        for name, directory in candidate_dirs(candidate_summary, candidate_root):
            preds = read_jsonl(directory / "test_predictions.jsonl")
            fails = read_jsonl(directory / "test_failed_cases.jsonl")
            candidate_predictions[name] = preds
            candidate_failures[name] = fails
            metrics = next(row for row in candidate_summary if row["candidate_name"] == name)
            total = int(metrics["sample_count"])
            candidate_rows.append(
                [
                    f"<strong>{esc(name)}</strong>",
                    metric_bar(float(metrics["canonical_match"]), rate_count(float(metrics["canonical_match"]), total)),
                    metric_bar(float(metrics["rdkit_validity"]), rate_count(float(metrics["rdkit_validity"]), total)),
                    metric_bar(float(metrics["two_attachment_validity"]), rate_count(float(metrics["two_attachment_validity"]), total)),
                    rate_count(float(metrics["exact_string_match"]), total),
                    num(float(metrics["loss"]), 5),
                    str(len(fails)),
                ]
            )
    else:
        candidate_rows.append(
            [
                "<strong>未补跑</strong>",
                "缺少 <code>candidate_test_eval_full/test_candidate_eval_summary.json</code>",
                "-",
                "-",
                "-",
                "-",
                "-",
            ]
        )

    names = [str(row["candidate_name"]) for row in candidate_summary]
    success_sets = {
        name: {row["record_id"] for row in candidate_predictions[name] if row.get("canonical_match")}
        for name in names
    }
    all_records = {row["record_id"] for row in candidate_predictions[names[0]]} if names else set()
    fail_sets = {name: all_records - success_sets[name] for name in names}
    overlap_rows: list[list[Any]] = []
    if {"epoch_008", "epoch_013", "epoch_014"}.issubset(set(names)):
        overlap_rows.extend(
            [
                ["三者均正确", len(success_sets["epoch_008"] & success_sets["epoch_013"] & success_sets["epoch_014"])],
                ["三者均失败", len(fail_sets["epoch_008"] & fail_sets["epoch_013"] & fail_sets["epoch_014"])],
                ["epoch_013 相比 epoch_008 新修复", len(fail_sets["epoch_008"] & success_sets["epoch_013"])],
                ["epoch_013 相比 epoch_008 新回退", len(success_sets["epoch_008"] & fail_sets["epoch_013"])],
                ["epoch_014 相比 epoch_013 新修复", len(fail_sets["epoch_013"] & success_sets["epoch_014"])],
                ["epoch_014 相比 epoch_013 新回退", len(success_sets["epoch_013"] & fail_sets["epoch_014"])],
            ]
        )

    failure_category_rows: list[list[Any]] = []
    for name in names:
        counter = Counter(failure_category(row) for row in candidate_predictions[name])
        total = len(candidate_predictions[name])
        failure_category_rows.append(
            [
                esc(name),
                str(counter["invalid_smiles"]),
                str(counter["attachment_count_not_two"]),
                str(counter["valid_two_attachment_wrong_canonical"]),
                str(counter["correct"]),
                pct(counter["correct"] / total),
            ]
        )

    bucket_order = ["<=64", "65-128", "129-256", ">256"]
    bucket_rows: list[list[Any]] = []
    for bucket in bucket_order:
        row = [bucket]
        bucket_n = 0
        for name in names:
            preds = candidate_predictions[name]
            in_bucket = [
                pred
                for pred in preds
                if length_bucket(int(test_preview.get(pred["record_id"], {}).get("restore_token_len", len(pred.get("target", ""))))) == bucket
            ]
            bucket_n = len(in_bucket)
            if in_bucket:
                rate = sum(1 for pred in in_bucket if pred.get("canonical_match")) / len(in_bucket)
                row.append(rate_count(rate, len(in_bucket)))
            else:
                row.append("-")
        row.insert(1, str(bucket_n))
        bucket_rows.append(row)

    epoch_table_rows = []
    for row in epoch_metrics:
        epoch = int(row["checkpoint_epoch"])
        early = row.get("early_stopping", {})
        badge = ""
        if row["checkpoint_name"] == best_loss_epoch["checkpoint_name"]:
            badge += " <span class=\"pill\">best loss</span>"
        if row["checkpoint_name"] == best_canonical_epoch["checkpoint_name"]:
            badge += " <span class=\"pill alt\">best valid canonical</span>"
        if early.get("stop_training"):
            badge += " <span class=\"pill warn\">early stop</span>"
        epoch_table_rows.append(
            [
                f"epoch_{epoch:03d}{badge}",
                num(float(row.get("checkpoint_epoch_train_loss_mean", 0.0)), 5),
                num(float(row["loss"]), 5),
                rate_count(float(row["canonical_match"]), int(row["decoded_sample_count"])),
                rate_count(float(row["rdkit_validity"]), int(row["decoded_sample_count"])),
                rate_count(float(row["two_attachment_validity"]), int(row["decoded_sample_count"])),
                rate_count(float(row["token_accuracy"]), None),
                str(early.get("wait", "")),
            ]
        )

    def eval_label(prefix: str, metrics: dict[str, Any]) -> str:
        decoded = metrics.get("decoded_sample_count", "?")
        total = metrics.get("sample_count", "?")
        return f"{prefix}, {decoded}/{total} decoded"

    artifact_rows = [
        [eval_label("final valid", final_valid), rate_count(final_valid.get("canonical_match"), final_valid.get("decoded_sample_count")), num(final_valid.get("loss"), 5), rate_count(final_valid.get("rdkit_validity"), final_valid.get("decoded_sample_count")), rate_count(final_valid.get("two_attachment_validity"), final_valid.get("decoded_sample_count"))],
        [eval_label("identity test", identity_test), rate_count(identity_test.get("canonical_match"), identity_test.get("decoded_sample_count")), num(identity_test.get("loss"), 5), rate_count(identity_test.get("rdkit_validity"), identity_test.get("decoded_sample_count")), rate_count(identity_test.get("two_attachment_validity"), identity_test.get("decoded_sample_count"))],
        [eval_label("robustness valid", robustness_valid), rate_count(robustness_valid.get("canonical_match"), robustness_valid.get("decoded_sample_count")), num(robustness_valid.get("loss"), 5), rate_count(robustness_valid.get("rdkit_validity"), robustness_valid.get("decoded_sample_count")), rate_count(robustness_valid.get("two_attachment_validity"), robustness_valid.get("decoded_sample_count"))],
        [eval_label("robustness test", robustness_test), rate_count(robustness_test.get("canonical_match"), robustness_test.get("decoded_sample_count")), num(robustness_test.get("loss"), 5), rate_count(robustness_test.get("rdkit_validity"), robustness_test.get("decoded_sample_count")), rate_count(robustness_test.get("two_attachment_validity"), robustness_test.get("decoded_sample_count"))],
    ]

    def robustness_strategy_rows(split_name: str, metrics: dict[str, Any]) -> list[list[Any]]:
        rows: list[list[Any]] = []
        decoded = int(metrics.get("decoded_sample_count") or 0)
        rows.append(
            [
                split_name,
                "row overall",
                str(decoded),
                rate_count(metrics.get("canonical_match"), decoded),
                rate_count(metrics.get("rdkit_validity"), decoded),
                rate_count(metrics.get("two_attachment_validity"), decoded),
                rate_count(metrics.get("exact_string_match"), decoded),
            ]
        )
        for strategy, values in (metrics.get("robustness_by_strategy") or {}).items():
            total = int(values.get("sample_count") or 0)
            rows.append(
                [
                    split_name,
                    esc(strategy),
                    str(total),
                    rate_count(values.get("canonical_match"), total),
                    rate_count(values.get("rdkit_validity"), total),
                    rate_count(values.get("two_attachment_validity"), total),
                    rate_count(values.get("exact_string_match"), total),
                ]
            )
        macro = metrics.get("robustness_strategy_macro_avg") or {}
        if macro:
            rows.append(
                [
                    split_name,
                    "strategy macro avg",
                    str(macro.get("strategy_count", "")),
                    pct(macro.get("canonical_match")),
                    pct(macro.get("rdkit_validity")),
                    pct(macro.get("two_attachment_validity")),
                    pct(macro.get("exact_string_match")),
                ]
            )
        return rows

    def robustness_record_rows(split_name: str, metrics: dict[str, Any]) -> list[list[Any]]:
        rows: list[list[Any]] = []
        for key, label in (
            ("robustness_record_all_views_success", "all views success"),
            ("robustness_record_any_view_success", "any view success"),
            ("robustness_record_partial_success", "partial success"),
        ):
            values = metrics.get(key) or {}
            total = int(values.get("record_count") or 0)
            success = int(values.get("success_count") or 0)
            rows.append([split_name, label, f"{success}/{total}", pct(values.get("rate"))])
        return rows

    robustness_strategy_table_rows = robustness_strategy_rows("valid", robustness_valid) + robustness_strategy_rows("test", robustness_test)
    robustness_record_table_rows = robustness_record_rows("valid", robustness_valid) + robustness_record_rows("test", robustness_test)

    primary_name = (
        str(max(candidate_summary, key=lambda row: float(row["canonical_match"]))["candidate_name"])
        if has_candidate_eval
        else str(final_valid.get("best_early_stopping_checkpoint") or final_epoch.get("checkpoint_name") or "final")
    )
    primary_fail_examples = candidate_failures.get(primary_name, [])[:16]
    example_rows = []
    for row in primary_fail_examples:
        info = test_preview.get(row["record_id"], {})
        example_rows.append(
            [
                esc(row["record_id"]),
                str(info.get("restore_token_len", "")),
                esc(failure_category(row)),
                f"<code>{esc(truncate(row.get('target', ''), 160))}</code>",
                f"<code>{esc(truncate(row.get('decoded_smiles', ''), 160))}</code>",
            ]
        )

    best_candidate_metrics = (
        next(row for row in candidate_summary if row["candidate_name"] == primary_name)
        if has_candidate_eval
        else identity_test
    )
    full_test_total = int(best_candidate_metrics.get("sample_count") or identity_test.get("sample_count") or 0)
    primary_card_name = primary_name if has_candidate_eval else "未补跑"
    primary_card_note = (
        f"canonical {rate_count(float(best_candidate_metrics['canonical_match']), full_test_total)}"
        if has_candidate_eval and best_candidate_metrics.get("canonical_match") is not None
        else "candidate full eval 缺失"
    )
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    loss_values = [float(row["loss"]) for row in epoch_metrics]
    canonical_values = [float(row["canonical_match"]) for row in epoch_metrics]
    quick_loss_values = [float(row["quick_valid"]["loss"]) for row in quick_metrics if "quick_valid" in row]
    completed_epochs = final_valid.get("completed_epochs", final_epoch.get("checkpoint_epoch", ""))
    final_status = "Early Stop" if final_valid.get("early_stopped") else "Completed"
    final_status_note = (
        "early stopping monitor-only"
        if final_valid.get("early_stopping_monitor_only")
        else f"completed_epochs={completed_epochs}"
    )
    epoch_decode_counts = sorted({int(row.get("decoded_sample_count", 0)) for row in epoch_metrics if row.get("decoded_sample_count") is not None})
    epoch_decode_note = ", ".join(str(value) for value in epoch_decode_counts) if epoch_decode_counts else "unknown"
    candidate_conclusion = (
        f"按完整 test 集 {full_test_total} 条逐条解码，综合最优是 <strong>{esc(primary_name)}</strong>。"
        if has_candidate_eval
        else "尚未找到 candidate full test 结果；本报告仅展示训练、final identity 与 robustness 指标。"
    )
    candidate_section_note = (
        f"共找到 {len(candidate_summary)} 个候选，均使用 identity test split 全量逐条解码，输出了 metrics、predictions 和 failed cases。"
        if has_candidate_eval
        else "未找到 <code>candidate_test_eval_full/test_candidate_eval_summary.json</code>；如需 checkpoint 横向对比，请先用 <code>scripts/evaluate_stage_b_restore_checkpoint.py --decode-sample-limit 0</code> 补跑候选。"
    )
    training_end_note = (
        f"训练完成 {completed_epochs} 个 epoch；early stopping 仅监控、不提前中断。"
        if final_valid.get("early_stopping_monitor_only")
        else f"训练结束于 epoch {completed_epochs}；early_stop_reason={final_valid.get('early_stop_reason')!r}。"
    )
    if has_candidate_eval:
        model_selection_items = [
            f"<li><strong>identity test 主候选：</strong>{esc(primary_name)}。它是已补跑候选中 canonical_match 最高的 checkpoint。</li>",
            f"<li><strong>valid loss 对照：</strong>{esc(best_loss_epoch['checkpoint_name'])}，valid loss 为 {num(float(best_loss_epoch['loss']), 5)}。</li>",
            "<li><strong>robustness 选择：</strong>如果目标是抗扰动 restore，应对候选 checkpoint 使用同一套 robustness valid full eval 后再定主模型。</li>",
        ]
    else:
        model_selection_items = [
            f"<li><strong>identity restore 候选：</strong>valid loss 最优为 {esc(best_loss_epoch['checkpoint_name'])}，valid canonical 最优为 {esc(best_canonical_epoch['checkpoint_name'])}。</li>",
            "<li><strong>当前限制：</strong>缺少 candidate full test 横向结果，不能仅凭 final checkpoint 或 identity valid 指标确定最终主模型。</li>",
            "<li><strong>下一步：</strong>对关键 checkpoint 补跑 identity test 与 robustness valid full eval；robustness 目标下优先看 record all-views success 与 strategy macro canonical。</li>",
        ]
    model_selection_html = "\n    ".join(model_selection_items)

    html_text = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\">
  <title>Stage B Restore Aug Full 20epoch 训练结果分析</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", Arial, sans-serif; margin: 0; color: #172033; background: #f6f7fb; }}
    main {{ max-width: 1240px; margin: 0 auto; padding: 32px 28px 56px; }}
    h1 {{ font-size: 30px; margin: 0 0 8px; }}
    h2 {{ font-size: 22px; margin: 34px 0 14px; border-left: 4px solid #2563eb; padding-left: 10px; }}
    h3 {{ font-size: 17px; margin: 22px 0 10px; }}
    p, li {{ line-height: 1.65; }}
    .muted {{ color: #687386; font-size: 12px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 18px 0; }}
    .card {{ background: #fff; border: 1px solid #d9deea; border-radius: 8px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
    .card .k {{ color: #687386; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }}
    .card .v {{ font-size: 24px; font-weight: 700; margin-top: 6px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d9deea; margin: 12px 0 22px; }}
    th, td {{ border-bottom: 1px solid #e7eaf2; padding: 9px 10px; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #eef2f8; color: #2b3447; font-weight: 700; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; white-space: normal; word-break: break-all; }}
    .bar {{ height: 8px; width: 120px; background: #e8edf5; border-radius: 999px; overflow: hidden; margin-bottom: 3px; }}
    .bar span {{ display: block; height: 100%; background: linear-gradient(90deg, #2563eb, #22a06b); }}
    .bar-label {{ font-size: 12px; color: #2b3447; }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 2px 7px; background: #e7f0ff; color: #174ea6; font-size: 11px; margin-left: 4px; }}
    .pill.alt {{ background: #e7f7ef; color: #157347; }}
    .pill.warn {{ background: #fff1df; color: #a15c00; }}
    .callout {{ background: #fff; border-left: 4px solid #22a06b; padding: 14px 16px; margin: 14px 0; border-radius: 6px; }}
    .warnbox {{ background: #fff; border-left: 4px solid #d97706; padding: 14px 16px; margin: 14px 0; border-radius: 6px; }}
    .chart {{ width: 100%; max-width: 760px; height: 190px; background: #fff; border: 1px solid #d9deea; border-radius: 8px; }}
    .axis {{ stroke: #c8cfdd; stroke-width: 1; }}
    .chart-label {{ fill: #687386; font-size: 12px; }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    @media (max-width: 900px) {{ .grid, .two-col {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <h1>Stage B 干扰增强 Restore 训练结果分析</h1>
  <p class=\"muted\">生成时间：{esc(generated_at)} ｜ 输出目录：<code>{esc(output_dir)}</code></p>

  <div class=\"grid\">
    <div class=\"card\"><div class=\"k\">最终状态</div><div class=\"v\">{esc(final_status)}</div><div class=\"muted\">{esc(final_status_note)}</div></div>
    <div class=\"card\"><div class=\"k\">loss 最优 checkpoint</div><div class=\"v\">{esc(best_loss_epoch['checkpoint_name'])}</div><div class=\"muted\">loss {num(float(best_loss_epoch['loss']), 5)}</div></div>
    <div class=\"card\"><div class=\"k\">full test 最优候选</div><div class=\"v\">{esc(primary_card_name)}</div><div class=\"muted\">{primary_card_note}</div></div>
    <div class=\"card\"><div class=\"k\">reload smoke</div><div class=\"v\">{esc(reload_smoke.get('status'))}</div><div class=\"muted\">adapter/head 可重载</div></div>
  </div>

  <div class=\"callout\">
    <strong>结论：</strong> {esc(training_end_note)} 按 validation loss，最优 checkpoint 是 {esc(best_loss_epoch['checkpoint_name'])}；
    {candidate_conclusion}
    后续详细错误分析和模型导出建议以 full identity test 与 robustness full eval 为准。
  </div>

  <h2>1. 数据与训练配置</h2>
  <p>本轮 Stage B 使用增强 restore-only 模板，训练目标是从增强/等价 SMILES view 恢复 canonical SMILES。训练未启用 graph tensor、fragment vocab、fragment matcher 或 fragment consistency。</p>
  {table(["项目", "值"], [
        ["preview split counts", f"<code>{esc(json.dumps(preview_counts, ensure_ascii=False, sort_keys=True))}</code>"],
        ["train rows", esc(preview_counts.get("train", ""))],
        ["valid rows", esc(preview_counts.get("valid", ""))],
        ["test rows", esc(preview_counts.get("test", ""))],
        ["max_epochs", esc(training_config.get("max_epochs"))],
        ["gradient_accumulation_steps", esc(training_config.get("gradient_accumulation_steps"))],
        ["checkpoint_at_epoch_end", esc(training_config.get("checkpoint_at_epoch_end"))],
        ["early stopping", f"metric={esc(training_config.get('early_stopping_metric'))}, mode={esc(training_config.get('early_stopping_mode'))}, min_epochs={esc(training_config.get('early_stopping_min_epochs'))}, patience={esc(training_config.get('early_stopping_patience'))}"],
    ])}

  <h2>2. 训练动态</h2>
  <div class=\"two-col\">
    <div><h3>valid loss by epoch</h3>{sparkline_svg(loss_values, color="#dc2626")}</div>
    <div><h3>valid canonical_match by epoch</h3>{sparkline_svg(canonical_values, color="#16a34a")}</div>
  </div>
  <p>quick eval 共 {len(quick_metrics)} 次，每次只 decode 32 条，因此主要用于观察是否崩溃和大趋势；checkpoint epoch eval 的 decoded_sample_count 为 {esc(epoch_decode_note)}，模型选择仍需要 full test 复核。</p>
  <h3>Epoch checkpoint 指标</h3>
  {table(["epoch", "train loss mean", "valid loss", "canonical", "RDKit valid", "two attachment", "token acc", "ES wait"], epoch_table_rows)}

  <h2>3. 训练结束与主产物评估</h2>
  <p>{esc(training_end_note)}</p>
  {table(["评估项", "canonical", "loss", "RDKit valid", "two attachment"], artifact_rows)}
  <h3>Robustness 分 view / 平均统计</h3>
  {table(["split", "view", "n", "canonical", "RDKit valid", "two attachment", "exact string"], robustness_strategy_table_rows)}
  <h3>Robustness record-level 统计</h3>
  {table(["split", "aggregate", "count", "rate"], robustness_record_table_rows)}
  <div class=\"warnbox\">
    <strong>解释：</strong> final/identity/robustness 表中的生成指标以 decoded/sample_count 标注实际解码口径；
    loss/token accuracy 的 sample_count 通常覆盖完整 split。三候选选择仍以 full test 结果为准。
  </div>

  <h2>4. 三个重点 checkpoint 的 full test 对比</h2>
  <p>{candidate_section_note}</p>
  {table(["candidate", "canonical_match", "RDKit valid", "two attachment", "exact string", "loss", "failed"], candidate_rows)}
  {table(["交叉对比", "记录数"], overlap_rows)}

  <h2>5. 失败类型分析</h2>
  <p>失败分为三类：无法被 RDKit parse、attachment 数不是 2、RDKit valid 且 attachment 合格但 canonical 仍不匹配。后者代表模型生成了合法但错误的 repeat unit。</p>
  {table(["candidate", "invalid SMILES", "attachment count error", "valid but wrong canonical", "correct", "correct rate"], failure_category_rows)}

  <h3>按 target restore token 长度分桶的 full test canonical_match</h3>
  {table(["target token bucket", "n", *names], bucket_rows)}

  <h3>{esc(primary_name)} 失败样本示例</h3>
  {table(["record_id", "target tokens", "failure category", "target", "decoded"], example_rows)}

  <h2>6. 模型选择建议</h2>
  <ul>
    {model_selection_html}
  </ul>
</main>
</body>
</html>
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html_text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a detailed HTML report for Stage B restore augmentation results.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--preview-path", type=Path, default=DEFAULT_PREVIEW_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_report(output_dir=args.output_dir, preview_path=args.preview_path, report_path=args.report_path)
    print(args.report_path)


if __name__ == "__main__":
    main()
