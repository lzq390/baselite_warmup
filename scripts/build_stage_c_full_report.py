from __future__ import annotations

import argparse
import html
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import seaborn as sns


DEFAULT_STAGE_C_ARTIFACTS = Path("reports/stage_c_non_vocab_aug_v2_full_30epoch_artifacts")
DEFAULT_STAGE_B_ARTIFACTS = Path("reports/stage_b_restore_aug_v2_full_20epoch_artifacts")
DEFAULT_REPORT_PATH = Path("reports/stage_c_non_vocab_aug_v2_full_30epoch_report.html")
DEFAULT_CHART_DIR = Path("reports/stage_c_non_vocab_aug_v2_full_30epoch_charts")

FONT_FAMILY = ["DejaVu Sans", "sans-serif"]
MONO_FONT_FAMILY = ["SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono", "monospace"]

TOKENS = {
    "surface": "#FCFCFD",
    "panel": "#FFFFFF",
    "ink": "#1F2430",
    "muted": "#6F768A",
    "grid": "#E6E8F0",
    "axis": "#D7DBE7",
}

COLORS = {
    "blue": "#A3BEFA",
    "blue_mid": "#5477C4",
    "blue_dark": "#2E4780",
    "gold": "#FFE15B",
    "gold_mid": "#B8A037",
    "orange": "#F0986E",
    "orange_mid": "#CC6F47",
    "olive": "#A3D576",
    "olive_mid": "#71B436",
    "pink": "#F390CA",
    "pink_mid": "#BD569B",
    "neutral": "#C5CAD3",
    "neutral_mid": "#7A828F",
    "neutral_dark": "#464C55",
}

STRATEGY_LABELS = {
    "identity": "identity",
    "attachment_rooted_smiles": "attachment-rooted",
    "light_denoise": "light-denoise",
    "direction_flip": "direction-flip",
    "rdkit_random_smiles": "rdkit-random",
}

STRATEGY_DESCRIPTIONS = {
    "identity": "原始规范视图",
    "attachment_rooted_smiles": "attachment-rooted 视图",
    "light_denoise": "轻量去噪视图",
    "direction_flip": "方向翻转视图",
    "rdkit_random_smiles": "RDKit random SMILES 视图",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json(path)


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


def pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.{digits}f}%"


def pp(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.{digits}f} pp"


def num(value: float | int | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:.{digits}f}"


def count_rate(rate: float | None, total: int | None) -> str:
    if rate is None:
        return "-"
    if total:
        count = round(rate * total)
        return f"{pct(rate)} <span class=\"muted\">({count:,}/{total:,})</span>"
    return pct(rate)


