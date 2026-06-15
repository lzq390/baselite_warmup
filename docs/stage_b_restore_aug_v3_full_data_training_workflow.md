# Stage B Restore Aug v3 Full-data 训练流程

本文档记录 OMG v3 百万级数据进入 Stage B restore-only warmup 的完整流程。v3 数据用于大规模预训练/热身，不直接替代 curated v2/v1 Stage B；正式结论需要同时看 OMG v3 分布内 full-decode 和 curated v2 迁移评估。

## 目标与范围

本流程训练：

```text
OMG v3 five-view augmented_smiles_view -> L_restore -> canonical_smiles
```

启用：

- Qwen2.5-7B Base LoRA
- restore cross-attention head
- `restore_aug_v3` 五视图模板
- Stage B restore-only loss
- 训练后 OMG v3 test full-decode 与 curated v2 test full-decode

不启用：

- chat template
- 新增 special tokens
- graph tensor 训练
- `L_align`
- fragment vocab / matcher / fragment labels

注意：v3 模板行数很大，当前已验证的训练配置是 full-data 1 epoch warmup。更长 epoch 需要重新评估时间和 GPU 成本，不建议直接照 v2 的 20 epoch 口径套用。

## 数据口径

基础数据：

```text
data/baselite_smiles_v3/
  train.jsonl  800,000 records
  valid.jsonl  100,000 records
  test.jsonl   100,000 records
```

训练模板：

```text
data/baselite_smiles_aug_v3/training_template_preview.jsonl
```

行数：

```text
train: 4,000,000 = 800,000 records * 5 views
valid:   500,000 = 100,000 records * 5 views
test:    500,000 = 100,000 records * 5 views
total: 5,000,000
```

五个 view：

```text
identity
rdkit_random_smiles
direction_flip
attachment_rooted_smiles
light_denoise
```

graph sidecar：

```text
data/processed/omg_repeat_unit_graphs_v3.jsonl
```

Stage B restore-only 训练脚本只消费 `training_template_preview.jsonl`；graph sidecar 当前用于 Stage C/graph audit 和后续 join 记录，不进入 Stage B loss。

## 大文件处理

以下文件不进入普通 Git，需要作为外部 artifact 保留和传输：

```text
data/baselite_smiles_v3/train.jsonl
data/baselite_smiles_v3/valid.jsonl
data/baselite_smiles_v3/test.jsonl
data/baselite_smiles_aug_v3/training_template_preview.jsonl
data/baselite_smiles_aug_v3/distinct_view_audit.jsonl
data/processed/omg_repeat_unit_graphs_v3.jsonl
reports/**/*predictions.jsonl
reports/**/*failed_cases.jsonl
```

Git 中只保留 manifest、stats、report、训练脚本、配置和轻量 metrics。云端训练前必须确认大文件已经单独同步到相同相对路径。

## 本地/构建机生成流程

从 OMG 原始 CSV 生成 v3 dataset：

```bash
python scripts/build_omg_baselite_v3_dataset.py \
  --input /path/to/OMG_polymers.csv \
  --summary
```

生成 repeat-unit graph sidecar 与 Stage C audit：

```bash
python scripts/build_omg_repeat_unit_graphs_v3.py \
  --summary
```

生成 Stage B v3 五视图 restore 模板：

```bash
python scripts/build_stage_b_restore_v3_template.py \
  --summary
```

期望关键检查：

```text
dataset rows: 1,000,000
split: train 800,000 / valid 100,000 / test 100,000
canonical_hash leakage: 0
graph_hash leakage: 0
template rows: 5,000,000
strategy counts: each strategy 1,000,000
augmentation failures: 0
input-label conflicts: 0
view/restore roundtrip failures: 0
view/restore length overflow: 0
```

## 云端环境准备

建议目录：

```text
/root/autodl-tmp/baselite_omg_v3_stageb/
  packages/
  work/
  venv/
  hf_cache/
  logs/
```

环境：

```bash
python3 -m venv --system-site-packages /root/autodl-tmp/baselite_omg_v3_stageb/venv
source /root/autodl-tmp/baselite_omg_v3_stageb/venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-stage-b.txt

export HF_HOME=/root/autodl-tmp/baselite_omg_v3_stageb/hf_cache
export TRANSFORMERS_CACHE=/root/autodl-tmp/baselite_omg_v3_stageb/hf_cache/transformers
```

如 Hugging Face 直连不稳定：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

训练前检查：

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

python -m py_compile \
  scripts/omg_v3_common.py \
  scripts/build_omg_baselite_v3_dataset.py \
  scripts/build_omg_repeat_unit_graphs_v3.py \
  scripts/build_stage_b_restore_v3_template.py \
  scripts/train_stage_b_restore_full.py \
  scripts/evaluate_stage_b_restore_checkpoint.py
```

如果云端有 `pytest`：

```bash
python -m pytest tests/test_omg_v3_builders.py tests/test_train_stage_b_restore_smoke.py -q
```

## 启动 v3 full-data 1 epoch warmup

直接使用 Hugging Face model id：

```bash
python scripts/train_stage_b_restore_full.py \
  --config configs/stage_b_restore_aug_v3_full_1epoch_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --output-dir outputs/stage_b_restore_aug_v3_full_1epoch
