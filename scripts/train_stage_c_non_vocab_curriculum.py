from __future__ import annotations

import argparse
import gc
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import DataLoader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.train_stage_b_restore_curriculum import (  # noqa: E402
    TRAIN_CONFLICT_AUDIT_JSONL,
    build_curriculum_epoch_rows,
    filter_train_input_label_conflicts,
)
from scripts.train_stage_b_restore_full import (  # noqa: E402
    full_decode_sample_limit,
    validate_preview_tokenizer_compatibility,
    write_jsonl,
)
from scripts.train_stage_c_non_vocab_full import (  # noqa: E402
    StageCConfig,
    StageCPreviewGraphDataset,
    append_epoch_metrics,
    build_optimizer,
    build_stage_c_modules,
    collate_stage_c_records,
    copy_config_snapshot,
    early_stopping_is_improvement,
    evaluate_stage_c,
    formal_eval_decode_sample_limit,
    formal_eval_retrieval_sample_limit,
    forward_stage_c,
    load_feature_schema,
    load_yaml_config,
    reset_epoch_metrics,
    run_extra_stage_c_eval,
    run_reload_check,
    save_stage_c_artifacts,
    validate_training_config,
    write_extra_stage_c_eval_outputs,
)


DEFAULT_CURRICULUM_CONFIG_PATH = ROOT / "configs" / "stage_c_non_vocab_aug_v2_curriculum_full_20epoch_bf16.yaml"
DEFAULT_CURRICULUM_OUTPUT_DIR = ROOT / "outputs" / "stage_c_non_vocab_aug_v2_curriculum_full_30epoch"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Stage C non-vocab with curriculum augmentation and full eval.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CURRICULUM_CONFIG_PATH)
    parser.add_argument("--model-name-or-path", required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--preview-path", type=Path, default=None)
    parser.add_argument("--graph-path", type=Path, default=None)
    parser.add_argument("--graph-feature-schema-path", type=Path, default=None)
    parser.add_argument("--eval-preview-path", type=Path, default=None)
    parser.add_argument("--eval-output-prefix", default="robustness")
    return parser.parse_args()


def update_early_stopping_monitor(
    *,
    config: StageCConfig,
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


def save_curriculum_checkpoint_with_full_eval(
    *,
    checkpoint_dir: Path,
    checkpoint_name: str,
    epoch: int,
    optimizer_step: int,
    model: Any,
    restore_head: Any,
    graph_encoder: Any,
    text_projector: Any,
    graph_projector: Any,
    graph_memory_projector: Any,
    dataloader: DataLoader,
    tokenizer: Any,
    config: StageCConfig,
    device: torch.device,
    feature_schema: dict[str, Any],
    recent_train_loss: float | None,
    epoch_train_loss_mean: float | None,
    curriculum_metadata: dict[str, Any],
) -> dict[str, Any]:
    max_batches = None
    if not config.formal_eval_full_decode and config.checkpoint_eval_samples > 0:
        max_batches = math.ceil(config.checkpoint_eval_samples / config.per_device_eval_batch_size)
    eval_sample_limit = (
        full_decode_sample_limit(dataloader.dataset)
        if config.formal_eval_full_decode
        else config.checkpoint_eval_samples
    )
    decode_sample_limit = formal_eval_decode_sample_limit(
        config,
        dataloader.dataset,
        config.checkpoint_eval_decode_samples,
    )
    retrieval_sample_limit = formal_eval_retrieval_sample_limit(
        config,
        dataloader.dataset,
        config.checkpoint_eval_retrieval_samples,
    )
    metrics, failed_cases, predictions, retrieval_rows = evaluate_stage_c(
        model=model,
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        dataloader=dataloader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        max_batches=max_batches,
        decode_sample_limit=decode_sample_limit,
        retrieval_sample_limit=retrieval_sample_limit,
        dedup_retrieval=config.formal_eval_dedup_retrieval,
    )
    metrics = {
        **metrics,
        "checkpoint_name": checkpoint_name,
        "checkpoint_epoch": epoch,
        "checkpoint_optimizer_step": optimizer_step,
        "checkpoint_recent_train_loss": recent_train_loss,
        "checkpoint_epoch_train_loss_mean": epoch_train_loss_mean,
        "early_stopping_monitor_only": True,
        "formal_eval_full_decode": config.formal_eval_full_decode,
        "formal_eval_dedup_retrieval": config.formal_eval_dedup_retrieval,
        "full_epoch_decode": config.formal_eval_full_decode,
        "dedup_epoch_retrieval": config.formal_eval_dedup_retrieval,
        **curriculum_metadata,
    }
    save_stage_c_artifacts(
        output_dir=checkpoint_dir,
        model=model,
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        tokenizer=tokenizer,
        config=config,
        metrics=metrics,
        failed_cases=failed_cases,
        restore_predictions=predictions,
        retrieval_rows=retrieval_rows,
        feature_schema=feature_schema,
    )
    (checkpoint_dir / "checkpoint_metadata.json").write_text(
        json.dumps(
            {
                "checkpoint_name": checkpoint_name,
                "epoch": epoch,
                "optimizer_step": optimizer_step,
                "recent_train_loss": recent_train_loss,
                "epoch_train_loss_mean": epoch_train_loss_mean,
                "eval_sample_limit": eval_sample_limit,
                "eval_decode_sample_limit": decode_sample_limit,
                "eval_retrieval_sample_limit": retrieval_sample_limit,
                "early_stopping_monitor_only": True,
                "formal_eval_full_decode": config.formal_eval_full_decode,
                "formal_eval_dedup_retrieval": config.formal_eval_dedup_retrieval,
                "full_epoch_decode": config.formal_eval_full_decode,
                "dedup_epoch_retrieval": config.formal_eval_dedup_retrieval,
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


def main() -> None:
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

    args = parse_args()
    config = load_yaml_config(args.config)
    updates: dict[str, Any] = {"output_dir": str(args.output_dir or DEFAULT_CURRICULUM_OUTPUT_DIR)}
    if args.preview_path is not None:
        updates["preview_path"] = str(args.preview_path)
    if args.graph_path is not None:
        updates["graph_path"] = str(args.graph_path)
    if args.graph_feature_schema_path is not None:
        updates["graph_feature_schema_path"] = str(args.graph_feature_schema_path)
    config = StageCConfig(**{**asdict(config), **updates})

    validate_training_config(config)
    set_seed(config.seed)
    if not torch.cuda.is_available():
        raise SystemExit("Stage C curriculum training requires a CUDA GPU.")
    device = torch.device("cuda")
    feature_schema = load_feature_schema(Path(config.graph_feature_schema_path), Path(config.graph_path))

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
    restore_head, graph_encoder, text_projector, graph_projector, graph_memory_projector = build_stage_c_modules(
        config=config,
        tokenizer=tokenizer,
        model_hidden_size=hidden_size,
        feature_schema=feature_schema,
        device=device,
    )

    train_dataset = StageCPreviewGraphDataset(
        preview_path=config.preview_path,
        graph_path=config.graph_path,
        split="train",
        max_samples=config.max_train_samples,
    )
    valid_dataset = StageCPreviewGraphDataset(
        preview_path=config.preview_path,
        graph_path=config.graph_path,
        split="valid",
        max_samples=config.max_valid_samples,
    )
    test_dataset = StageCPreviewGraphDataset(
        preview_path=config.preview_path,
        graph_path=config.graph_path,
        split="test",
        max_samples=config.max_valid_samples,
    )
    collate = lambda rows: collate_stage_c_records(  # noqa: E731
        rows,
        pad_token_id=tokenizer.pad_token_id,
        label_pad_token_id=tokenizer.pad_token_id,
        feature_schema=feature_schema,
    )
    valid_loader = DataLoader(valid_dataset, batch_size=config.per_device_eval_batch_size, shuffle=False, collate_fn=collate)
    test_loader = DataLoader(test_dataset, batch_size=config.per_device_eval_batch_size, shuffle=False, collate_fn=collate)
    optimizer = build_optimizer(
        model=model,
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        config=config,
    )

    output_dir = Path(config.output_dir)
    reset_epoch_metrics(output_dir)
    clean_train_rows, train_conflict_metadata, train_conflict_audit = filter_train_input_label_conflicts(train_dataset.rows)
    write_jsonl(output_dir / TRAIN_CONFLICT_AUDIT_JSONL, train_conflict_audit)
    if train_conflict_metadata["train_conflict_filter_remaining_conflicting_input_view_count"] != 0:
        raise AssertionError("train input-label conflict filter left unresolved conflicts")
    print(json.dumps({"train_conflict_filter": train_conflict_metadata}, ensure_ascii=False, sort_keys=True))

    trainable_params = (
        [param for param in model.parameters() if param.requires_grad]
        + list(restore_head.parameters())
        + list(graph_encoder.parameters())
        + list(text_projector.parameters())
        + list(graph_projector.parameters())
        + list(graph_memory_projector.parameters())
    )
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
            graph_encoder.train()
            text_projector.train()
            graph_projector.train()
            graph_memory_projector.train()
            batch = batch.to(device)
            output = forward_stage_c(
                model=model,
                batch=batch,
                tokenizer=tokenizer,
                restore_head=restore_head,
                graph_encoder=graph_encoder,
                text_projector=text_projector,
                graph_projector=graph_projector,
                graph_memory_projector=graph_memory_projector,
                config=config,
            )
            if not torch.isfinite(output.total_loss):
                raise FloatingPointError(f"non-finite training loss at step {step}: {output.total_loss.item()}")
            (output.total_loss / config.gradient_accumulation_steps).backward()
            loss_value = float(output.total_loss.item())
            train_losses.append(loss_value)
            epoch_train_losses.append(loss_value)

            if step % config.gradient_accumulation_steps == 0 or step == len(train_loader):
                torch.nn.utils.clip_grad_norm_(trainable_params, config.max_grad_norm)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                optimizer_steps += 1

                if config.quick_eval_every_steps > 0 and optimizer_steps % config.quick_eval_every_steps == 0:
                    quick_batches = math.ceil(config.quick_eval_samples / config.per_device_eval_batch_size)
                    quick_metrics, _, _, _ = evaluate_stage_c(
                        model=model,
                        restore_head=restore_head,
                        graph_encoder=graph_encoder,
                        text_projector=text_projector,
                        graph_projector=graph_projector,
                        graph_memory_projector=graph_memory_projector,
                        dataloader=valid_loader,
                        tokenizer=tokenizer,
                        config=config,
                        device=device,
                        max_batches=quick_batches,
                        decode_sample_limit=config.quick_eval_decode_samples,
                        retrieval_sample_limit=config.quick_eval_retrieval_samples,
                        dedup_retrieval=False,
                    )
                    print(
                        json.dumps(
                            {
                                "epoch": epoch_index,
                                "optimizer_step": optimizer_steps,
                                "train_loss": train_losses[-1],
                                "quick_valid": quick_metrics,
                            },
                            ensure_ascii=False,
                        )
                    )

                if config.checkpoint_every_steps > 0 and optimizer_steps % config.checkpoint_every_steps == 0:
                    checkpoint_name = f"step_{optimizer_steps:06d}"
                    checkpoint_metrics = save_curriculum_checkpoint_with_full_eval(
                        checkpoint_dir=output_dir / "checkpoints" / checkpoint_name,
                        checkpoint_name=checkpoint_name,
                        epoch=epoch_index,
                        optimizer_step=optimizer_steps,
                        model=model,
                        restore_head=restore_head,
                        graph_encoder=graph_encoder,
                        text_projector=text_projector,
                        graph_projector=graph_projector,
                        graph_memory_projector=graph_memory_projector,
                        dataloader=valid_loader,
                        tokenizer=tokenizer,
                        config=config,
                        device=device,
                        feature_schema=feature_schema,
                        recent_train_loss=train_losses[-1] if train_losses else None,
                        epoch_train_loss_mean=None,
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
                graph_encoder=graph_encoder,
                text_projector=text_projector,
                graph_projector=graph_projector,
                graph_memory_projector=graph_memory_projector,
                dataloader=valid_loader,
                tokenizer=tokenizer,
                config=config,
                device=device,
                feature_schema=feature_schema,
                recent_train_loss=train_losses[-1] if train_losses else None,
                epoch_train_loss_mean=epoch_train_loss_mean,
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

    valid_decode_sample_limit = formal_eval_decode_sample_limit(config, valid_dataset, config.eval_decode_samples)
    valid_retrieval_sample_limit = formal_eval_retrieval_sample_limit(config, valid_dataset, config.eval_retrieval_samples)
    test_decode_sample_limit = formal_eval_decode_sample_limit(config, test_dataset, config.eval_decode_samples)
    test_retrieval_sample_limit = formal_eval_retrieval_sample_limit(config, test_dataset, config.eval_retrieval_samples)
    metrics, failed_cases, predictions, retrieval_rows = evaluate_stage_c(
        model=model,
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        dataloader=valid_loader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        decode_sample_limit=valid_decode_sample_limit,
        retrieval_sample_limit=valid_retrieval_sample_limit,
        dedup_retrieval=config.formal_eval_dedup_retrieval,
    )
    test_metrics, test_failed_cases, test_predictions, test_retrieval_rows = evaluate_stage_c(
        model=model,
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        dataloader=test_loader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        decode_sample_limit=test_decode_sample_limit,
        retrieval_sample_limit=test_retrieval_sample_limit,
        dedup_retrieval=config.formal_eval_dedup_retrieval,
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
    metrics["formal_eval_full_decode"] = config.formal_eval_full_decode
    metrics["formal_eval_dedup_retrieval"] = config.formal_eval_dedup_retrieval
    metrics["full_final_decode"] = True
    metrics["dedup_final_retrieval"] = config.formal_eval_dedup_retrieval
    metrics["all_view_test_loss"] = test_metrics.get("loss")
    metrics["all_view_test_restore_loss"] = test_metrics.get("restore_loss")
    metrics["all_view_test_canonical_match"] = test_metrics.get("canonical_match")
    metrics.update(train_conflict_metadata)
    test_metrics = {
        **test_metrics,
        "formal_eval_full_decode": config.formal_eval_full_decode,
        "formal_eval_dedup_retrieval": config.formal_eval_dedup_retrieval,
        "full_final_decode": True,
        "dedup_final_retrieval": config.formal_eval_dedup_retrieval,
    }
    save_stage_c_artifacts(
        output_dir=output_dir,
        model=model,
        restore_head=restore_head,
        graph_encoder=graph_encoder,
        text_projector=text_projector,
        graph_projector=graph_projector,
        graph_memory_projector=graph_memory_projector,
        tokenizer=tokenizer,
        config=config,
        metrics=metrics,
        failed_cases=failed_cases,
        restore_predictions=predictions,
        retrieval_rows=retrieval_rows,
        feature_schema=feature_schema,
    )
    write_extra_stage_c_eval_outputs(
        output_dir=output_dir,
        prefix="all_view",
        split="test",
        metrics=test_metrics,
        failed_cases=test_failed_cases,
        predictions=test_predictions,
        retrieval_rows=test_retrieval_rows,
        config=config,
        eval_preview_path=Path(config.preview_path),
    )
    copy_config_snapshot(args.config, output_dir)
    extra_eval: dict[str, dict[str, Any]] = {}
    if args.eval_preview_path is not None:
        extra_eval = run_extra_stage_c_eval(
            eval_preview_path=args.eval_preview_path,
            output_dir=output_dir,
            output_prefix=args.eval_output_prefix,
            model=model,
            restore_head=restore_head,
            graph_encoder=graph_encoder,
            text_projector=text_projector,
            graph_projector=graph_projector,
            graph_memory_projector=graph_memory_projector,
            tokenizer=tokenizer,
            config=config,
            collate_fn=collate,
            device=device,
        )

    del optimizer
    del model
    del restore_head
    del graph_encoder
    del text_projector
    del graph_projector
    del graph_memory_projector
    gc.collect()
    torch.cuda.empty_cache()
    reload_check = run_reload_check(
        model_name_or_path=args.model_name_or_path,
        output_dir=output_dir,
        tokenizer=tokenizer,
        config=config,
        feature_schema=feature_schema,
        valid_dataset=valid_dataset,
        collate_fn=collate,
        device=device,
    )
    print(
        json.dumps(
            {
                "eval_metrics": metrics,
                "all_view_test_metrics": test_metrics,
                "extra_eval": extra_eval,
                "reload_check": reload_check,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