def table(headers: list[str], rows: list[list[Any]], class_name: str = "") -> str:
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    return (
        f"<div class=\"table-wrap\"><table class=\"{esc(class_name)}\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def pill(ok: bool, text: str | None = None) -> str:
    label = text if text is not None else ("PASS" if ok else "CHECK")
    cls = "ok" if ok else "warn"
    return f"<span class=\"pill {cls}\">{esc(label)}</span>"


def metric_card(label: str, value: str, note: str) -> str:
    return (
        "<div class=\"metric\">"
        f"<div class=\"metric-label\">{esc(label)}</div>"
        f"<div class=\"metric-value\">{value}</div>"
        f"<div class=\"metric-note\">{note}</div>"
        "</div>"
    )


def failure_category(row: dict[str, Any]) -> str:
    if not row.get("rdkit_valid"):
        return "invalid_smiles"
    if not row.get("two_attachment_valid"):
        return "attachment_count_not_two"
    return "valid_two_attachment_wrong_canonical"


def summarize_failures(path: Path) -> dict[str, Any]:
    rows = read_jsonl(path)
    category_counts = Counter(failure_category(row) for row in rows)
    strategy_counts = Counter(row.get("augmentation_strategy", "unknown") for row in rows)
    reason_counts = Counter(str(row.get("failure_reason")) for row in rows)
    return {
        "file": path.name,
        "failed_count": len(rows),
        "category_counts": dict(category_counts),
        "strategy_counts": dict(strategy_counts),
        "reason_counts": dict(reason_counts),
    }


def retrieval_rank_summary(path: Path) -> dict[str, Any]:
    rows = read_jsonl(path)
    ranks: Counter[int | str] = Counter()
    margins: list[float] = []
    top_scores: list[float] = []
    for row in rows:
        record_id = row.get("record_id")
        ranked = row.get("ranked_graph_record_ids", [])
        scores = row.get("scores", [])
        try:
            rank: int | str = ranked.index(record_id) + 1
        except ValueError:
            rank = "miss"
        ranks[rank] += 1
        if scores:
            top_scores.append(float(scores[0]))
        if len(scores) >= 2:
            margins.append(float(scores[0]) - float(scores[1]))
    total = len(rows)
    top1 = ranks.get(1, 0) / total if total else None
    top5 = sum(count for rank, count in ranks.items() if isinstance(rank, int) and rank <= 5) / total if total else None
    return {
        "file": path.name,
        "sample_count": total,
        "rank_counts": {str(rank): count for rank, count in ranks.items()},
        "top1": top1,
        "top5": top5,
        "mean_top_score": sum(top_scores) / len(top_scores) if top_scores else None,
        "mean_top1_margin": sum(margins) / len(margins) if margins else None,
    }


def setup_plot_style() -> None:
    sns.set_theme(style="whitegrid")
    plt.rcParams.update(
        {
            "figure.facecolor": TOKENS["surface"],
            "axes.facecolor": TOKENS["panel"],
            "axes.edgecolor": TOKENS["axis"],
            "axes.labelcolor": TOKENS["ink"],
            "axes.titlecolor": TOKENS["ink"],
            "xtick.color": TOKENS["muted"],
            "ytick.color": TOKENS["muted"],
            "grid.color": TOKENS["grid"],
            "grid.linewidth": 1.0,
            "font.family": FONT_FAMILY,
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def add_chart_header(fig: plt.Figure, title: str, subtitle: str) -> None:
    fig.text(0.02, 0.965, title, ha="left", va="top", fontsize=15, color=TOKENS["ink"], weight="bold")
    fig.text(0.02, 0.925, subtitle, ha="left", va="top", fontsize=10, color=TOKENS["muted"])


def save_chart(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor=TOKENS["surface"])
    plt.close(fig)


def generate_charts(
    *,
    epoch_df: pd.DataFrame,
    final_valid: dict[str, Any],
    all_view_test: dict[str, Any],
    robustness_valid: dict[str, Any],
    robustness_test: dict[str, Any],
    failure_summaries: dict[str, dict[str, Any]],
    stage_b_valid: dict[str, Any] | None,
    stage_b_test: dict[str, Any] | None,
    stage_b_robustness_valid: dict[str, Any] | None,
    stage_b_robustness_test: dict[str, Any] | None,
    chart_dir: Path,
) -> dict[str, str]:
    setup_plot_style()
    chart_dir.mkdir(parents=True, exist_ok=True)
    chart_paths: dict[str, str] = {}

    metric_rows = []
    metric_map = {
        "canonical_match": "Canonical",
        "exact_string_match": "Exact",
        "rdkit_validity": "RDKit valid",
        "two_attachment_validity": "Two attach.",
    }
    for metric, label in metric_map.items():
        for _, row in epoch_df.iterrows():
            metric_rows.append({"epoch": int(row["checkpoint_epoch"]), "Metric": label, "Rate": float(row[metric])})
    trend_df = pd.DataFrame(metric_rows)
    fig, ax = plt.subplots(figsize=(10.5, 5.1))
    palette = {
        "Canonical": COLORS["blue_mid"],
        "Exact": COLORS["pink_mid"],
        "RDKit valid": COLORS["olive_mid"],
        "Two attach.": COLORS["orange_mid"],
    }
    sns.lineplot(data=trend_df, x="epoch", y="Rate", hue="Metric", marker="o", linewidth=2.0, palette=palette, ax=ax)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Rate")
    ax.set_ylim(0, 1.02)
    ax.legend(loc="lower right", frameon=False, ncol=2)
    add_chart_header(fig, "Epoch restore metric trends", "Valid split; 5,790 decoded samples at every checkpoint")
    fig.subplots_adjust(top=0.82, left=0.08, right=0.98, bottom=0.12)
    path = chart_dir / "epoch_restore_metric_trends.png"
    save_chart(fig, path)
    chart_paths["epoch_restore_metric_trends"] = str(path)

    loss_rows = []
    for _, row in epoch_df.iterrows():
        epoch = int(row["checkpoint_epoch"])
        loss_rows.extend(
            [
                {"epoch": epoch, "Loss": "Total", "Value": float(row["loss"])},
                {"epoch": epoch, "Loss": "Restore", "Value": float(row["restore_loss"])},
                {"epoch": epoch, "Loss": "0.2 x Align", "Value": float(row["weighted_align_loss"])},
            ]
        )
    loss_df = pd.DataFrame(loss_rows)
    fig, ax = plt.subplots(figsize=(10.5, 5.1))
    sns.lineplot(
        data=loss_df,
        x="epoch",
        y="Value",
        hue="Loss",
        marker="o",
        linewidth=2.0,
        palette={"Total": COLORS["blue_mid"], "Restore": COLORS["orange_mid"], "0.2 x Align": COLORS["neutral_mid"]},
        ax=ax,
    )
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Loss")
    ax.legend(loc="upper right", frameon=False)
    add_chart_header(fig, "Loss components over epochs", "Stage C full validation objective: L_restore + 0.2 x L_align")
    fig.subplots_adjust(top=0.82, left=0.08, right=0.98, bottom=0.12)
    path = chart_dir / "loss_components_over_epochs.png"
    save_chart(fig, path)
    chart_paths["loss_components_over_epochs"] = str(path)

    retrieval_rows = []
    for _, row in epoch_df.iterrows():
        epoch = int(row["checkpoint_epoch"])
        retrieval_rows.extend(
            [
                {"epoch": epoch, "Direction": "Text -> graph", "Metric": "Top-1", "Rate": float(row["text_to_graph_top1"])},
                {"epoch": epoch, "Direction": "Graph -> text", "Metric": "Top-1", "Rate": float(row["graph_to_text_top1"])},
                {"epoch": epoch, "Direction": "Text -> graph", "Metric": "Top-5", "Rate": float(row["text_to_graph_top5"])},
                {"epoch": epoch, "Direction": "Graph -> text", "Metric": "Top-5", "Rate": float(row["graph_to_text_top5"])},
            ]
        )
    retrieval_df = pd.DataFrame(retrieval_rows)
    fig, axes = plt.subplots(1, 2, figsize=(12.2, 5.2), sharex=True)
    for ax, metric in zip(axes, ["Top-1", "Top-5"], strict=True):
        subset = retrieval_df[retrieval_df["Metric"] == metric]
        sns.lineplot(
            data=subset,
            x="epoch",
            y="Rate",
            hue="Direction",
            marker="o",
            linewidth=2.0,
            palette={"Text -> graph": COLORS["blue_mid"], "Graph -> text": COLORS["gold_mid"]},
            ax=ax,
        )
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
        ax.set_title(metric, loc="left", fontsize=11, weight="bold")
        ax.set_xlabel("Epoch")
        ax.set_ylabel("Rate")
        ax.set_ylim(0, 1.04)
        ax.legend(frameon=False, loc="lower right")
    add_chart_header(fig, "Retrieval quality over epochs", "Valid split; graph/text retrieval evaluated on 1,158 deduplicated graph records")
    fig.subplots_adjust(top=0.78, left=0.07, right=0.98, bottom=0.12, wspace=0.18)
    path = chart_dir / "retrieval_quality_over_epochs.png"
    save_chart(fig, path)
    chart_paths["retrieval_quality_over_epochs"] = str(path)

    strategy_rows = []
    for split_label, metrics, source_key in [
        ("Valid", final_valid, "all_view_by_strategy"),
        ("Test", all_view_test, "all_view_by_strategy"),
        ("Robust test", robustness_test, "robustness_by_strategy"),
    ]:
        for strategy, values in (metrics.get(source_key) or {}).items():
            strategy_rows.append(
                {
                    "Strategy": STRATEGY_LABELS.get(strategy, strategy),
                    "Split": split_label,
                    "Canonical": float(values["canonical_match"]),
                }
            )
    strategy_df = pd.DataFrame(strategy_rows)
    strategy_order = [
        "identity",
        "attachment-rooted",
        "light-denoise",
        "direction-flip",
        "rdkit-random",
    ]
    fig, ax = plt.subplots(figsize=(10.8, 5.6))
    sns.barplot(
        data=strategy_df,
        y="Strategy",
        x="Canonical",
        hue="Split",
        order=[label for label in strategy_order if label in set(strategy_df["Strategy"])],
        palette={"Valid": COLORS["blue_mid"], "Test": COLORS["gold_mid"], "Robust test": COLORS["orange_mid"]},
        ax=ax,
    )
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.set_xlim(0, 0.9)
    ax.set_xlabel("Canonical match")
    ax.set_ylabel("")
    ax.legend(frameon=False, loc="lower right")
    add_chart_header(fig, "Canonical match by augmentation strategy", "n=1,158 per strategy; robustness excludes identity")
    fig.subplots_adjust(top=0.82, left=0.18, right=0.98, bottom=0.12)
    path = chart_dir / "canonical_match_by_strategy.png"
    save_chart(fig, path)
    chart_paths["canonical_match_by_strategy"] = str(path)

    failure_rows = []
    category_labels = {
        "invalid_smiles": "Invalid SMILES",
        "valid_two_attachment_wrong_canonical": "Valid but wrong",
        "attachment_count_not_two": "Attachment count",
    }
    split_labels = {
        "failed_cases.jsonl": "Valid",
        "all_view_test_failed_cases.jsonl": "Test",
        "robustness_valid_failed_cases.jsonl": "Robust valid",
        "robustness_test_failed_cases.jsonl": "Robust test",
    }
    for file_name, summary in failure_summaries.items():
        for category, label in category_labels.items():
            failure_rows.append(
                {
                    "Split": split_labels[file_name],
                    "Failure category": label,
                    "Count": summary["category_counts"].get(category, 0),
                }
            )
    failure_df = pd.DataFrame(failure_rows)
    fig, ax = plt.subplots(figsize=(10.8, 5.2))
    bottom_by_split: dict[str, int] = {}
    palette_stack = {
        "Invalid SMILES": COLORS["orange_mid"],
        "Valid but wrong": COLORS["blue_mid"],
        "Attachment count": COLORS["neutral_mid"],
    }
    split_order = ["Valid", "Test", "Robust valid", "Robust test"]
    for category in ["Invalid SMILES", "Valid but wrong", "Attachment count"]:
        values = [
            int(failure_df[(failure_df["Split"] == split_label) & (failure_df["Failure category"] == category)]["Count"].sum())
            for split_label in split_order
        ]
        bottoms = [bottom_by_split.get(split_label, 0) for split_label in split_order]
        ax.barh(split_order, values, left=bottoms, label=category, color=palette_stack[category], edgecolor=TOKENS["panel"])
        for split_label, value in zip(split_order, values, strict=True):
            bottom_by_split[split_label] = bottom_by_split.get(split_label, 0) + value
    ax.set_xlabel("Failed canonical-match cases")
    ax.set_ylabel("")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3)
    add_chart_header(fig, "Failure mix by evaluation split", "Failed cases are canonical non-matches; invalid SMILES and valid-wrong outputs dominate")
    fig.subplots_adjust(top=0.82, left=0.16, right=0.98, bottom=0.24)
    path = chart_dir / "failure_mix_by_split.png"
    save_chart(fig, path)
    chart_paths["failure_mix_by_split"] = str(path)

    if stage_b_valid and stage_b_test and stage_b_robustness_valid and stage_b_robustness_test:
        comparison_rows = [
            {"Metric": "Valid canonical", "Stage": "Stage B full", "Rate": float(stage_b_valid["canonical_match"])},
            {"Metric": "Valid canonical", "Stage": "Stage C full", "Rate": float(final_valid["canonical_match"])},
            {"Metric": "Test canonical", "Stage": "Stage B full", "Rate": float(stage_b_test["canonical_match"])},
            {"Metric": "Test canonical", "Stage": "Stage C full", "Rate": float(all_view_test["canonical_match"])},
            {"Metric": "Robust valid canonical", "Stage": "Stage B full", "Rate": float(stage_b_robustness_valid["canonical_match"])},
            {"Metric": "Robust valid canonical", "Stage": "Stage C full", "Rate": float(robustness_valid["canonical_match"])},
            {"Metric": "Robust test canonical", "Stage": "Stage B full", "Rate": float(stage_b_robustness_test["canonical_match"])},
            {"Metric": "Robust test canonical", "Stage": "Stage C full", "Rate": float(robustness_test["canonical_match"])},
        ]
        comparison_df = pd.DataFrame(comparison_rows)
        fig, ax = plt.subplots(figsize=(11.2, 5.4))
        sns.barplot(
            data=comparison_df,
            y="Metric",
            x="Rate",
            hue="Stage",
            palette={"Stage B full": COLORS["neutral_mid"], "Stage C full": COLORS["blue_mid"]},
            ax=ax,
        )
        ax.xaxis.set_major_formatter(mticker.PercentFormatter(1.0))
        ax.set_xlim(0, 0.65)
        ax.set_xlabel("Canonical match")
        ax.set_ylabel("")
        ax.legend(frameon=False, loc="lower right")
        add_chart_header(fig, "Stage B vs Stage C restore-only metrics", "Same aug_v2 data family; compare restore metrics only, not joint Stage C loss")
        fig.subplots_adjust(top=0.82, left=0.23, right=0.98, bottom=0.12)
        path = chart_dir / "stage_b_vs_stage_c_restore_metrics.png"
        save_chart(fig, path)
        chart_paths["stage_b_vs_stage_c_restore_metrics"] = str(path)

    return chart_paths


def stage_b_test_metrics(stage_b_artifacts: Path) -> dict[str, Any] | None:
    return read_json_optional(stage_b_artifacts / "all_view_test_eval_metrics.json") or read_json_optional(
        stage_b_artifacts / "identity_test_eval_metrics.json"
    )


def build_report(stage_c_artifacts: Path, stage_b_artifacts: Path, report_path: Path, chart_dir: Path) -> None:
    final_valid = read_json(stage_c_artifacts / "eval_metrics.json")
    all_view_test = read_json(stage_c_artifacts / "all_view_test_eval_metrics.json")
    robustness_valid = read_json(stage_c_artifacts / "robustness_valid_eval_metrics.json")
    robustness_test = read_json(stage_c_artifacts / "robustness_test_eval_metrics.json")
    training_config = read_json(stage_c_artifacts / "training_config.json")
    reload_check = read_json(stage_c_artifacts / "reload_check.json")
    epoch_rows = read_jsonl(stage_c_artifacts / "epoch_metrics.jsonl")
    epoch_df = pd.DataFrame(epoch_rows)

    stage_b_valid = read_json_optional(stage_b_artifacts / "eval_metrics.json")
    stage_b_test = stage_b_test_metrics(stage_b_artifacts)
    stage_b_robustness_valid = read_json_optional(stage_b_artifacts / "robustness_valid_eval_metrics.json")
    stage_b_robustness_test = read_json_optional(stage_b_artifacts / "robustness_test_eval_metrics.json")

    failure_files = [
        "failed_cases.jsonl",
        "all_view_test_failed_cases.jsonl",
        "robustness_valid_failed_cases.jsonl",
        "robustness_test_failed_cases.jsonl",
    ]
    failure_summaries = {file_name: summarize_failures(stage_c_artifacts / file_name) for file_name in failure_files}
    retrieval_summaries = {
        "valid": retrieval_rank_summary(stage_c_artifacts / "retrieval_predictions.jsonl"),
        "test": retrieval_rank_summary(stage_c_artifacts / "all_view_test_retrieval_predictions.jsonl"),
    }

    chart_paths = generate_charts(
        epoch_df=epoch_df,
        final_valid=final_valid,
        all_view_test=all_view_test,
        robustness_valid=robustness_valid,
        robustness_test=robustness_test,
        failure_summaries=failure_summaries,
        stage_b_valid=stage_b_valid,
        stage_b_test=stage_b_test,
        stage_b_robustness_valid=stage_b_robustness_valid,
        stage_b_robustness_test=stage_b_robustness_test,
        chart_dir=chart_dir,
    )

    best_restore_epoch = min(epoch_rows, key=lambda row: float(row["restore_loss"]))
    best_canonical_epoch = max(epoch_rows, key=lambda row: float(row["canonical_match"]))
    final_epoch = epoch_rows[-1]
    monitor_best_checkpoint = str(final_valid.get("best_early_stopping_checkpoint") or "")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    final_fail_count = failure_summaries["failed_cases.jsonl"]["failed_count"]
    final_failure_categories = failure_summaries["failed_cases.jsonl"]["category_counts"]
    invalid_rate = final_failure_categories.get("invalid_smiles", 0) / final_fail_count if final_fail_count else 0.0
    valid_wrong_rate = (
        final_failure_categories.get("valid_two_attachment_wrong_canonical", 0) / final_fail_count if final_fail_count else 0.0
    )

    stage_b_compare_available = bool(stage_b_valid and stage_b_test and stage_b_robustness_valid and stage_b_robustness_test)
    if stage_b_compare_available:
        valid_delta = float(final_valid["canonical_match"]) - float(stage_b_valid["canonical_match"])
        test_delta = float(all_view_test["canonical_match"]) - float(stage_b_test["canonical_match"])
        robust_test_delta = float(robustness_test["canonical_match"]) - float(stage_b_robustness_test["canonical_match"])
    else:
        valid_delta = test_delta = robust_test_delta = None

    metric_cards = "".join(
        [
            metric_card(
                "Final valid canonical",
                pct(final_valid.get("canonical_match")),
                f"all-view macro · {int(final_valid.get('decoded_sample_count', 0)):,} decoded",
            ),
            metric_card(
                "Final test canonical",
                pct(all_view_test.get("canonical_match")),
                f"all-view macro · {int(all_view_test.get('decoded_sample_count', 0)):,} decoded",
            ),
            metric_card(
                "Robustness test canonical",
                pct(robustness_test.get("canonical_match")),
                f"4 non-identity strategies · {int(robustness_test.get('decoded_sample_count', 0)):,} decoded",
            ),
            metric_card(
                "Text -> graph top1",
                pct(final_valid.get("text_to_graph_top1")),
                f"dedup retrieval · top5 {pct(final_valid.get('text_to_graph_top5'))}",
            ),
            metric_card(
                "Graph -> text top1",
                pct(final_valid.get("graph_to_text_top1")),
                f"dedup retrieval · top5 {pct(final_valid.get('graph_to_text_top5'))}",
            ),
            metric_card(
                "Lowest raw restore loss",
                esc(best_restore_epoch.get("checkpoint_name")),
                f"restore_loss {num(float(best_restore_epoch['restore_loss']), 4)} · monitor best {esc(monitor_best_checkpoint)}",
            ),
        ]
    )

    full_decode_rows = [
        ["Stage C artifact dir", pill(stage_c_artifacts.exists()), f"<code>{esc(stage_c_artifacts)}</code>"],
        ["Completed epochs", pill(final_valid.get("completed_epochs") == training_config.get("max_epochs")), f"{final_valid.get('completed_epochs')} / {training_config.get('max_epochs')}"],
        ["Train rows", pill(final_valid.get("train_sample_count") == 46320), f"{int(final_valid.get('train_sample_count', 0)):,}"],
        ["Final valid full decode", pill(final_valid.get("decoded_sample_count") == final_valid.get("sample_count")), f"{int(final_valid.get('decoded_sample_count', 0)):,}/{int(final_valid.get('sample_count', 0)):,}"],
        ["Final test full decode", pill(all_view_test.get("decoded_sample_count") == all_view_test.get("sample_count")), f"{int(all_view_test.get('decoded_sample_count', 0)):,}/{int(all_view_test.get('sample_count', 0)):,}"],
        ["Robustness valid full decode", pill(robustness_valid.get("decoded_sample_count") == robustness_valid.get("sample_count")), f"{int(robustness_valid.get('decoded_sample_count', 0)):,}/{int(robustness_valid.get('sample_count', 0)):,}"],
        ["Robustness test full decode", pill(robustness_test.get("decoded_sample_count") == robustness_test.get("sample_count")), f"{int(robustness_test.get('decoded_sample_count', 0)):,}/{int(robustness_test.get('sample_count', 0)):,}"],
        ["Formal decode limits", pill(training_config.get("eval_decode_samples") == 0 and training_config.get("checkpoint_eval_decode_samples") == 0), "eval_decode_samples=0, checkpoint_eval_decode_samples=0"],
        ["Retrieval dedup", pill(final_valid.get("formal_eval_dedup_retrieval") is True), f"valid/test retrieval sample count = {int(final_valid.get('retrieval_sample_count', 0)):,}"],
        ["Early stopping", pill(final_valid.get("early_stopping_monitor_only") and not final_valid.get("early_stopped")), "monitor_only=True, early_stopped=False"],
        ["Reload check", pill(reload_check.get("status") == "passed"), f"status={esc(reload_check.get('status'))}, record_id={esc(reload_check.get('record_id'))}"],
    ]

    formal_metric_rows = []
    split_specs = [
        ("Final valid", final_valid),
        ("All-view test", all_view_test),
        ("Robustness valid", robustness_valid),
        ("Robustness test", robustness_test),
    ]
    for label, metrics in split_specs:
        formal_metric_rows.append(
            [
                esc(label),
                f"{int(metrics.get('sample_count', 0)):,}",
                f"{int(metrics.get('decoded_sample_count', 0)):,}",
                f"{int(metrics.get('retrieval_sample_count', 0)):,}",
                num(metrics.get("loss"), 4),
                num(metrics.get("restore_loss"), 4),
                num(metrics.get("weighted_align_loss"), 4),
                pct(metrics.get("token_accuracy")),
                pct(metrics.get("canonical_match")),
                pct(metrics.get("rdkit_validity")),
                pct(metrics.get("two_attachment_validity")),
            ]
        )

    retrieval_rows = []
    for label, metrics, rank_summary in [
        ("Final valid", final_valid, retrieval_summaries["valid"]),
        ("All-view test", all_view_test, retrieval_summaries["test"]),
    ]:
        retrieval_rows.append(
            [
                esc(label),
                f"{int(metrics.get('retrieval_sample_count', 0)):,}",
                count_rate(metrics.get("text_to_graph_top1"), metrics.get("retrieval_sample_count")),
                count_rate(metrics.get("text_to_graph_top5"), metrics.get("retrieval_sample_count")),
                count_rate(metrics.get("graph_to_text_top1"), metrics.get("retrieval_sample_count")),
                count_rate(metrics.get("graph_to_text_top5"), metrics.get("retrieval_sample_count")),
                num(rank_summary.get("mean_top1_margin"), 4),
                num(rank_summary.get("mean_top_score"), 4),
            ]
        )

    strategy_rows = []
    strategies = ["identity", "attachment_rooted_smiles", "light_denoise", "direction_flip", "rdkit_random_smiles"]
    for strategy in strategies:
        valid_values = (final_valid.get("all_view_by_strategy") or {}).get(strategy)
        test_values = (all_view_test.get("all_view_by_strategy") or {}).get(strategy)
        robust_values = (robustness_test.get("robustness_by_strategy") or {}).get(strategy)
        strategy_rows.append(
            [
                f"<b>{esc(STRATEGY_LABELS.get(strategy, strategy))}</b>",
                esc(STRATEGY_DESCRIPTIONS.get(strategy, "")),
                count_rate(valid_values.get("canonical_match"), valid_values.get("sample_count")) if valid_values else "-",
                count_rate(test_values.get("canonical_match"), test_values.get("sample_count")) if test_values else "-",
                count_rate(robust_values.get("canonical_match"), robust_values.get("sample_count")) if robust_values else "<span class=\"muted\">not in robustness</span>",
                pct(valid_values.get("rdkit_validity")) if valid_values else "-",
                str(valid_values.get("failed_count")) if valid_values else "-",
            ]
        )

    stage_b_rows: list[list[Any]] = []
    if stage_b_compare_available:
        compare_specs = [
            ("Final valid canonical", stage_b_valid, final_valid, "canonical_match"),
            ("Final test canonical", stage_b_test, all_view_test, "canonical_match"),
            ("Robustness valid canonical", stage_b_robustness_valid, robustness_valid, "canonical_match"),
            ("Robustness test canonical", stage_b_robustness_test, robustness_test, "canonical_match"),
            ("Final valid RDKit", stage_b_valid, final_valid, "rdkit_validity"),
            ("Final test RDKit", stage_b_test, all_view_test, "rdkit_validity"),
        ]
        for label, stage_b, stage_c, key in compare_specs:
            delta = float(stage_c[key]) - float(stage_b[key])
            stage_b_rows.append([esc(label), pct(stage_b[key]), pct(stage_c[key]), f"<b>{pp(delta)}</b>"])

    failure_table_rows = []
    split_labels = {
        "failed_cases.jsonl": "Final valid",
        "all_view_test_failed_cases.jsonl": "All-view test",
        "robustness_valid_failed_cases.jsonl": "Robustness valid",
        "robustness_test_failed_cases.jsonl": "Robustness test",
    }
    for file_name, summary in failure_summaries.items():
        total_failed = summary["failed_count"]
        categories = summary["category_counts"]
        failure_table_rows.append(
            [
                esc(split_labels[file_name]),
                f"{total_failed:,}",
                f"{categories.get('invalid_smiles', 0):,} <span class=\"muted\">({pct(categories.get('invalid_smiles', 0) / total_failed if total_failed else 0)})</span>",
                f"{categories.get('valid_two_attachment_wrong_canonical', 0):,} <span class=\"muted\">({pct(categories.get('valid_two_attachment_wrong_canonical', 0) / total_failed if total_failed else 0)})</span>",
                f"{categories.get('attachment_count_not_two', 0):,} <span class=\"muted\">({pct(categories.get('attachment_count_not_two', 0) / total_failed if total_failed else 0)})</span>",
            ]
        )

    config_rows = [
        ["Output dir", f"<code>{esc(training_config.get('output_dir'))}</code>"],
        ["Data", f"<code>{esc(training_config.get('preview_path'))}</code>"],
        ["Graph path", f"<code>{esc(training_config.get('graph_path'))}</code>"],
        ["Objective", f"L_restore x {training_config.get('restore_loss_weight')} + L_align x {training_config.get('align_loss_weight')}"],
        ["Precision / seed", f"{esc(training_config.get('precision'))} / {esc(training_config.get('seed'))}"],
        ["Effective batch", f"per_device_train_batch_size={training_config.get('per_device_train_batch_size')}, gradient_accumulation_steps={training_config.get('gradient_accumulation_steps')}"],
        ["Learning rates", f"LoRA={training_config.get('learning_rate_lora')}, restore={training_config.get('learning_rate_restore_head')}, graph={training_config.get('learning_rate_graph_encoder')}, projectors={training_config.get('learning_rate_projectors')}"],
        ["LoRA", f"rank={training_config.get('lora_rank')}, alpha={training_config.get('lora_alpha')}, dropout={training_config.get('lora_dropout')}, targets={', '.join(training_config.get('lora_target_modules', []))}"],
        ["Graph encoder", f"hidden={training_config.get('graph_hidden_size')}, layers={training_config.get('graph_num_layers')}, dropout={training_config.get('graph_dropout')}"],
    ]

    chart = lambda key, alt: f"<img src=\"{esc(Path(chart_paths[key]).relative_to(report_path.parent))}\" alt=\"{esc(alt)}\">"

    executive_stage_b_line = (
        f"相对本地 Stage B full restore-only 基线，Stage C full 在 valid canonical 上高 {pp(valid_delta)}，test canonical 高 {pp(test_delta)}，robustness test canonical 高 {pp(robust_test_delta)}。"
        if stage_b_compare_available
        else "本地缺少完整 Stage B full artifact，因此报告未做 Stage B 横比。"
    )

    html_text = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Stage C Full Detailed Report</title>
<style>
:root {{ --bg:#f5f7fb; --panel:#fff; --ink:#172033; --muted:#647084; --line:#dbe3ee; --soft:#eef3f8; --navy:#101827; --blue:#2563eb; --green:#047857; --orange:#cc6f47; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.55 -apple-system,BlinkMacSystemFont,\"Segoe UI\",Arial,\"Noto Sans SC\",sans-serif; }}
header {{ background:var(--navy); color:#fff; padding:34px 40px 30px; }}
header h1 {{ margin:0 0 8px; font-size:28px; letter-spacing:0; }}
header p {{ margin:0; color:#cbd5e1; max-width:1100px; }}
main {{ max-width:1260px; margin:0 auto; padding:28px 24px 54px; }}
section {{ margin:0 0 24px; }}
h2 {{ font-size:19px; margin:0 0 13px; letter-spacing:0; }}
h3 {{ font-size:15px; margin:0 0 11px; letter-spacing:0; }}
.card,.chart-card,.metric {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; box-shadow:0 1px 2px rgba(15,23,42,.035); }}
.card {{ padding:18px; }}
.grid {{ display:grid; gap:14px; }}
.grid.metrics {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
.grid.two {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
.metric {{ padding:14px 16px; min-height:96px; }}
.metric-label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em; }}
.metric-value {{ font-size:27px; font-weight:740; margin:4px 0 2px; letter-spacing:0; }}
.metric-note {{ color:var(--muted); font-size:12px; }}
.callout {{ border-left:4px solid var(--blue); background:#eff6ff; border-radius:0 8px 8px 0; padding:12px 14px; margin:10px 0 0; }}
.note {{ color:var(--muted); font-size:12px; margin-top:8px; }}
.table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:#fff; }}
table {{ width:100%; border-collapse:collapse; min-width:780px; }}
th,td {{ padding:9px 11px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }}
th {{ background:#f8fafc; color:#475569; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
tr:last-child td {{ border-bottom:0; }}
code {{ background:#eef2f7; border:1px solid #d9e2ec; padding:1px 5px; border-radius:5px; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12px; }}
.muted {{ color:var(--muted); }}
.pill {{ display:inline-block; padding:2px 8px; border-radius:999px; font-weight:680; font-size:12px; }}
.pill.ok {{ background:#d9f5ef; color:#075e54; }}
.pill.warn {{ background:#fff2cc; color:#92400e; }}
.chart-card {{ padding:14px; }}
.chart-title {{ display:flex; justify-content:space-between; gap:12px; align-items:baseline; font-weight:730; margin:0 0 8px; }}
.chart-title em {{ color:var(--muted); font-style:normal; font-weight:500; }}
.chart-card p {{ margin:0 0 10px; color:#334155; }}
.chart-card img {{ display:block; width:100%; height:auto; border:1px solid var(--line); border-radius:8px; background:#fff; }}
.delta-pos {{ color:var(--green); font-weight:730; }}
footer {{ color:var(--muted); font-size:12px; margin-top:30px; }}
@media (max-width:900px) {{
  header {{ padding:26px 20px; }} main {{ padding:20px 14px 40px; }}
  .grid.metrics,.grid.two {{ grid-template-columns:1fr; }}
  table {{ min-width:720px; }}
}}
</style>
</head>
<body>
<header>
  <h1>Stage C Full Detailed Report</h1>
  <p>Stage C non-vocab aug v2 full：30 epoch 静态全量 all-view 训练，目标为 <code>L_restore + 0.2 * L_align</code>，正式评估使用全量 decode 与 dedup retrieval。</p>
</header>
<main>
  <section class=\"card\">
    <h2>Executive Summary</h2>
    <ul>
      <li><b>Stage C full 已完整跑完 30 epoch，正式 decode 口径通过。</b> Final valid canonical 为 {pct(final_valid.get('canonical_match'))}，all-view test canonical 为 {pct(all_view_test.get('canonical_match'))}，robustness test canonical 为 {pct(robustness_test.get('canonical_match'))}。</li>
      <li><b>图文对齐分支在 top-5 上几乎饱和，top-1 也稳定在 81% 以上。</b> Final valid text->graph top1/top5 为 {pct(final_valid.get('text_to_graph_top1'))}/{pct(final_valid.get('text_to_graph_top5'))}，graph->text top1/top5 为 {pct(final_valid.get('graph_to_text_top1'))}/{pct(final_valid.get('graph_to_text_top5'))}。</li>
      <li><b>继续训练到 epoch 30 对 restore 指标是有价值的。</b> early-stopping 记录的 monitor best 是 {esc(monitor_best_checkpoint)}；逐 epoch 原始 restore_loss 最低是 {esc(best_restore_epoch.get('checkpoint_name'))}，canonical best 出现在 {esc(best_canonical_epoch.get('checkpoint_name'))}。</li>
      <li><b>{executive_stage_b_line}</b> 这部分只比较 restore 相关指标；Stage C joint loss 和 Stage B restore-only loss 不直接横比。</li>
      <li><b>主要弱项仍是非 identity view 的语法失败和 valid-but-wrong canonical。</b> Final valid failed cases 中 invalid SMILES 占 {pct(invalid_rate)}，valid two-attachment 但 canonical 错误占 {pct(valid_wrong_rate)}。</li>
    </ul>
  </section>

  <section class=\"grid metrics\">{metric_cards}</section>

  <section class=\"card\">
    <h2>Full-Decode Standard Check</h2>
    {table(["Check", "Status", "Detail"], full_decode_rows)}
    <p class=\"note\">配置文件名仍保留 <code>20epoch</code> 字样，但本次 artifact 的 <code>training_config.json</code> 与 YAML 内容均为 <code>max_epochs=30</code>，输出目录为 <code>stage_c_non_vocab_aug_v2_full_30epoch</code>。</p>
  </section>

  <section class=\"card\">
    <h2>Formal Metrics</h2>
    <p>Stage C 的 total loss 是联合目标，拆成 restore loss 与 weighted align loss 后更容易判断。Robustness split 的 retrieval count 为 0 是设计选择：这些样本是重复 graph view，不用于 retrieval 排名评估。</p>
    {table(["Split", "Samples", "Decoded", "Retrieval", "Loss", "Restore loss", "0.2 x Align", "Token acc.", "Canonical", "RDKit valid", "Two attach."], formal_metric_rows)}
  </section>

  <section class=\"grid two\">
    <div class=\"chart-card\">
      <div class=\"chart-title\"><span>Epoch restore metrics</span><em>valid full decode</em></div>
      <p>Canonical、exact、RDKit validity 和 two-attachment validity 在前 10 个 epoch 快速提升，后续虽有小波动，但 final epoch 保持在最高或接近最高区域。</p>
      {chart('epoch_restore_metric_trends', 'Epoch restore metric trends')}
    </div>
    <div class=\"chart-card\">
      <div class=\"chart-title\"><span>Loss components</span><em>restore + align</em></div>
      <p>restore_loss 在 epoch 9 附近达到早停监控最优，之后 total loss 小幅波动；weighted align loss 基本稳定，说明后半段的 restore 指标提升不是靠 align 项大幅漂移换来的。</p>
      {chart('loss_components_over_epochs', 'Loss components over epochs')}
    </div>
  </section>

  <section class=\"card\">
    <h2>Retrieval Alignment Is Strong And Stable</h2>
    <p>Formal retrieval 对 record_id 去重后评估 1,158 个 graph identity，避免五个 text view 互相干扰 top-k。Valid/test 的 top-5 均接近 100%，top-1 主要落在 81%-83% 区间。</p>
    {table(["Split", "Retrieval n", "Text->graph top1", "Text->graph top5", "Graph->text top1", "Graph->text top5", "Mean top1 margin", "Mean top score"], retrieval_rows)}
    <div class=\"chart-card\" style=\"margin-top:14px\">
      <div class=\"chart-title\"><span>Retrieval trends</span><em>deduplicated graph records</em></div>
      <p>Top-5 很早进入高位，Top-1 在 epoch 20 后继续改善，final valid text->graph top1 为 {pct(final_valid.get('text_to_graph_top1'))}，graph->text top1 为 {pct(final_valid.get('graph_to_text_top1'))}。</p>
      {chart('retrieval_quality_over_epochs', 'Retrieval quality over epochs')}
    </div>
  </section>

  <section class=\"card\">
    <h2>Identity Is Strong; Random And Flip Views Remain The Bottleneck</h2>
    <p>Final valid/test 的 identity canonical 已到 74%-76%，attachment-rooted 位于 62% 左右；rdkit-random 与 direction-flip 仍在 45%-47% 区间，是后续 robustness 提升最直接的工作面。</p>
    {table(["Strategy", "Meaning", "Final valid canonical", "All-view test canonical", "Robustness test canonical", "Final valid RDKit", "Final valid failed"], strategy_rows)}
    <div class=\"chart-card\" style=\"margin-top:14px\">
      <div class=\"chart-title\"><span>Strategy comparison</span><em>canonical match</em></div>
      <p>Robustness test 排除了 identity，因此图里可以直接看到非 identity 的排序：attachment-rooted 明显领先，random/flip 是最低两项。</p>
      {chart('canonical_match_by_strategy', 'Canonical match by augmentation strategy')}
    </div>
  </section>
"""

    if stage_b_compare_available:
        html_text += f"""
  <section class=\"card\">
    <h2>Stage B Restore-Only Reference</h2>
    <p>这个对比只使用同口径 restore 指标，帮助判断 Stage C graph+align 分支是否伤害 restore 能力。需要注意：Stage B full 是 20 epoch，Stage C full 是 30 epoch，因此这不是严格 epoch-budget ablation。</p>
    {table(["Metric", "Stage B full", "Stage C full", "Delta"], stage_b_rows)}
    <div class=\"chart-card\" style=\"margin-top:14px\">
      <div class=\"chart-title\"><span>Stage B vs Stage C</span><em>restore metrics only</em></div>
      <p>Stage C full 在 valid/test/robustness 的 canonical restore 指标上都高于本地 Stage B full；joint loss、align loss 和 retrieval 指标不放进这张横比图。</p>
      {chart('stage_b_vs_stage_c_restore_metrics', 'Stage B vs Stage C restore metrics')}
    </div>
  </section>
"""

    html_text += f"""
  <section class=\"card\">
    <h2>Failure Mix Shows Two Different Problems</h2>
    <p>失败样例不是单一问题：一部分是 RDKit parse failed，另一部分已经是合法、双连接点 SMILES，但 canonical 仍不匹配。前者更像语法/闭环/价态问题，后者更像结构等价与恢复目标混淆问题。</p>
    {table(["Split", "Failed cases", "Invalid SMILES", "Valid but wrong canonical", "Attachment count != 2"], failure_table_rows)}
    <div class=\"chart-card\" style=\"margin-top:14px\">
      <div class=\"chart-title\"><span>Failure taxonomy</span><em>canonical non-matches</em></div>
      <p>Attachment-count 错误很少；主要成本在 invalid SMILES 和 valid-but-wrong canonical 两类之间分摊。</p>
      {chart('failure_mix_by_split', 'Failure mix by evaluation split')}
    </div>
  </section>

  <section class=\"card\">
    <h2>Recommended Next Steps</h2>
    <ol>
      <li><b>先把 epoch 30 作为 Stage C full 默认 checkpoint。</b> 它不是 restore_loss 最低点，但 final canonical、RDKit validity、retrieval top-k 和 full-decode 覆盖最完整；若只追求 restore_loss，再单独补评 early-stopping monitor best {esc(monitor_best_checkpoint)} 与 raw restore-loss best {esc(best_restore_epoch.get('checkpoint_name'))} 的 test/robustness/retrieval。</li>
      <li><b>用同一套脚本生成 Stage C curriculum 报告并做 full-vs-curriculum 横比。</b> 重点看 curriculum 是否能继续抬高 random/flip 两类非 identity view，同时不牺牲 retrieval top-1。</li>
      <li><b>对 rdkit-random 与 direction-flip 的 invalid SMILES 做错误切片。</b> 优先按环闭合、Si/连接点、芳香性和长序列 bucket 切分，分别处理语法失败和 valid-wrong canonical。</li>
      <li><b>保留 dedup retrieval 口径。</b> Formal retrieval 已去重；robustness split 因重复 graph view 跳过 retrieval，不应把其中的 0.0 top-k 当作模型退化。</li>
    </ol>
  </section>

  <section class=\"card\">
    <h2>Further Questions</h2>
    <ul>
      <li>Stage C curriculum 是否能把 random/flip canonical 从 45%-47% 区间推到 50% 以上，并维持 top-5 retrieval 接近饱和？</li>
      <li>valid-but-wrong canonical 是否集中在少数结构家族，还是广泛分布在所有 polymer repeat unit 类型中？</li>
      <li>epoch 29/30 的 final 差异是否来自真实泛化提升，还是少数 strategy 和 failure bucket 的波动？</li>
    </ul>
  </section>

  <section class=\"card\">
    <h2>Caveats And Assumptions</h2>
    <ul>
      <li>本报告读取远端训练产物并在本地生成；未重新训练模型。</li>
      <li>Stage B 横比使用本地已有 <code>{esc(stage_b_artifacts)}</code>，只比较 restore 指标；Stage C 的 <code>loss</code> 包含 align 项，不能直接和 Stage B restore-only loss 横比。</li>
      <li>Stage B full 为 20 epoch，Stage C full 为 30 epoch；结论可说明 Stage C full 当前产物更强，但不能单独归因到 graph/align 架构。</li>
      <li>正式 retrieval 只在 deduplicated graph records 上解释；robustness retrieval 被跳过是评估设计，不是模型质量指标。</li>
    </ul>
  </section>

  <section class=\"card\">
    <h2>Configuration Summary</h2>
    {table(["Item", "Value"], config_rows)}
  </section>

  <footer>
    Generated locally at {esc(generated_at)} from <code>{esc(stage_c_artifacts)}</code>. Source notes: <code>{esc(stage_c_artifacts / 'stage_c_full_report_source_notes.json')}</code>.
  </footer>
</main>
</body>
</html>
"""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html_text, encoding="utf-8")

    source_notes = {
        "report": str(report_path),
        "generated_at": generated_at,
        "stage_c_artifacts": str(stage_c_artifacts),
        "stage_b_artifacts": str(stage_b_artifacts) if stage_b_compare_available else None,
        "chart_map": [
            {
                "section": "Epoch restore metrics",
                "question": "How did formal restore metrics move over checkpoints?",
                "family": "Trend",
                "chart_type": "multi-series line",
                "fields": ["checkpoint_epoch", "canonical_match", "exact_string_match", "rdkit_validity", "two_attachment_validity"],
                "artifact": chart_paths.get("epoch_restore_metric_trends"),
            },
            {
                "section": "Loss components",
                "question": "How did restore and weighted align loss contribute to total objective?",
                "family": "Trend",
                "chart_type": "multi-series line",
                "fields": ["checkpoint_epoch", "loss", "restore_loss", "weighted_align_loss"],
                "artifact": chart_paths.get("loss_components_over_epochs"),
            },
            {
                "section": "Retrieval alignment",
                "question": "How stable were text->graph and graph->text retrieval metrics?",
                "family": "Trend",
                "chart_type": "small-multiple line",
                "fields": ["checkpoint_epoch", "text_to_graph_top1", "text_to_graph_top5", "graph_to_text_top1", "graph_to_text_top5"],
                "artifact": chart_paths.get("retrieval_quality_over_epochs"),
            },
            {
                "section": "Strategy comparison",
                "question": "Which augmentation strategies are bottlenecks?",
                "family": "Comparison & Ranking",
                "chart_type": "grouped horizontal bar",
                "fields": ["strategy", "split", "canonical_match"],
                "artifact": chart_paths.get("canonical_match_by_strategy"),
            },
            {
                "section": "Failure taxonomy",
                "question": "What type of canonical non-match dominates failures?",
                "family": "Composition",
                "chart_type": "stacked horizontal bar",
                "fields": ["split", "failure_category", "count"],
                "artifact": chart_paths.get("failure_mix_by_split"),
            },
            {
                "section": "Stage B restore-only reference",
                "question": "How does Stage C full compare to local Stage B full on restore metrics only?",
                "family": "Comparison & Ranking",
                "chart_type": "grouped horizontal bar",
                "fields": ["metric", "stage", "rate"],
                "artifact": chart_paths.get("stage_b_vs_stage_c_restore_metrics"),
            },
        ],
        "source_files": sorted(path.name for path in stage_c_artifacts.iterdir() if path.is_file()),
        "failure_summaries": failure_summaries,
        "retrieval_summaries": retrieval_summaries,
        "caveats": [
            "Stage C loss is not directly comparable to Stage B restore-only loss.",
            "Stage B full has 20 epochs while Stage C full has 30 epochs.",
            "Robustness retrieval metrics are skipped by design for duplicate graph views.",
            "The YAML artifact file name contains 20epoch, but its content and training_config specify max_epochs=30.",
        ],
        "executive_structure_map": {
            "Title": "Stage C Full Detailed Report",
            "Executive summary": "Executive Summary",
            "Key findings with visual evidence": [
                "Epoch restore metrics",
                "Retrieval Alignment Is Strong And Stable",
                "Identity Is Strong; Random And Flip Views Remain The Bottleneck",
                "Stage B Restore-Only Reference",
                "Failure Mix Shows Two Different Problems",
            ],
            "Recommended next steps": "Recommended Next Steps",
            "Further questions": "Further Questions",
            "Caveats and assumptions": "Caveats And Assumptions",
        },
    }
    (stage_c_artifacts / "stage_c_full_report_source_notes.json").write_text(
        json.dumps(source_notes, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the local Stage C full detailed HTML report.")
    parser.add_argument("--stage-c-artifacts", type=Path, default=DEFAULT_STAGE_C_ARTIFACTS)
    parser.add_argument("--stage-b-artifacts", type=Path, default=DEFAULT_STAGE_B_ARTIFACTS)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--chart-dir", type=Path, default=DEFAULT_CHART_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_report(args.stage_c_artifacts, args.stage_b_artifacts, args.report_path, args.chart_dir)
    print(json.dumps({"report": str(args.report_path), "chart_dir": str(args.chart_dir)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
