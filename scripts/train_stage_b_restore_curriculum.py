from __future__ import annotations

import argparse
import gc
import json
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import DataLoader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.train_stage_b_restore_full import (
    DEFAULT_CONFIG_PATH,
    RestoreCrossAttentionHead,
    StageAPreviewDataset,
    StageBConfig,
    append_epoch_metrics,
    append_quick_eval_metrics,
    build_optimizer,
    collate_restore_records,
    copy_config_snapshot,
    early_stopping_is_improvement,
    evaluate_restore,
    forward_encoder_hidden,
    load_yaml_config,
    masked_cross_entropy,
    reset_training_metric_files,
    run_reload_smoke,
    save_run_artifacts,
    shift_restore_labels_right,
    validate_preview_tokenizer_compatibility,
    validate_training_config,
    write_extra_eval_outputs,
    write_jsonl,
)


DEFAULT_CURRICULUM_OUTPUT_DIR = ROOT / "outputs" / "stage_b_restore_aug_curriculum_full_20epoch"
CURRICULUM_STRATEGIES = (
    "identity",
    "rdkit_random_smiles",
    "attachment_rooted_smiles",
    "light_denoise",
)
ROBUSTNESS_STRATEGIES = ("rdkit_random_smiles", "light_denoise")
TRAIN_CONFLICT_FILTER_POLICY = "prefer_self_label_else_drop_all"
TRAIN_CONFLICT_AUDIT_JSONL = "train_input_label_conflicts.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Stage B restore with curriculum augmentation and full eval.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--model-name-or-path", required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--preview-path", type=Path, default=None)
    parser.add_argument("--eval-preview-path", type=Path, default=None)
    parser.add_argument("--eval-output-prefix", default="robustness")
    return parser.parse_args()


def curriculum_weights_for_epoch(epoch_index: int) -> dict[str, float]:
    if epoch_index < 1:
        raise ValueError("epoch_index must be >= 1")
    if epoch_index <= 2:
        return {
            "identity": 1.0,
            "rdkit_random_smiles": 0.0,
            "attachment_rooted_smiles": 0.0,
            "light_denoise": 0.0,
        }
    if epoch_index <= 4:
        return {
            "identity": 0.80,
            "rdkit_random_smiles": 0.20,
            "attachment_rooted_smiles": 0.0,
            "light_denoise": 0.0,
        }
    if epoch_index <= 6:
        return {
            "identity": 0.60,
            "rdkit_random_smiles": 0.25,
            "attachment_rooted_smiles": 0.15,
            "light_denoise": 0.0,
        }
    if epoch_index <= 9:
        return {
            "identity": 0.40,
            "rdkit_random_smiles": 0.25,
            "attachment_rooted_smiles": 0.25,
            "light_denoise": 0.10,
        }
    if epoch_index <= 12:
        return {
            "identity": 0.30,
            "rdkit_random_smiles": 0.25,
            "attachment_rooted_smiles": 0.25,
            "light_denoise": 0.20,
        }
    return {
        "identity": 0.20,
        "rdkit_random_smiles": 0.20,
        "attachment_rooted_smiles": 0.25,
        "light_denoise": 0.35,
    }


def strategy_for_row(row: dict[str, Any]) -> str:
    return str(row.get("augmentation_strategy") or row.get("text_view_1_strategy") or "identity")


def label_for_row(row: dict[str, Any]) -> str:
    label = str(row.get("canonical_text_target") or row.get("canonical_smiles") or row.get("target_text") or "")
    for eos_token in ("<|endoftext|>", "<eos>"):
        if label.endswith(eos_token):
            return label[: -len(eos_token)]
    return label


def input_view_for_row(row: dict[str, Any]) -> str:
    return str(row.get("input_text_view1") or "")


def text_view_for_row(row: dict[str, Any]) -> str:
    if "text_view_1" in row:
        return str(row["text_view_1"])
    input_text = input_view_for_row(row)
    prefix = "<polymer_view_smiles>\n"
    suffix = "\n</polymer_view_smiles>\n"
    if input_text.startswith(prefix) and input_text.endswith(suffix):
        return input_text[len(prefix) : -len(suffix)]
    return input_text


def row_audit_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": row.get("record_id"),
        "view_id": row.get("view_id"),
        "split": row.get("split"),
        "augmentation_strategy": strategy_for_row(row),
        "text_view_1_strategy": row.get("text_view_1_strategy"),
        "text_view_1": text_view_for_row(row),
        "canonical_text_target": label_for_row(row),
        "canonical_smiles": row.get("canonical_smiles"),
    }


