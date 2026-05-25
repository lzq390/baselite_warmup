# Stage C Non-vocab Smoke Cloud Run

This package is for the Stage C smoke run:

```text
text_view + repeat_unit_graph -> L_restore + L_align -> checkpoint/reload/eval
```

It is not a formal long-run checkpoint. The default config intentionally uses a
small training subset to verify the full Stage C path before spending GPU time
on the full dataset.

## Scope

Enabled:

- `L_restore`
- `L_align`
- Qwen2.5-7B Base LoRA
- pure PyTorch graph encoder
- graph tensor inputs from `data/processed/repeat_unit_graphs.jsonl`

Disabled:

- chat template
- new special tokens
- fragment vocab
- fragment matcher
- `L_fragment_presence`
- `L_fragment_consistency`

## Package Contents

Required files are listed in:

```text
packaging/stage_c_non_vocab_smoke_files.txt
```

The package includes the Stage A template preview dataset, the repeat-unit graph
JSONL, the Stage C graph feature schema/audit report, scripts, tests, config,
and the local Qwen tokenizer files. It does not include full Qwen2.5-7B model
weights, Hugging Face caches, or training outputs.

## Server Requirements

- Linux server with NVIDIA GPU.
- CUDA-enabled PyTorch installed for the server driver/runtime.
- bf16-capable GPU is expected because the config loads Qwen2.5-7B in bf16.
- Recommended free disk space: at least 80 GB for model cache, package, and run
  outputs.
- Use `Qwen/Qwen2.5-7B` Base, not an Instruct checkpoint.

## Environment Setup

Create and activate a fresh environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Install CUDA PyTorch using the command for the server. Example for CUDA 12.1:

```bash
pip install --index-url https://download.pytorch.org/whl/cu121 torch
```

Install the remaining dependencies:

```bash
pip install -r requirements-stage-c.txt
```

Optional cache placement:

```bash
export HF_HOME=/data/hf_cache
export TRANSFORMERS_CACHE=/data/hf_cache/transformers
```

If Hugging Face access requires authentication:

```bash
huggingface-cli login
```

## Optional Pre-download

Downloading before training makes failures easier to diagnose:

```bash
huggingface-cli download Qwen/Qwen2.5-7B \
  --local-dir /data/models/Qwen2.5-7B \
  --local-dir-use-symlinks False
```

Then use `/data/models/Qwen2.5-7B` as `--model-name-or-path`.

## Preflight

Verify the package data join and local unit tests:

```bash
python scripts/build_stage_c_non_vocab_dataset.py

python - <<'PY'
import torch
import transformers
import peft
import rdkit
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
print("gpu", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
print("transformers", transformers.__version__)
print("peft", peft.__version__)
print("rdkit", rdkit.__version__)
PY

python -m pytest \
  tests/test_stage_c_non_vocab_smoke.py \
  tests/test_train_stage_b_restore_smoke.py \
  tests/test_build_baselite_restore_template_preview.py \
  -q
```

Expected dataset audit:

```text
dataset rows: 11580
graph rows: 11580
missing graph by record_id: 0
missing graph by canonical_hash: 0
canonical hash mismatches: 0
```

## Smoke Run

Direct Hugging Face model ID:

```bash
python scripts/train_stage_c_non_vocab_smoke.py \
  --config configs/stage_c_non_vocab_smoke_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --output-dir outputs/stage_c_non_vocab_smoke
```

Local model directory:

```bash
python scripts/train_stage_c_non_vocab_smoke.py \
  --config configs/stage_c_non_vocab_smoke_bf16.yaml \
  --model-name-or-path /data/models/Qwen2.5-7B \
  --output-dir outputs/stage_c_non_vocab_smoke
```

The default smoke config uses:

```text
max_train_samples: 512
max_valid_samples: 128
max_epochs: 1
per_device_train_batch_size: 2
gradient_accumulation_steps: 8
```

This is about 32 optimizer steps.

## Expected Outputs

```text
outputs/stage_c_non_vocab_smoke/
  eval_metrics.json
  eval_report.md
  failed_cases.jsonl
  retrieval_predictions.jsonl
  lora_adapter/
  restore_head/
  graph_encoder/
  projectors/
  reload_smoke.json
  stage_c_non_vocab_smoke_bf16.yaml
  tokenizer/
  training_config.json
```

`reload_smoke.json` should report `"status": "passed"`.

The smoke acceptance bar is engineering health only: finite losses, computable
restore/retrieval metrics, complete artifact export, and successful reload. Do
not require canonical match or retrieval metrics to reach formal quality
thresholds.

## Full-data Follow-up

After the smoke package passes, run a full-data Stage C pass by setting the
sample caps to `null` in a separate config:

```yaml
data:
  max_train_samples: null
  max_valid_samples: null
```

With the current split and batch settings, a full 1-epoch run uses 9,264 train
rows and is about 579 optimizer steps. Start with 1 epoch; only consider 2-3
epochs after the first full pass shows useful restore and retrieval trends.