```

如果模型已经提前下载到本地：

```bash
python scripts/train_stage_b_restore_full.py \
  --config configs/stage_b_restore_aug_v3_full_1epoch_bf16.yaml \
  --model-name-or-path /data/models/Qwen2.5-7B \
  --output-dir outputs/stage_b_restore_aug_v3_full_1epoch
```

当前配置要点：

```text
max_epochs: 1
train rows: 4,000,000
valid rows: 500,000
test rows: 500,000
per_device_train_batch_size: 8
gradient_accumulation_steps: 2
effective batch size: 16
estimated optimizer steps: 250,000
quick eval every: 5,000 optimizer steps
quick eval samples: 256 rows, 32 decode samples
checkpoint eval samples: 10,000 rows, 128 decode samples
final eval decode samples: 128
formal_eval_full_decode: false
early stopping: disabled
```

不建议在训练过程中打开 `formal_eval_full_decode: true`：v3 valid/test 各 500,000 行，逐 epoch 全量 decode 成本很高。正式 full-decode 应在选定 checkpoint 后单独补跑。

## 训练产物验收

期望输出：

```text
outputs/stage_b_restore_aug_v3_full_1epoch/
  eval_metrics.json
  eval_report.md
  identity_test_eval_metrics.json
  identity_test_eval_report.md
  epoch_metrics.csv
  epoch_metrics.jsonl
  quick_eval_metrics.jsonl
  checkpoints/epoch_001/
  lora_adapter/
  restore_head/
  tokenizer/
  training_config.json
  reload_smoke.json
```

验收标准：

```text
completed_epochs: 1
optimizer_steps: 250,000
train_sample_count: 4,000,000
valid_sample_count: 500,000
test_sample_count: 500,000
reload_smoke.status: passed
formal_eval_full_decode: false
```

生成训练报告：

```bash
python scripts/build_stage_b_v3_full_1epoch_report.py \
  --artifact-dir reports/stage_b_restore_aug_v3_full_1epoch_artifacts_remote \
  --template-stats data/baselite_smiles_aug_v3/training_template_stats.json \
  --dataset-manifest data/baselite_smiles_v3/dataset_manifest.json \
  --output reports/stage_b_restore_aug_v3_full_1epoch_report.html
```

## 选定 checkpoint 后 full-decode 评估

OMG v3 test full-decode：

```bash
python scripts/evaluate_stage_b_restore_checkpoint.py \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --preview-path data/baselite_smiles_aug_v3/training_template_preview.jsonl \
  --split test \
  --candidate v3_epoch001=outputs/stage_b_restore_aug_v3_full_1epoch/checkpoints/epoch_001 \
  --output-dir reports/stage_b_restore_aug_v3_full_decode_eval_remote/v3_test \
  --batch-size 16 \
  --decode-sample-limit 0
```

curated v2 test 迁移评估：

```bash
python scripts/evaluate_stage_b_restore_checkpoint.py \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --preview-path data/baselite_smiles_aug_v2/training_template_preview.jsonl \
  --split test \
  --candidate v3_epoch001=outputs/stage_b_restore_aug_v3_full_1epoch/checkpoints/epoch_001 \
  --output-dir reports/stage_b_restore_aug_v3_full_decode_eval_remote/v2_test \
  --batch-size 16 \
  --decode-sample-limit 0
```

生成 full-decode 对比报告：

```bash
python scripts/build_stage_b_v3_full_decode_eval_html_report.py \
  --input-dir reports/stage_b_restore_aug_v3_full_decode_eval_remote \
  --output reports/stage_b_restore_aug_v3_full_decode_eval_report.html
```

当前报告脚本需要本地存在 `test_predictions.jsonl`；这些文件被 `.gitignore` 忽略，不随 Git 提交分发。若只保留轻量 metrics，需要先把 prediction 明细从外部 artifact 拉回，或后续改造报告脚本读取聚合 analysis JSON。

## 已知结果口径

当前已完成的 v3 full-data 1 epoch 结果：

```text
V3 OMG test full-decode:
  rows decoded: 500,000
  canonical_match: 93.99%
  RDKit validity: 98.57%
  two_attachment_validity: 98.54%

V2 curated test full-decode:
  rows decoded: 5,790
  canonical_match: 17.65%
  RDKit validity: 44.47%
  two_attachment_validity: 42.56%
```

解释：

- v3 checkpoint 在 OMG v3 分布内表现强，适合作为大规模 warmup。
- curated v2 迁移明显不足，不能直接作为最终 Stage B restore 模型。
- 下一步应在支持 checkpoint 初始化后，继续用 curated v2/v1 数据 fine-tune，并保持 v3/v2 双口径评估。

## 后续补强项

- `build_stage_b_restore_v3_template.py` 当前只记录 graph sidecar 路径，不读取 graph JSONL。若 Stage C 依赖该 sidecar，应单独跑 `build_omg_repeat_unit_graphs_v3.py --summary` 并保留 join report。
- `build_stage_b_v3_full_decode_eval_html_report.py` 当前依赖被忽略的 prediction JSONL。建议后续支持从已提交的 `stage_b_restore_aug_v3_full_decode_eval_analysis.json` 生成轻量报告。
- 当前 `train_stage_b_restore_full.py` 不支持从已有 LoRA/restore_head checkpoint 初始化继续训练。若要执行“OMG v3 warmup -> curated v2 fine-tune”，需要先补 checkpoint 初始化入口。
