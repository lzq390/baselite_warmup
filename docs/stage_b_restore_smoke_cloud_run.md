# Stage B Restore-Only Cloud Run

This package is for the Stage B text-only restore smoke/baseline run. It trains
`L_restore` only.

It does not train `L_align`, does not load graph tensors, and does not use
fragment vocab or property labels.

## Package Contents

Required files:

```text
configs/stage_b_restore_smoke_bf16.yaml
data/baselite_smiles_v1/training_template_preview.jsonl
data/baselite_smiles_v1/training_template_stats.json
data/baselite_smiles_v1/training_template_report.md
data/baselite_smiles_v1/dataset_manifest.json
data/baselite_smiles_v1/train.jsonl
data/baselite_smiles_v1/valid.jsonl
data/baselite_smiles_v1/test.jsonl
models/qwen2.5-7b-tokenizer/
scripts/train_stage_b_restore_smoke.py
scripts/build_baselite_restore_template_preview.py
tests/test_train_stage_b_restore_smoke.py
tests/test_build_baselite_restore_template_preview.py
requirements-stage-b.txt
```

The full Qwen2.5-7B Base model weights are not bundled. Download them on the
server or point `--model-name-or-path` at an existing local model directory.

## Server Requirements

- Linux server with NVIDIA GPU.
- CUDA-enabled PyTorch installed for the server driver/runtime.
- bf16-capable GPU is expected because the current config and script use bf16.
- Recommended free disk space: at least 60 GB for model cache, package, and run
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
pip install -r requirements-stage-b.txt
```

Optional but recommended cache placement:

```bash
export HF_HOME=/data/hf_cache
export TRANSFORMERS_CACHE=/data/hf_cache/transformers
```

If Hugging Face access requires authentication:

```bash
huggingface-cli login
```

## Optional Pre-Download

Downloading before training makes failures easier to diagnose:

```bash
huggingface-cli download Qwen/Qwen2.5-7B \
  --local-dir /data/models/Qwen2.5-7B \
  --local-dir-use-symlinks False
```

Then use `/data/models/Qwen2.5-7B` as `--model-name-or-path`.

## Preflight

Run these checks before training:

```bash
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

python -m pytest tests/test_train_stage_b_restore_smoke.py tests/test_build_baselite_restore_template_preview.py -q
```

## Run

Direct Hugging Face model ID:

```bash
python scripts/train_stage_b_restore_smoke.py \
  --config configs/stage_b_restore_smoke_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --output-dir outputs/stage_b_restore_smoke
```

Local model directory:

```bash
python scripts/train_stage_b_restore_smoke.py \
  --config configs/stage_b_restore_smoke_bf16.yaml \
  --model-name-or-path /data/models/Qwen2.5-7B \
  --output-dir outputs/stage_b_restore_smoke
```

## Expected Outputs

```text
outputs/stage_b_restore_smoke/
  eval_metrics.json
  eval_report.md
  failed_cases.jsonl
  lora_adapter/
  reload_smoke.json
  restore_head/
  stage_b_restore_smoke_bf16.yaml
  tokenizer/
  training_config.json
```

`reload_smoke.json` should report `"status": "passed"`.

## Scope Check

This run is only a restore-only smoke/baseline checkpoint. It is not the formal
BaseLite `L_restore + L_align` warmup checkpoint.