def count_input_label_conflicts(rows: list[dict[str, Any]]) -> int:
    labels_by_input: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        labels_by_input[input_view_for_row(row)].add(label_for_row(row))
    return sum(1 for labels in labels_by_input.values() if len(labels) > 1)


def filter_train_input_label_conflicts(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[input_view_for_row(row)].append(index)

    removed_indices: set[int] = set()
    audit_rows: list[dict[str, Any]] = []
    rows_in_conflict = 0
    kept_rows_in_conflict = 0
    removed_rows_in_conflict = 0

    for input_view, indices in grouped.items():
        labels = {label_for_row(rows[index]) for index in indices}
        if len(labels) <= 1:
            continue

        rows_in_conflict += len(indices)
        self_labels = {
            label_for_row(rows[index])
            for index in indices
            if text_view_for_row(rows[index]) == label_for_row(rows[index])
        }
        if self_labels:
            kept_indices = [index for index in indices if label_for_row(rows[index]) in self_labels]
            removed_for_group = [index for index in indices if label_for_row(rows[index]) not in self_labels]
        else:
            kept_indices = []
            removed_for_group = list(indices)

        removed_indices.update(removed_for_group)
        kept_rows_in_conflict += len(kept_indices)
        removed_rows_in_conflict += len(removed_for_group)
        audit_rows.append(
            {
                "input_text_view1": input_view,
                "label_count": len(labels),
                "row_count": len(indices),
                "kept_row_count": len(kept_indices),
                "removed_row_count": len(removed_for_group),
                "labels": sorted(labels),
                "kept_rows": [row_audit_summary(rows[index]) for index in kept_indices],
                "removed_rows": [row_audit_summary(rows[index]) for index in removed_for_group],
            }
        )

    clean_rows = [row for index, row in enumerate(rows) if index not in removed_indices]
    removed_rows = [row for index, row in enumerate(rows) if index in removed_indices]
    stats = {
        "train_conflict_filter_enabled": True,
        "train_conflict_filter_policy": TRAIN_CONFLICT_FILTER_POLICY,
        "train_conflict_filter_original_row_count": len(rows),
        "train_conflict_filter_clean_row_count": len(clean_rows),
        "train_conflict_filter_removed_row_count": len(removed_rows),
        "train_conflict_filter_removed_by_strategy": dict(
            sorted(Counter(strategy_for_row(row) for row in removed_rows).items())
        ),
        "train_conflict_filter_conflicting_input_view_count": len(audit_rows),
        "train_conflict_filter_rows_in_conflict_count": rows_in_conflict,
        "train_conflict_filter_kept_rows_in_conflict_count": kept_rows_in_conflict,
        "train_conflict_filter_removed_rows_in_conflict_count": removed_rows_in_conflict,
        "train_conflict_filter_remaining_conflicting_input_view_count": count_input_label_conflicts(clean_rows),
        "train_conflict_filter_clean_strategy_counts": dict(
            sorted(Counter(strategy_for_row(row) for row in clean_rows).items())
        ),
    }
    return clean_rows, stats, audit_rows


def group_rows_by_strategy(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[strategy_for_row(row)].append(row)
    return dict(grouped)


def allocate_strategy_counts(total_rows: int, weights: dict[str, float]) -> dict[str, int]:
    if total_rows < 0:
        raise ValueError("total_rows must be >= 0")
    if any(value < 0 for value in weights.values()):
        raise ValueError("curriculum weights must be non-negative")
    weight_sum = sum(weights.values())
    if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"curriculum weights must sum to 1.0; got {weight_sum}")

    raw_counts = {strategy: total_rows * weights.get(strategy, 0.0) for strategy in CURRICULUM_STRATEGIES}
    counts = {strategy: int(math.floor(raw_counts[strategy])) for strategy in CURRICULUM_STRATEGIES}
    remainder = total_rows - sum(counts.values())
    ranked = sorted(
        CURRICULUM_STRATEGIES,
        key=lambda strategy: (raw_counts[strategy] - counts[strategy], -CURRICULUM_STRATEGIES.index(strategy)),
        reverse=True,
    )
    for strategy in ranked[:remainder]:
        counts[strategy] += 1
    return counts


def deterministic_oversample(
    rows: list[dict[str, Any]],
    count: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    if count < 0:
        raise ValueError("count must be >= 0")
    if count == 0:
        return []
    if not rows:
        raise ValueError("cannot sample from an empty strategy bucket")

    sampled: list[dict[str, Any]] = []
    full_repeats, remainder = divmod(count, len(rows))
    for _ in range(full_repeats):
        cycle_rows = list(rows)
        rng.shuffle(cycle_rows)
        sampled.extend(cycle_rows)
    if remainder:
        remainder_rows = list(rows)
        rng.shuffle(remainder_rows)
        sampled.extend(remainder_rows[:remainder])
    return sampled


def build_curriculum_epoch_rows(
    rows: list[dict[str, Any]],
    *,
    epoch_index: int,
    seed: int,
    epoch_target_row_count: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target_row_count = len(rows) if epoch_target_row_count is None else epoch_target_row_count
    if target_row_count < 0:
        raise ValueError("epoch_target_row_count must be >= 0")
    grouped = group_rows_by_strategy(rows)
    present_strategies = set(grouped)
    if present_strategies == {"identity"}:
        rng = random.Random(seed + epoch_index * 100003)
        epoch_rows = deterministic_oversample(grouped["identity"], target_row_count, rng)
        rng.shuffle(epoch_rows)
        counts = Counter(strategy_for_row(row) for row in epoch_rows)
        return epoch_rows, {
            "curriculum_enabled": False,
            "curriculum_epoch": epoch_index,
            "curriculum_strategy_weights": {"identity": 1.0},
            "curriculum_strategy_counts": dict(sorted(counts.items())),
            "curriculum_epoch_row_count": len(epoch_rows),
            "curriculum_epoch_target_row_count": target_row_count,
        }

    missing = set(CURRICULUM_STRATEGIES) - present_strategies
    if missing:
        raise ValueError(f"curriculum training requires strategy buckets {CURRICULUM_STRATEGIES}; missing {sorted(missing)}")

    weights = curriculum_weights_for_epoch(epoch_index)
    target_counts = allocate_strategy_counts(target_row_count, weights)
    rng = random.Random(seed + epoch_index * 100003)
    epoch_rows: list[dict[str, Any]] = []
    for strategy in CURRICULUM_STRATEGIES:
        epoch_rows.extend(deterministic_oversample(grouped[strategy], target_counts[strategy], rng))
    rng.shuffle(epoch_rows)
    counts = Counter(strategy_for_row(row) for row in epoch_rows)
    if len(epoch_rows) != target_row_count:
        raise AssertionError(f"curriculum epoch row count drifted: {len(epoch_rows)} != {target_row_count}")
    return epoch_rows, {
        "curriculum_enabled": True,
        "curriculum_epoch": epoch_index,
        "curriculum_strategy_weights": weights,
        "curriculum_strategy_counts": {strategy: counts.get(strategy, 0) for strategy in CURRICULUM_STRATEGIES},
        "curriculum_epoch_row_count": len(epoch_rows),
        "curriculum_epoch_target_row_count": target_row_count,
    }


def full_decode_sample_limit(dataset: Any) -> int:
    return len(dataset)


def rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def aggregate_boolean_metric(rows: list[dict[str, Any]], key: str) -> float:
    return rate(sum(1 for row in rows if bool(row.get(key))), len(rows))


def add_robustness_aggregates(metrics: dict[str, Any], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    by_strategy_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        by_strategy_rows[str(row.get("augmentation_strategy", "unknown"))].append(row)

    by_strategy: dict[str, dict[str, Any]] = {}
    for strategy in sorted(by_strategy_rows):
        rows = by_strategy_rows[strategy]
        by_strategy[strategy] = {
            "sample_count": len(rows),
            "failed_count": sum(1 for row in rows if not bool(row.get("canonical_match"))),
            "exact_string_match": aggregate_boolean_metric(rows, "exact_string_match"),
            "rdkit_validity": aggregate_boolean_metric(rows, "rdkit_valid"),
            "two_attachment_validity": aggregate_boolean_metric(rows, "two_attachment_valid"),
            "canonical_match": aggregate_boolean_metric(rows, "canonical_match"),
        }

    macro_strategies = [strategy for strategy in ROBUSTNESS_STRATEGIES if by_strategy.get(strategy, {}).get("sample_count", 0) > 0]
    if not macro_strategies:
        macro_strategies = [strategy for strategy, values in by_strategy.items() if values.get("sample_count", 0) > 0]
    macro_metrics = {
        metric_name: rate(
            sum(by_strategy[strategy][metric_name] for strategy in macro_strategies),
            len(macro_strategies),
        )
        for metric_name in ("exact_string_match", "rdkit_validity", "two_attachment_validity", "canonical_match")
    }
    macro_metrics["strategy_count"] = len(macro_strategies)
    macro_metrics["strategies"] = macro_strategies

    record_strategy_success: dict[str, dict[str, bool]] = defaultdict(dict)
    for row in predictions:
        record_strategy_success[str(row.get("record_id"))][str(row.get("augmentation_strategy", "unknown"))] = bool(
            row.get("canonical_match")
        )
    all_view_strategies = macro_strategies
    record_count = len(record_strategy_success)
    all_success_count = sum(
        1
        for successes in record_strategy_success.values()
        if all(successes.get(strategy, False) for strategy in all_view_strategies)
    )
    any_success_count = sum(
        1
        for successes in record_strategy_success.values()
        if any(successes.get(strategy, False) for strategy in all_view_strategies)
    )
    partial_success_count = sum(
        1
        for successes in record_strategy_success.values()
        if any(successes.get(strategy, False) for strategy in all_view_strategies)
        and not all(successes.get(strategy, False) for strategy in all_view_strategies)
    )

    return {
        **metrics,
        "robustness_by_strategy": by_strategy,
        "robustness_strategy_macro_avg": macro_metrics,
        "robustness_record_all_views_success": {
            "record_count": record_count,
            "success_count": all_success_count,
            "rate": rate(all_success_count, record_count),
            "strategies": all_view_strategies,
        },
        "robustness_record_any_view_success": {
            "record_count": record_count,
            "success_count": any_success_count,
            "rate": rate(any_success_count, record_count),
            "strategies": all_view_strategies,
        },
        "robustness_record_partial_success": {
            "record_count": record_count,
            "success_count": partial_success_count,
            "rate": rate(partial_success_count, record_count),
            "strategies": all_view_strategies,
        },
    }


def write_curriculum_extra_eval_report(
    path: Path,
    *,
    metrics: dict[str, Any],
    config: StageBConfig,
    eval_preview_path: Path,
    split: str,
) -> None:
    lines = [
        "# Stage B Restore Curriculum Extra Eval Report",
        "",
        "This report is an eval-only pass against an alternate preview file.",
        "",
        f"- split: `{split}`",
        f"- train preview path: `{config.preview_path}`",
        f"- eval preview path: `{eval_preview_path}`",
        f"- decoded sample count: `{metrics.get('decoded_sample_count')}`",
        f"- sample count: `{metrics.get('sample_count')}`",
        "",
        "## Row-Level Overall",
        "",
        "| metric | value |",
        "|---|---:|",
    ]
    for key in ("canonical_match", "rdkit_validity", "two_attachment_validity", "exact_string_match", "loss", "token_accuracy"):
        if key in metrics:
            lines.append(f"| `{key}` | `{metrics[key]}` |")

    if "robustness_by_strategy" in metrics:
        lines.extend(
            [
                "",
                "## Strategy-Level Robustness",
                "",
                "| strategy | sample_count | canonical_match | rdkit_validity | two_attachment_validity | exact_string_match | failed_count |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for strategy, values in metrics["robustness_by_strategy"].items():
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{strategy}`",
                        f"`{values.get('sample_count')}`",
                        f"`{values.get('canonical_match')}`",
                        f"`{values.get('rdkit_validity')}`",
                        f"`{values.get('two_attachment_validity')}`",
                        f"`{values.get('exact_string_match')}`",
                        f"`{values.get('failed_count')}`",
                    ]
                )
                + " |"
            )

        macro = metrics["robustness_strategy_macro_avg"]
        all_views = metrics["robustness_record_all_views_success"]
        any_view = metrics["robustness_record_any_view_success"]
        partial = metrics["robustness_record_partial_success"]
        lines.extend(
            [
                "",
                "## Aggregates",
                "",
                "| aggregate | value |",
                "|---|---:|",
                f"| `strategy_macro_avg.canonical_match` | `{macro.get('canonical_match')}` |",
                f"| `strategy_macro_avg.rdkit_validity` | `{macro.get('rdkit_validity')}` |",
                f"| `strategy_macro_avg.two_attachment_validity` | `{macro.get('two_attachment_validity')}` |",
                f"| `strategy_macro_avg.exact_string_match` | `{macro.get('exact_string_match')}` |",
                f"| `record_all_views_success` | `{all_views.get('success_count')}/{all_views.get('record_count')} = {all_views.get('rate')}` |",
                f"| `record_any_view_success` | `{any_view.get('success_count')}/{any_view.get('record_count')} = {any_view.get('rate')}` |",
                f"| `record_partial_success` | `{partial.get('success_count')}/{partial.get('record_count')} = {partial.get('rate')}` |",
            ]
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_curriculum_extra_eval_outputs(
    *,
    output_dir: Path,
    prefix: str,
    split: str,
    metrics: dict[str, Any],
    failed_cases: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    config: StageBConfig,
    eval_preview_path: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{prefix}_{split}"
    (output_dir / f"{stem}_eval_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_jsonl(output_dir / f"{stem}_failed_cases.jsonl", failed_cases)
    write_jsonl(output_dir / f"{stem}_predictions.jsonl", predictions)
    write_curriculum_extra_eval_report(
        output_dir / f"{stem}_eval_report.md",
        metrics=metrics,
        config=config,
        eval_preview_path=eval_preview_path,
        split=split,
    )


def run_curriculum_extra_restore_eval(
    *,
    eval_preview_path: Path,
    output_dir: Path,
    output_prefix: str,
    model: torch.nn.Module,
    restore_head: RestoreCrossAttentionHead,
    tokenizer: Any,
    config: StageBConfig,
    collate_fn: Any,
    device: torch.device,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    validate_preview_tokenizer_compatibility(tokenizer, eval_preview_path)
    for split in ("valid", "test"):
        dataset = StageAPreviewDataset(eval_preview_path, split=split)
        if len(dataset) == 0:
            continue
        dataloader = DataLoader(dataset, batch_size=config.per_device_eval_batch_size, shuffle=False, collate_fn=collate_fn)
        metrics, failed_cases, predictions = evaluate_restore(
            model=model,
            restore_head=restore_head,
            dataloader=dataloader,
            tokenizer=tokenizer,
            config=config,
            device=device,
            decode_sample_limit=full_decode_sample_limit(dataset),
        )
        metrics = add_robustness_aggregates(metrics, predictions)
        write_curriculum_extra_eval_outputs(
            output_dir=output_dir,
            prefix=output_prefix,
            split=split,
            metrics=metrics,
            failed_cases=failed_cases,
            predictions=predictions,
            config=config,
            eval_preview_path=eval_preview_path,
        )
        results[split] = metrics
    return results


def save_curriculum_checkpoint_with_full_eval(
    *,
    checkpoint_dir: Path,
    checkpoint_name: str,
    epoch: int,
    optimizer_step: int,
    model: Any,
    restore_head: RestoreCrossAttentionHead,
    dataloader: DataLoader,
    tokenizer: Any,
    config: StageBConfig,
    device: torch.device,
    recent_train_loss: float | None,
    epoch_train_loss_mean: float | None,
    decode_sample_limit: int,
    curriculum_metadata: dict[str, Any],
) -> dict[str, Any]:
    metrics, failed_cases, predictions = evaluate_restore(
        model=model,
        restore_head=restore_head,
        dataloader=dataloader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        max_batches=None,
        decode_sample_limit=decode_sample_limit,
    )
    metrics = {
        **metrics,
        "checkpoint_name": checkpoint_name,
        "checkpoint_epoch": epoch,
        "checkpoint_optimizer_step": optimizer_step,
        "checkpoint_recent_train_loss": recent_train_loss,
        "checkpoint_epoch_train_loss_mean": epoch_train_loss_mean,
        "early_stopping_monitor_only": True,
        "full_epoch_decode": True,
        **curriculum_metadata,
    }
    save_run_artifacts(
        output_dir=checkpoint_dir,
        model=model,
        restore_head=restore_head,
        tokenizer=tokenizer,
        config=config,
        metrics=metrics,
        failed_cases=failed_cases,
        predictions=predictions,
    )
    (checkpoint_dir / "checkpoint_metadata.json").write_text(
        json.dumps(
            {
                "checkpoint_name": checkpoint_name,
                "epoch": epoch,
                "optimizer_step": optimizer_step,
                "recent_train_loss": recent_train_loss,
                "epoch_train_loss_mean": epoch_train_loss_mean,
                "eval_sample_limit": 0,
                "eval_decode_sample_limit": decode_sample_limit,
                "early_stopping_monitor_only": True,
                "full_epoch_decode": True,
                **curriculum_metadata,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return metrics


def update_early_stopping_monitor(
    *,
    config: StageBConfig,
    checkpoint_metrics: dict[str, Any],
    checkpoint_name: str,
    epoch_index: int,
    best_metric: float | None,
    best_checkpoint: str | None,
    wait: int,
) -> tuple[dict[str, Any] | None, float | None, str | None, int]:
    if not config.early_stopping_enabled:
        return {"enabled": False, "monitor_only": True, "stop_training": False}, best_metric, best_checkpoint, wait

    raw_metric = checkpoint_metrics.get(config.early_stopping_metric)
    if not isinstance(raw_metric, (int, float)) or not math.isfinite(float(raw_metric)):
        raise ValueError(f"early stopping metric is missing or non-finite: {config.early_stopping_metric}")
    metric_value = float(raw_metric)
    improved = early_stopping_is_improvement(
        metric_value,
        best_metric,
        mode=config.early_stopping_mode,
        min_delta=config.early_stopping_min_delta,
    )
    reason = None
    would_stop_training = False
    if improved:
        best_metric = metric_value
        best_checkpoint = checkpoint_name
        wait = 0
    elif epoch_index >= config.early_stopping_min_epochs:
        wait += 1
        if wait >= config.early_stopping_patience:
            would_stop_training = True
            reason = (
                f"{config.early_stopping_metric} did not improve by "
                f"{config.early_stopping_min_delta} for {wait} epoch checkpoints"
            )
    state = {
        "enabled": True,
        "monitor_only": True,
        "metric": config.early_stopping_metric,
        "mode": config.early_stopping_mode,
        "current": metric_value,
        "best": best_metric,
        "best_checkpoint": best_checkpoint,
        "wait": wait,
        "stop_training": False,
        "would_stop_training": would_stop_training,
        "reason": reason,
    }
    return state, best_metric, best_checkpoint, wait


def main() -> None:
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

    args = parse_args()
    config = load_yaml_config(args.config)
    output_dir_override = args.output_dir or DEFAULT_CURRICULUM_OUTPUT_DIR
    config = StageBConfig(**{**asdict(config), "output_dir": str(output_dir_override)})
    if args.preview_path is not None:
        config = StageBConfig(**{**asdict(config), "preview_path": str(args.preview_path)})

    validate_training_config(config)
    set_seed(config.seed)
    if not torch.cuda.is_available():
        raise SystemExit("Stage B curriculum training requires a CUDA GPU.")
    device = torch.device("cuda")

    tokenizer = AutoTokenizer.from_pretrained(args.model_name_or_path, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    validate_preview_tokenizer_compatibility(tokenizer, config.preview_path)

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name_or_path,
        torch_dtype=torch.bfloat16,
        device_map={"": 0},
    )
    model.config.use_cache = False
    lora_config = LoraConfig(
        r=config.lora_rank,
        lora_alpha=config.lora_alpha,
        target_modules=list(config.lora_target_modules),
        lora_dropout=config.lora_dropout,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    model.train()

    hidden_size = int(model.config.hidden_size)
    restore_head = RestoreCrossAttentionHead(
        vocab_size=len(tokenizer),
        hidden_size=config.restore_hidden_size,
        num_layers=config.restore_num_layers,
        num_attention_heads=config.restore_num_attention_heads,
        dropout=config.restore_dropout,
        pad_token_id=tokenizer.pad_token_id,
        decoder_start_token_id=tokenizer.eos_token_id,
        max_target_positions=config.max_seq_len_restore_label,
        encoder_hidden_size=hidden_size,
    ).to(device=device)

    preview_path = Path(config.preview_path)
    train_dataset = StageAPreviewDataset(preview_path, split="train")
    valid_dataset = StageAPreviewDataset(preview_path, split="valid")
    test_dataset = StageAPreviewDataset(preview_path, split="test")
    collate = lambda rows: collate_restore_records(  # noqa: E731
        rows,
        pad_token_id=tokenizer.pad_token_id,
        label_pad_token_id=tokenizer.pad_token_id,
    )
    valid_loader = DataLoader(valid_dataset, batch_size=config.per_device_eval_batch_size, shuffle=False, collate_fn=collate)
    test_loader = DataLoader(test_dataset, batch_size=config.per_device_eval_batch_size, shuffle=False, collate_fn=collate)
    optimizer = build_optimizer(model, restore_head, config)

    output_dir = Path(config.output_dir)
    reset_training_metric_files(output_dir)
    clean_train_rows, train_conflict_metadata, train_conflict_audit = filter_train_input_label_conflicts(train_dataset.rows)
    write_jsonl(output_dir / TRAIN_CONFLICT_AUDIT_JSONL, train_conflict_audit)
    if train_conflict_metadata["train_conflict_filter_remaining_conflicting_input_view_count"] != 0:
        raise AssertionError("train input-label conflict filter left unresolved conflicts")
    print(json.dumps({"train_conflict_filter": train_conflict_metadata}, ensure_ascii=False, sort_keys=True))

    trainable_params = [param for param in model.parameters() if param.requires_grad] + list(restore_head.parameters())
    train_losses: list[float] = []
    optimizer.zero_grad(set_to_none=True)
    optimizer_steps = 0
    completed_epochs = 0
    best_early_metric: float | None = None
    best_early_checkpoint: str | None = None
    early_stop_wait = 0

    for epoch_index in range(1, config.max_epochs + 1):
        completed_epochs = epoch_index
        epoch_rows, curriculum_metadata = build_curriculum_epoch_rows(
            clean_train_rows,
            epoch_index=epoch_index,
            seed=config.seed,
            epoch_target_row_count=train_conflict_metadata["train_conflict_filter_original_row_count"],
        )
        curriculum_metadata = {**train_conflict_metadata, **curriculum_metadata}
        train_loader = DataLoader(
            epoch_rows,
            batch_size=config.per_device_train_batch_size,
            shuffle=False,
            collate_fn=collate,
        )
        print(json.dumps({"curriculum_epoch": epoch_index, **curriculum_metadata}, ensure_ascii=False, sort_keys=True))
        epoch_train_losses: list[float] = []
        for step, batch in enumerate(train_loader, start=1):
            model.train()
            restore_head.train()
            batch = batch.to(device)
            hidden = forward_encoder_hidden(model, batch)
            decoder_input = shift_restore_labels_right(
                batch.restore_labels,
                batch.restore_label_mask,
                decoder_start_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.pad_token_id,
            )
            logits = restore_head(decoder_input, hidden, batch.attention_mask_view1)
            loss = masked_cross_entropy(logits.float(), batch.restore_labels, batch.restore_label_mask)
            if not torch.isfinite(loss):
                raise FloatingPointError(f"non-finite training loss at step {step}: {loss.item()}")
            (loss / config.gradient_accumulation_steps).backward()
            loss_value = float(loss.item())
            train_losses.append(loss_value)
            epoch_train_losses.append(loss_value)

            if step % config.gradient_accumulation_steps == 0 or step == len(train_loader):
                torch.nn.utils.clip_grad_norm_(trainable_params, config.max_grad_norm)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                optimizer_steps += 1

                if config.quick_eval_every_steps > 0 and optimizer_steps % config.quick_eval_every_steps == 0:
                    quick_batches = math.ceil(config.quick_eval_samples / config.per_device_eval_batch_size)
                    quick_metrics, _, _ = evaluate_restore(
                        model=model,
                        restore_head=restore_head,
                        dataloader=valid_loader,
                        tokenizer=tokenizer,
                        config=config,
                        device=device,
                        max_batches=quick_batches,
                        decode_sample_limit=config.quick_eval_decode_samples,
                    )
                    quick_row = {
                        "epoch": epoch_index,
                        "optimizer_step": optimizer_steps,
                        "train_loss": train_losses[-1],
                        "quick_valid": quick_metrics,
                    }
                    append_quick_eval_metrics(output_dir, quick_row)
                    print(json.dumps(quick_row, ensure_ascii=False))

                if config.checkpoint_every_steps > 0 and optimizer_steps % config.checkpoint_every_steps == 0:
                    checkpoint_name = f"step_{optimizer_steps:06d}"
                    checkpoint_metrics = save_curriculum_checkpoint_with_full_eval(
                        checkpoint_dir=output_dir / "checkpoints" / checkpoint_name,
                        checkpoint_name=checkpoint_name,
                        epoch=epoch_index,
                        optimizer_step=optimizer_steps,
                        model=model,
                        restore_head=restore_head,
                        dataloader=valid_loader,
                        tokenizer=tokenizer,
                        config=config,
                        device=device,
                        recent_train_loss=train_losses[-1] if train_losses else None,
                        epoch_train_loss_mean=None,
                        decode_sample_limit=full_decode_sample_limit(valid_dataset),
                        curriculum_metadata=curriculum_metadata,
                    )
                    copy_config_snapshot(args.config, output_dir / "checkpoints" / checkpoint_name)
                    print(json.dumps({"checkpoint": checkpoint_name, "metrics": checkpoint_metrics}, ensure_ascii=False))

        if config.checkpoint_at_epoch_end:
            checkpoint_name = f"epoch_{epoch_index:03d}"
            epoch_train_loss_mean = sum(epoch_train_losses) / len(epoch_train_losses) if epoch_train_losses else None
            checkpoint_metrics = save_curriculum_checkpoint_with_full_eval(
                checkpoint_dir=output_dir / "checkpoints" / checkpoint_name,
                checkpoint_name=checkpoint_name,
                epoch=epoch_index,
                optimizer_step=optimizer_steps,
                model=model,
                restore_head=restore_head,
                dataloader=valid_loader,
                tokenizer=tokenizer,
                config=config,
                device=device,
                recent_train_loss=train_losses[-1] if train_losses else None,
                epoch_train_loss_mean=epoch_train_loss_mean,
                decode_sample_limit=full_decode_sample_limit(valid_dataset),
                curriculum_metadata=curriculum_metadata,
            )
            copy_config_snapshot(args.config, output_dir / "checkpoints" / checkpoint_name)
            print(json.dumps({"checkpoint": checkpoint_name, "metrics": checkpoint_metrics}, ensure_ascii=False))
            early_stopping_state, best_early_metric, best_early_checkpoint, early_stop_wait = update_early_stopping_monitor(
                config=config,
                checkpoint_metrics=checkpoint_metrics,
                checkpoint_name=checkpoint_name,
                epoch_index=epoch_index,
                best_metric=best_early_metric,
                best_checkpoint=best_early_checkpoint,
                wait=early_stop_wait,
            )
            print(json.dumps({"early_stopping_monitor": early_stopping_state}, ensure_ascii=False))
            append_epoch_metrics(output_dir, checkpoint_metrics, early_stopping=early_stopping_state)

    metrics, failed_cases, predictions = evaluate_restore(
        model=model,
        restore_head=restore_head,
        dataloader=valid_loader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        decode_sample_limit=full_decode_sample_limit(valid_dataset),
    )
    test_metrics, test_failed_cases, test_predictions = evaluate_restore(
        model=model,
        restore_head=restore_head,
        dataloader=test_loader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        decode_sample_limit=full_decode_sample_limit(test_dataset),
    )
    first_window = train_losses[: max(1, len(train_losses) // 5)]
    last_window = train_losses[-max(1, len(train_losses) // 5) :]
    if first_window and last_window:
        metrics["train_loss_first_window"] = sum(first_window) / len(first_window)
        metrics["train_loss_last_window"] = sum(last_window) / len(last_window)
        metrics["train_loss_decreased"] = metrics["train_loss_last_window"] < metrics["train_loss_first_window"]
    metrics["completed_epochs"] = completed_epochs
    metrics["optimizer_steps"] = optimizer_steps
    metrics["train_sample_count"] = len(train_dataset)
    metrics["train_clean_sample_count"] = len(clean_train_rows)
    metrics["valid_sample_count"] = len(valid_dataset)
    metrics["test_sample_count"] = len(test_dataset)
    metrics["early_stopped"] = False
    metrics["early_stop_reason"] = None
    metrics["early_stopping_monitor_only"] = True
    metrics["best_early_stopping_metric"] = best_early_metric
    metrics["best_early_stopping_checkpoint"] = best_early_checkpoint
    metrics["identity_test_loss"] = test_metrics.get("loss")
    metrics["identity_test_canonical_match"] = test_metrics.get("canonical_match")
    metrics["full_final_decode"] = True
    metrics.update(train_conflict_metadata)
    save_run_artifacts(
        output_dir=output_dir,
        model=model,
        restore_head=restore_head,
        tokenizer=tokenizer,
        config=config,
        metrics=metrics,
        failed_cases=failed_cases,
        predictions=predictions,
    )
    write_extra_eval_outputs(
        output_dir=output_dir,
        prefix="identity",
        split="test",
        metrics={**test_metrics, "full_final_decode": True},
        failed_cases=test_failed_cases,
        predictions=test_predictions,
        config=config,
        eval_preview_path=preview_path,
    )
    copy_config_snapshot(args.config, output_dir)
    extra_eval: dict[str, dict[str, Any]] = {}
    if args.eval_preview_path is not None:
        extra_eval = run_curriculum_extra_restore_eval(
            eval_preview_path=args.eval_preview_path,
            output_dir=output_dir,
            output_prefix=args.eval_output_prefix,
            model=model,
            restore_head=restore_head,
            tokenizer=tokenizer,
            config=config,
            collate_fn=collate,
            device=device,
        )

    del optimizer
    del model
    del restore_head
    gc.collect()
    torch.cuda.empty_cache()
    reload_smoke = run_reload_smoke(
        model_name_or_path=args.model_name_or_path,
        output_dir=output_dir,
        tokenizer=tokenizer,
        config=config,
        valid_dataset=valid_dataset,
        collate_fn=collate,
        device=device,
    )
    print(
        json.dumps(
            {
                "eval_metrics": metrics,
                "identity_test_metrics": test_metrics,
                "extra_eval": extra_eval,
                "reload_smoke": reload_smoke,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
