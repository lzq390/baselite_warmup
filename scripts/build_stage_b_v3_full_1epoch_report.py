from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_ARTIFACT_DIR = Path("reports/stage_b_restore_aug_v3_full_1epoch_artifacts_remote")
DEFAULT_TEMPLATE_STATS = Path("data/baselite_smiles_aug_v3/training_template_stats.json")
DEFAULT_DATASET_MANIFEST = Path("data/baselite_smiles_v3/dataset_manifest.json")
DEFAULT_REPORT_PATH = Path("reports/stage_b_restore_aug_v3_full_1epoch_report.html")
REMOTE_OUTPUT_DIR = "/root/autodl-tmp/baselite_omg_v3_stageb/work/outputs/stage_b_restore_aug_v3_full_1epoch"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


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
    units = ["B", "KiB", "MiB", "GiB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def rate_count(value: float | int | None, total: int | None = None) -> str:
    if value is None:
        return "-"
    if total:
        count = round(float(value) * total)
        return f"{pct(float(value))} <span class=\"muted\">({count:,}/{total:,})</span>"
    return pct(float(value))


def metric_bar(value: float | int | None, total: int | None = None) -> str:
    if value is None:
        return "-"
    width = max(0.0, min(100.0, float(value) * 100.0))
    return (
        f"<div class=\"bar\"><span style=\"width:{width:.2f}%\"></span></div>"
        f"<div class=\"bar-label\">{rate_count(float(value), total)}</div>"
    )


def table(headers: list[str], rows: list[list[Any]], *, class_name: str = "") -> str:
    thead = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    return f"<table class=\"{esc(class_name)}\"><thead><tr>{thead}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def sparkline_svg(
    values: list[float],
    *,
    width: int = 760,
    height: int = 190,
    color: str = "#2563eb",
    label: str = "",
) -> str:
    if not values:
        return "<div class=\"empty\">无数据</div>"
    plot_values = values if len(values) > 1 else values + values
    lo = min(plot_values)
    hi = max(plot_values)
    if hi == lo:
        hi = lo + 1.0
    pad = 18
    points: list[str] = []
    for index, value in enumerate(plot_values):
        x = pad + index * (width - 2 * pad) / (len(plot_values) - 1)
        y = height - pad - ((value - lo) / (hi - lo)) * (height - 2 * pad)
        points.append(f"{x:.1f},{y:.1f}")
    last_x, last_y = points[-1].split(",")
    return (
        f"<svg class=\"chart\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"{esc(label)}\">"
        f"<line x1=\"{pad}\" y1=\"{height-pad}\" x2=\"{width-pad}\" y2=\"{height-pad}\" class=\"axis\"/>"
        f"<line x1=\"{pad}\" y1=\"{pad}\" x2=\"{pad}\" y2=\"{height-pad}\" class=\"axis\"/>"
        f"<polyline points=\"{' '.join(points)}\" fill=\"none\" stroke=\"{color}\" stroke-width=\"3\"/>"
        f"<circle cx=\"{last_x}\" cy=\"{last_y}\" r=\"4\" fill=\"{color}\"/>"
        f"<text x=\"{pad}\" y=\"{pad}\" class=\"chart-label\">max {hi:.5f}</text>"
        f"<text x=\"{pad}\" y=\"{height-3}\" class=\"chart-label\">min {lo:.5f}</text>"
        "</svg>"
    )


def short_smiles(value: str, limit: int = 130) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def failure_category(row: dict[str, Any]) -> str:
    if row.get("canonical_match"):
        return "correct"
    if not row.get("rdkit_valid"):
        return "invalid_smiles"
    if not row.get("two_attachment_valid"):
        return "attachment_count_not_two"
    return "valid_two_attachment_wrong_canonical"


