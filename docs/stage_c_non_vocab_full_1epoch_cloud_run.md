# Stage C Non-vocab Full 1-epoch Cloud Run

This package is for the first full-data Stage C run:

```text
text_view + repeat_unit_graph -> L_restore + L_align -> checkpoint/reload/eval
```

It uses the same code path that passed the Stage C smoke run, but removes the
sample caps so the full train and valid splits are used.

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

This is still the non-vocab Stage C route. Fragment-aware Stage D should remain
blocked until fragment matcher outputs are stable.

## Package Contents

Required files are listed in:

```text
packaging/stage_c_non_vocab_full_1epoch_files.txt
```

The package includes the Stage A template preview dataset, repeat-unit graph
JSONL, Stage C graph feature schema/audit report, scripts, tests, config,
tokenizer files, and the Stage C smoke analysis report for baseline comparison.
It does not include Qwen2.5-7B model weights, Hugging Face caches, or previous
training outputs.

## Server Requirements

- Linux server with NVIDIA GPU.
- CUDA-enabled PyTorch installed for the server driver/runtime.
- bf16-capable GPU; RTX 4090D 48GB already passed the smoke run with ample
  memory headroom.
- Recommended free disk space: at least 120 GB on the data disk for package,
  model cache, logs, and outputs.
- Use `Qwen/Qwen2.5-7B` Base, not an Instruct checkpoint.

## Environment Setup

Use the data disk for the work directory, venv, model cache, and outputs. Example
layout:

```text
/root/autodl-tmp/baselite_stage_c_full/
  packages/
  work/
  venv/
  hf_cache/
  logs/
```

Create and activate a fresh environment:

```bash
python3 -m venv --system-site-packages /root/autodl-tmp/baselite_stage_c_full/venv
source /root/autodl-tmp/baselite_stage_c_full/venv/bin/activate
python -m pip install --upgrade pip
```

Install CUDA PyTorch using the command for the server if the base environment
does not already provide it. Example for CUDA 12.1:

```bash
pip install --index-url https://download.pytorch.org/whl/cu121 torch
```

Install the remaining dependencies:

```bash
pip install -r requirements-stage-c.txt
```

Cache placement:

```bash
export HF_HOME=/root/autodl-tmp/baselite_stage_c_full/hf_cache
export TRANSFORMERS_CACHE=/root/autodl-tmp/baselite_stage_c_full/hf_cache/transformers
```

If the same server already ran the smoke package, you can point `HF_HOME` to the
existing smoke cache to avoid downloading Qwen2.5-7B again:

```bash
export HF_HOME=/root/autodl-tmp/baselite_stage_c_smoke/hf_cache
export TRANSFORMERS_CACHE=/root/autodl-tmp/baselite_stage_c_smoke/hf_cache/transformers
```

If direct Hugging Face access is unavailable, use the mirror that worked for the
smoke run:

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

## Preflight

Run these before training:

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

## Full 1-epoch Run

Direct Hugging Face model ID:

```bash
python scripts/train_stage_c_non_vocab_smoke.py \
  --config configs/stage_c_non_vocab_full_1epoch_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --output-dir outputs/stage_c_non_vocab_full_1epoch
```

Local model directory:

```bash
python scripts/train_stage_c_non_vocab_smoke.py \
  --config configs/stage_c_non_vocab_full_1epoch_bf16.yaml \
  --model-name-or-path /data/models/Qwen2.5-7B \
  --output-dir outputs/stage_c_non_vocab_full_1epoch
```

The full config uses:

```text
max_train_samples: null
max_valid_samples: null
max_epochs: 1
train rows: 9264
valid rows: 1158
per_device_train_batch_size: 2
gradient_accumulation_steps: 8
effective batch size: 16
estimated optimizer steps: 579
eval_decode_samples: 128
eval_retrieval_samples: 512
```

## Expected Outputs

```text
outputs/stage_c_non_vocab_full_1epoch/
  eval_metrics.json
  eval_report.md
  failed_cases.jsonl
  retrieval_predictions.jsonl
  lora_adapter/
  restore_head/
  graph_encoder/
  projectors/
  reload_smoke.json
  stage_c_non_vocab_full_1epoch_bf16.yaml
  tokenizer/
  training_config.json
```

`reload_smoke.json` should report `"status": "passed"`.

## Acceptance Bar

This run is the first full-data non-vocab Stage C pass, not the final BaseLite
checkpoint. Treat it as successful if:

- all losses are finite;
- `train_loss_decreased` is `true`;
- `reload_smoke.status == "passed"`;
- restore and retrieval metrics are computable;
- output artifacts are complete;
- text-to-graph and graph-to-text top-k can be compared against the smoke
  baseline.

Do not require canonical match or retrieval top-k to reach production quality
after this single epoch.

## Suggested Post-run Analysis

After downloading outputs, generate an analysis report and compare it with the
smoke-run baseline described in `docs/stage_c_non_vocab_smoke_cloud_run.md`:

- train loss first/last window;
- restore token accuracy and decode validity;
- text-to-graph top1/top5;
- graph-to-text top1/top5;
- mean positive vs negative similarity;
- failure modes in `failed_cases.jsonl`;
- whether over-generation still dominates restore failures.

Only consider 2-3 epochs after this 1-epoch run shows useful restore or
retrieval trends.
