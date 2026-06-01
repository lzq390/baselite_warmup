from __future__ import annotations

import argparse
import gc
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import DataLoader


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.train_stage_b_restore_full import (  # noqa: E402
    RestoreCrossAttentionHead,
    StageAPreviewDataset,
    StageBConfig,
    collate_restore_records,
    evaluate_restore,
    validate_preview_tokenizer_compatibility,
    write_jsonl,
)


DEFAULT_PREVIEW_PATH = ROOT / "data" / "baselite_smiles_aug_v1" / "training_template_preview.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "stage_b_restore_aug_full_20epoch" / "candidate_test_eval_full"


def parse_candidate(value: str) -> tuple[str, Path]:
    if "=" in value:
        name, path = value.split("=", 1)
        if not name:
            raise argparse.ArgumentTypeError(f"candidate name is empty: {value!r}")
        return name, Path(path)
    path = Path(value)
    return path.name, path


def load_checkpoint_config(checkpoint_dir: Path) -> StageBConfig:
    for path in (
        checkpoint_dir / "training_config.json",
        checkpoint_dir / "restore_head" / "restore_head_config.json",
    ):
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if "lora_target_modules" in data:
                data["lora_target_modules"] = tuple(data["lora_target_modules"])
            allowed = set(StageBConfig.__dataclass_fields__)
            return StageBConfig(**{key: value for key, value in data.items() if key in allowed})
    raise FileNotFoundError(f"{checkpoint_dir}: missing training_config.json and restore_head_config.json")


def write_eval_report(
    path: Path,
    *,
    candidate_name: str,
    checkpoint_dir: Path,
    split: str,
    preview_path: Path,
    metrics: dict[str, Any],
) -> None:
    lines = [
        "# Stage B Candidate Test Eval",
        "",
        f"- candidate: `{candidate_name}`",
        f"- checkpoint: `{checkpoint_dir}`",
        f"- split: `{split}`",
        f"- preview path: `{preview_path}`",
        "",
        "## Metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate_candidate(
    *,
    candidate_name: str,
    checkpoint_dir: Path,
    model_name_or_path: str,
    preview_path: Path,
    split: str,
    batch_size: int,
    decode_sample_limit: int | None,
    output_dir: Path,
    local_files_only: bool,
) -> dict[str, Any]:
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    checkpoint_dir = checkpoint_dir.resolve()
    if not checkpoint_dir.exists():
        raise FileNotFoundError(f"candidate checkpoint not found: {checkpoint_dir}")
    lora_dir = checkpoint_dir / "lora_adapter"
    restore_path = checkpoint_dir / "restore_head" / "restore_head.pt"
    if not lora_dir.exists():
        raise FileNotFoundError(f"{checkpoint_dir}: missing lora_adapter")
    if not restore_path.exists():
        raise FileNotFoundError(f"{checkpoint_dir}: missing restore_head/restore_head.pt")

    tokenizer = AutoTokenizer.from_pretrained(
        model_name_or_path,
        use_fast=True,
        local_files_only=local_files_only,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    validate_preview_tokenizer_compatibility(tokenizer, preview_path)

    config = load_checkpoint_config(checkpoint_dir)
    dataset = StageAPreviewDataset(preview_path, split=split)
    if len(dataset) == 0:
        raise ValueError(f"{preview_path}: no rows for split={split!r}")
    effective_decode_limit = len(dataset) if decode_sample_limit is None else decode_sample_limit
    config = StageBConfig(
        **{
            **asdict(config),
            "preview_path": str(preview_path),
            "per_device_eval_batch_size": batch_size,
            "eval_decode_samples": effective_decode_limit,
        }
    )
    collate = lambda rows: collate_restore_records(  # noqa: E731
        rows,
        pad_token_id=tokenizer.pad_token_id,
        label_pad_token_id=tokenizer.pad_token_id,
    )
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=False, collate_fn=collate)

    base_model = AutoModelForCausalLM.from_pretrained(
        model_name_or_path,
        torch_dtype=torch.bfloat16,
        device_map={"": 0},
        local_files_only=local_files_only,
    )
    model = PeftModel.from_pretrained(base_model, lora_dir)
    model.config.use_cache = False
    model.eval()
    device = torch.device("cuda")

    restore_head = RestoreCrossAttentionHead(
        vocab_size=len(tokenizer),
        hidden_size=config.restore_hidden_size,
        num_layers=config.restore_num_layers,
        num_attention_heads=config.restore_num_attention_heads,
        dropout=config.restore_dropout,
        pad_token_id=tokenizer.pad_token_id,
        decoder_start_token_id=tokenizer.eos_token_id,
        max_target_positions=config.max_seq_len_restore_label,
        encoder_hidden_size=int(model.config.hidden_size),
    ).to(device=device)
    restore_head.load_state_dict(torch.load(restore_path, map_location=device))
    restore_head.eval()

    metrics, failed_cases, predictions = evaluate_restore(
        model=model,
        restore_head=restore_head,
        dataloader=dataloader,
        tokenizer=tokenizer,
        config=config,
        device=device,
        decode_sample_limit=effective_decode_limit,
    )
    metrics = {
        **metrics,
        "candidate_name": candidate_name,
        "checkpoint_dir": str(checkpoint_dir),
        "split": split,
        "preview_path": str(preview_path),
        "decode_sample_limit": effective_decode_limit,
        "batch_size": batch_size,
    }

    candidate_output_dir = output_dir / candidate_name
    candidate_output_dir.mkdir(parents=True, exist_ok=True)
    (candidate_output_dir / f"{split}_eval_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_jsonl(candidate_output_dir / f"{split}_failed_cases.jsonl", failed_cases)
    write_jsonl(candidate_output_dir / f"{split}_predictions.jsonl", predictions)
    write_eval_report(
        candidate_output_dir / f"{split}_eval_report.md",
        candidate_name=candidate_name,
        checkpoint_dir=checkpoint_dir,
        split=split,
        preview_path=preview_path,
        metrics=metrics,
    )

    del restore_head
    del model
    del base_model
    gc.collect()
    torch.cuda.empty_cache()
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Stage B restore checkpoints on a preview split.")
    parser.add_argument("--model-name-or-path", required=True)
    parser.add_argument("--preview-path", type=Path, default=DEFAULT_PREVIEW_PATH)
    parser.add_argument("--split", default="test")
    parser.add_argument("--candidate", action="append", required=True, type=parse_candidate)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument(
        "--decode-sample-limit",
        type=int,
        default=0,
        help="Number of rows to decode; 0 decodes the full split.",
    )
    parser.add_argument("--local-files-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("checkpoint evaluation requires a CUDA GPU")
    if args.batch_size < 1:
        raise ValueError("--batch-size must be >= 1")
    decode_sample_limit = None if args.decode_sample_limit == 0 else args.decode_sample_limit
    if decode_sample_limit is not None and decode_sample_limit < 1:
        raise ValueError("--decode-sample-limit must be 0 or >= 1")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    for candidate_name, checkpoint_dir in args.candidate:
        metrics = evaluate_candidate(
            candidate_name=candidate_name,
            checkpoint_dir=checkpoint_dir,
            model_name_or_path=args.model_name_or_path,
            preview_path=args.preview_path,
            split=args.split,
            batch_size=args.batch_size,
            decode_sample_limit=decode_sample_limit,
            output_dir=args.output_dir,
            local_files_only=args.local_files_only,
        )
        summary.append(metrics)
        print(json.dumps({"candidate": candidate_name, "metrics": metrics}, ensure_ascii=False, sort_keys=True))

    (args.output_dir / f"{args.split}_candidate_eval_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