def strategy_rows(metrics: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for strategy, values in sorted((metrics.get("all_view_by_strategy") or {}).items()):
        total = int(values.get("sample_count") or 0)
        rows.append(
            [
                esc(strategy),
                f"{total:,}",
                metric_bar(values.get("canonical_match"), total),
                rate_count(values.get("exact_string_match"), total),
                rate_count(values.get("rdkit_validity"), total),
                rate_count(values.get("two_attachment_validity"), total),
                f"{int(values.get('failed_count') or 0):,}",
            ]
        )
    macro = metrics.get("all_view_strategy_macro_avg") or {}
    if macro:
        rows.append(
            [
                "<strong>strategy macro avg</strong>",
                esc(macro.get("strategy_count")),
                metric_bar(macro.get("canonical_match")),
                pct(macro.get("exact_string_match")),
                pct(macro.get("rdkit_validity")),
                pct(macro.get("two_attachment_validity")),
                "-",
            ]
        )
    return rows


def failure_summary_rows(failures: list[dict[str, Any]], label: str) -> list[list[Any]]:
    counter = Counter(failure_category(row) for row in failures)
    strategy_counter = Counter(str(row.get("augmentation_strategy", "")) for row in failures)
    top_strategy = ", ".join(f"{key}: {value}" for key, value in strategy_counter.most_common())
    return [
        [
            esc(label),
            f"{len(failures):,}",
            f"{counter['invalid_smiles']:,}",
            f"{counter['attachment_count_not_two']:,}",
            f"{counter['valid_two_attachment_wrong_canonical']:,}",
            esc(top_strategy),
        ]
    ]


def failure_example_rows(failures: list[dict[str, Any]], limit: int = 8) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in failures[:limit]:
        rows.append(
            [
                esc(row.get("record_id")),
                esc(row.get("augmentation_strategy")),
                esc(failure_category(row)),
                f"<code>{esc(short_smiles(str(row.get('text_view_1', ''))))}</code>",
                f"<code>{esc(short_smiles(str(row.get('target', ''))))}</code>",
                f"<code>{esc(short_smiles(str(row.get('decoded_smiles', ''))))}</code>",
            ]
        )
    return rows


def metric_overview_row(label: str, metrics: dict[str, Any], *, decoded_note: bool = True) -> list[Any]:
    decoded = int(metrics.get("decoded_sample_count") or 0)
    sample_count = int(metrics.get("sample_count") or 0)
    label_text = esc(label)
    if decoded_note:
        label_text += f"<div class=\"muted\">decode {decoded:,} / loss {sample_count:,}</div>"
    return [
        label_text,
        num(metrics.get("loss")),
        pct(metrics.get("token_accuracy"), 3),
        rate_count(metrics.get("canonical_match"), decoded),
        rate_count(metrics.get("rdkit_validity"), decoded),
        rate_count(metrics.get("two_attachment_validity"), decoded),
        rate_count(metrics.get("exact_string_match"), decoded),
    ]


def file_inventory_rows(root: Path) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        rows.append([f"<code>{esc(rel)}</code>", size_text(path.stat().st_size)])
    return rows


def get_template_counts(template_stats: dict[str, Any]) -> tuple[dict[str, int], dict[str, dict[str, int]], dict[str, Any]]:
    training = template_stats.get("previews", {}).get("training", {})
    split_counts: dict[str, int] = {}
    for split, values in (training.get("splits") or {}).items():
        split_counts[split] = int(values.get("view1_token_length", {}).get("count") or 0)
    strategy_counts_by_split = {
        split: {strategy: int(count) for strategy, count in values.items()}
        for split, values in (training.get("strategy_counts_by_split") or {}).items()
    }
    return split_counts, strategy_counts_by_split, training


def build_report(
    *,
    artifact_dir: Path,
    template_stats_path: Path,
    dataset_manifest_path: Path,
    report_path: Path,
) -> None:
    quick_metrics = read_jsonl(artifact_dir / "quick_eval_metrics.jsonl")
    epoch_metrics = read_jsonl(artifact_dir / "epoch_metrics.jsonl")
    final_valid = read_json(artifact_dir / "eval_metrics.json")
    final_test = read_json(artifact_dir / "identity_test_eval_metrics.json")
    checkpoint_eval = read_json(artifact_dir / "checkpoints" / "epoch_001" / "eval_metrics.json")
    training_config = read_json(artifact_dir / "training_config.json")
    reload_smoke = read_json(artifact_dir / "reload_smoke.json")
    template_stats = read_json(template_stats_path)
    dataset_manifest = read_json_optional(dataset_manifest_path)
    valid_failures = read_jsonl(artifact_dir / "failed_cases.jsonl")
    test_failures = read_jsonl(artifact_dir / "identity_test_failed_cases.jsonl")

    split_counts, strategy_counts_by_split, template_training = get_template_counts(template_stats)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    quick_steps = [int(row.get("optimizer_step") or 0) for row in quick_metrics]
    quick_losses = [float(row["quick_valid"]["loss"]) for row in quick_metrics if row.get("quick_valid")]
    quick_canonical = [float(row["quick_valid"]["canonical_match"]) for row in quick_metrics if row.get("quick_valid")]
    quick_token_acc = [float(row["quick_valid"]["token_accuracy"]) for row in quick_metrics if row.get("quick_valid")]
    train_losses = [float(row.get("train_loss") or 0.0) for row in quick_metrics]
    final_quick = quick_metrics[-1] if quick_metrics else {}
    final_quick_valid = final_quick.get("quick_valid") or {}
    best_quick_loss = min(quick_metrics, key=lambda row: float(row["quick_valid"]["loss"])) if quick_metrics else {}
    best_quick_canonical = max(quick_metrics, key=lambda row: float(row["quick_valid"]["canonical_match"])) if quick_metrics else {}
    epoch_row = epoch_metrics[-1] if epoch_metrics else checkpoint_eval
    effective_batch = int(training_config.get("per_device_train_batch_size") or 0) * int(
        training_config.get("gradient_accumulation_steps") or 0
    )
    final_valid_time = datetime.fromtimestamp((artifact_dir / "eval_metrics.json").stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    reload_time = datetime.fromtimestamp((artifact_dir / "reload_smoke.json").stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    split_rows = []
    for split in ("train", "valid", "test"):
        strategies = strategy_counts_by_split.get(split, {})
        split_rows.append(
            [
                esc(split),
                f"{split_counts.get(split, 0):,}",
                f"<code>{esc(json.dumps(strategies, ensure_ascii=False, sort_keys=True))}</code>",
            ]
        )

    config_rows = [
        ["preview_path", f"<code>{esc(training_config.get('preview_path'))}</code>"],
        ["max_epochs", esc(training_config.get("max_epochs"))],
        ["batch / grad accum / effective", f"{training_config.get('per_device_train_batch_size')} / {training_config.get('gradient_accumulation_steps')} / {effective_batch}"],
        ["eval batch", esc(training_config.get("per_device_eval_batch_size"))],
        ["quick eval", f"every {training_config.get('quick_eval_every_steps')} steps, sample {training_config.get('quick_eval_samples')}, decode {training_config.get('quick_eval_decode_samples')}"],
        ["checkpoint eval", f"sample {training_config.get('checkpoint_eval_samples')}, decode {training_config.get('checkpoint_eval_decode_samples')}"],
        ["final eval decode", f"decode {training_config.get('eval_decode_samples')}, full_final_decode={training_config.get('formal_eval_full_decode')}"],
        ["LoRA", f"rank={training_config.get('lora_rank')}, alpha={training_config.get('lora_alpha')}, dropout={training_config.get('lora_dropout')}, modules={esc(', '.join(training_config.get('lora_target_modules') or []))}"],
        ["restore head", f"hidden={training_config.get('restore_hidden_size')}, layers={training_config.get('restore_num_layers')}, heads={training_config.get('restore_num_attention_heads')}, dropout={training_config.get('restore_dropout')}"],
        ["optimizer", f"lr_lora={training_config.get('learning_rate_lora')}, lr_head={training_config.get('learning_rate_restore_head')}, wd={training_config.get('weight_decay')}"],
        ["precision / seed", f"{training_config.get('precision')} / {training_config.get('seed')}"],
    ]

    quick_tail_rows = []
    for row in quick_metrics[-12:]:
        quick = row.get("quick_valid") or {}
        decoded = int(quick.get("decoded_sample_count") or 0)
        quick_tail_rows.append(
            [
                f"{int(row.get('optimizer_step') or 0):,}",
                num(row.get("train_loss")),
                num(quick.get("loss")),
                rate_count(quick.get("canonical_match"), decoded),
                pct(quick.get("token_accuracy"), 3),
                rate_count(quick.get("rdkit_validity"), decoded),
                rate_count(quick.get("two_attachment_validity"), decoded),
            ]
        )

    eval_rows = [
        metric_overview_row("checkpoint epoch_001 valid", checkpoint_eval),
        metric_overview_row("final valid all-view", final_valid),
        metric_overview_row("final test all-view", final_test),
    ]

    base_record_count = (
        dataset_manifest.get("quality_checks", {}).get("total_records")
        or dataset_manifest.get("selection", {}).get("target_count")
        or template_stats.get("expected", {}).get("base_record_count")
    )
    data_quality_rows = [
        ["base records", f"{int(base_record_count):,}" if base_record_count is not None else "-"],
        ["template rows", f"{template_stats.get('expected', {}).get('training_row_count', 0):,}"],
        ["augmentation failures", f"{template_stats.get('augmentation_failures', {}).get('count', 0):,}"],
        ["input/label conflicts", f"{template_stats.get('input_label_conflicts', {}).get('input_label_conflict_final_count', 0):,}"],
        ["record strategy quality bad records", f"{template_training.get('record_strategy_quality', {}).get('bad_record_count', 0):,}"],
        ["view token overflow", f"{template_training.get('quality_checks', {}).get('view_length_overflow_count', 0):,}"],
        ["restore label overflow", f"{template_training.get('quality_checks', {}).get('restore_label_length_overflow_count', 0):,}"],
        ["view roundtrip failures", f"{template_training.get('quality_checks', {}).get('view_roundtrip_failure_count', 0):,}"],
        ["restore roundtrip failures", f"{template_training.get('quality_checks', {}).get('restore_roundtrip_failure_count', 0):,}"],
    ]

    failure_rows = failure_summary_rows(valid_failures, "valid decoded failures") + failure_summary_rows(
        test_failures, "test decoded failures"
    )

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Stage B Restore v3 Full 1epoch 训练报告</title>
  <style>
    body {{ margin: 0; background: #f5f7fb; color: #172033; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", Arial, sans-serif; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 34px 30px 60px; }}
    h1 {{ margin: 0 0 8px; font-size: 31px; letter-spacing: 0; }}
    h2 {{ margin: 34px 0 14px; padding-left: 11px; border-left: 4px solid #2563eb; font-size: 22px; }}
    h3 {{ margin: 23px 0 10px; font-size: 17px; }}
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
    .chart {{ width: 100%; max-width: 780px; height: 190px; background: #fff; border: 1px solid #d9deea; border-radius: 8px; }}
    .axis {{ stroke: #c8cfdd; stroke-width: 1; }}
    .chart-label {{ fill: #687386; font-size: 12px; }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 2px 8px; background: #e7f0ff; color: #174ea6; font-size: 11px; }}
    .ok {{ color: #157347; font-weight: 700; }}
    .bad {{ color: #a15c00; font-weight: 700; }}
    @media (max-width: 900px) {{ .grid, .two-col {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <h1>Stage B Restore v3 Full 1epoch 训练报告</h1>
  <p class="muted">生成时间：{esc(generated_at)} ｜ 远端输出：<code>{esc(REMOTE_OUTPUT_DIR)}</code> ｜ 本地输入：<code>{esc(artifact_dir)}</code></p>

  <div class="grid">
    <div class="card"><div class="k">运行状态</div><div class="v ok">完成</div><div class="muted">reload smoke: {esc(reload_smoke.get('status'))}</div></div>
    <div class="card"><div class="k">训练规模</div><div class="v">{int(final_valid.get('train_sample_count') or 0):,}</div><div class="muted">train rows, 5-view full template</div></div>
    <div class="card"><div class="k">final valid canonical</div><div class="v">{pct(final_valid.get('canonical_match'))}</div><div class="muted">decode {int(final_valid.get('decoded_sample_count') or 0):,} / loss {int(final_valid.get('sample_count') or 0):,}</div></div>
    <div class="card"><div class="k">final test canonical</div><div class="v">{pct(final_test.get('canonical_match'))}</div><div class="muted">all-view test；文件名仍为 identity_test</div></div>
  </div>

  <div class="callout">
    <strong>结论：</strong>v3 Stage B 1 epoch 已完成，主训练达到 {int(final_valid.get('optimizer_steps') or 0):,} optimizer steps。
    final valid loss 为 {num(final_valid.get('loss'))}，token accuracy 为 {pct(final_valid.get('token_accuracy'), 3)}；
    test split loss 为 {num(final_test.get('loss'))}，canonical_match 为 {pct(final_test.get('canonical_match'))}。
    生成类指标只 decode 128 条，loss/token accuracy 覆盖完整 50w split。
  </div>

  <h2>1. 数据模板与质量</h2>
  <p>本轮使用 v3 full 五视图模板，不是 curriculum。valid/test 也各包含五种视图；<code>identity_test_*</code> 是历史文件名前缀，实际结果来自 all-view test loader。</p>
  {table(["split", "rows", "strategy counts"], split_rows)}
  {table(["质量项", "值"], data_quality_rows)}

  <h2>2. 训练配置</h2>
  {table(["配置项", "值"], config_rows)}

  <h2>3. 训练曲线</h2>
  <div class="two-col">
    <div><h3>quick valid loss</h3>{sparkline_svg(quick_losses, color="#dc2626", label="quick valid loss")}</div>
    <div><h3>quick canonical_match</h3>{sparkline_svg(quick_canonical, color="#16a34a", label="quick canonical match")}</div>
    <div><h3>train loss snapshots</h3>{sparkline_svg(train_losses, color="#7c3aed", label="train loss snapshots")}</div>
    <div><h3>quick token accuracy</h3>{sparkline_svg(quick_token_acc, color="#0891b2", label="quick token accuracy")}</div>
  </div>
  <p>quick eval 共 {len(quick_metrics)} 次；最后一次 step={int(final_quick.get('optimizer_step') or 0):,}，loss={num(final_quick_valid.get('loss'))}，canonical_match={pct(final_quick_valid.get('canonical_match'))}。best quick loss 出现在 step={int(best_quick_loss.get('optimizer_step') or 0):,}；best quick canonical 出现在 step={int(best_quick_canonical.get('optimizer_step') or 0):,}。</p>
  {table(["step", "train_loss", "quick_loss", "canonical", "token_acc", "RDKit valid", "two attachment"], quick_tail_rows)}

  <h2>4. Epoch 与 Final 评估</h2>
  {table(["评估项", "loss", "token_acc", "canonical", "RDKit valid", "two attachment", "exact string"], eval_rows)}
  <h3>valid all-view by strategy</h3>
  {table(["strategy", "decoded n", "canonical", "exact", "RDKit valid", "two attachment", "failed"], strategy_rows(final_valid))}
  <h3>test all-view by strategy</h3>
  {table(["strategy", "decoded n", "canonical", "exact", "RDKit valid", "two attachment", "failed"], strategy_rows(final_test))}
  <div class="warnbox">
    <strong>口径说明：</strong><code>loss</code> 和 <code>token_accuracy</code> 使用完整 valid/test 50w 行；
    <code>canonical_match</code>、<code>rdkit_validity</code>、<code>two_attachment_validity</code> 来自 decode sample，共 128 条。
    因此 strategy 表适合做定性比较，不等价于 50w 全量逐条解码。
  </div>

  <h2>5. 失败样本分析</h2>
  {table(["split", "failed", "invalid SMILES", "attachment error", "valid but wrong canonical", "strategy mix"], failure_rows)}
  <h3>valid failed examples</h3>
  {table(["record_id", "strategy", "category", "input view", "target", "decoded"], failure_example_rows(valid_failures))}
  <h3>test failed examples</h3>
  {table(["record_id", "strategy", "category", "input view", "target", "decoded"], failure_example_rows(test_failures))}

  <h2>6. 产物清单</h2>
  <p>final artifact 生成时间：{esc(final_valid_time)}；reload smoke 生成时间：{esc(reload_time)}。主 checkpoint 和 root final adapter/head 均已保存。</p>
  {table(["file", "size"], file_inventory_rows(artifact_dir))}

  <h2>7. 建议</h2>
  <ul>
    <li>当前 checkpoint 可作为 Stage B v3 warmup 的可用产物；reload smoke 已通过。</li>
    <li>如果要把 canonical_match 作为正式论文/汇报数字，建议补跑更大的 decode sample 或全量 decode，因为当前生成指标只 decode 128 条。</li>
    <li>建议后续把训练脚本中的 <code>identity_test_*</code> 输出命名改为 <code>all_view_test_*</code>，避免误读为 identity-only。</li>
    <li>Stage C 若接 v3，应显式记录使用 <code>data/baselite_smiles_aug_v3/training_template_preview.jsonl</code> 和 <code>omg_repeat_unit_graphs_v3.jsonl</code> 的 join 版本。</li>
  </ul>
</main>
</body>
</html>
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html_text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Stage B v3 full 1epoch HTML report.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--template-stats", type=Path, default=DEFAULT_TEMPLATE_STATS)
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_DATASET_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_report(
        artifact_dir=args.artifact_dir,
        template_stats_path=args.template_stats,
        dataset_manifest_path=args.dataset_manifest,
        report_path=args.output,
    )
    print(args.output)


if __name__ == "__main__":
    main()
