# Stage B Restore 增强全量 20 epoch 云端运行说明

这个包用于执行 Stage B restore-only 的增强全量训练：

```text
augmented_smiles_view -> L_restore -> canonical_smiles
```

它使用 Stage B full 训练入口，训练数据切换到 `restore_aug_v1` 增强模板。训练目标仍然只优化 `L_restore`，不接 graph tensor，不训练 `L_align`，也不启用 fragment vocab 或 fragment labels。

## 训练范围

本轮启用：

- Qwen2.5-7B Base LoRA
- restore cross-attention head
- Stage B train 四视图增强数据
- identity valid 主验证指标
- 训练后 robustness valid/test 扰动恢复评估

本轮不启用：

- chat template
- 新增 special tokens
- graph tensor
- `L_align`
- fragment vocab
- fragment matcher
- `L_fragment_presence`
- `L_fragment_consistency`

## 包内容

上传清单在：

```text
packaging/stage_b_restore_aug_full_20epoch_files.txt
```

包内包含增强 Stage B preview、robustness eval preview、`train_stage_b_restore_full.py` 训练脚本、测试、20epoch 配置和 tokenizer 文件。包内不包含 Qwen2.5-7B 模型权重、Hugging Face 缓存或历史训练输出。

注意：20epoch 上传包不包含 smoke 训练配置或 smoke cloud-run 说明，避免云端误跑旧配置。

## 数据口径

主训练 preview：

```text
data/baselite_smiles_aug_v1/training_template_preview.jsonl
```

行数：

```text
train: 37056 = 9264 records * 4 views
valid: 1158  = identity only
test:  1158  = identity only
total: 39372
```

train 每个 record 包含四个 view：

```text
identity
rdkit_random_smiles
attachment_rooted_smiles
light_denoise
```

训练后 robustness eval preview：

```text
data/baselite_smiles_aug_v1/robustness_eval_preview.jsonl
```

行数：

```text
valid: 2316 = 1158 records * 2 views
test:  2316 = 1158 records * 2 views
total: 4632
```

robustness eval 每个 valid/test record 包含两个 view：

```text
rdkit_random_smiles
light_denoise
```

## 服务器要求

- Linux + NVIDIA GPU。
- CUDA 版 PyTorch，版本需匹配服务器驱动/runtime。
- 单卡 bf16-capable GPU。
- 推荐显存至少 48 GB。
- 数据盘建议至少 120 GB，用于包、模型缓存、日志和最终输出。
- 使用 `Qwen/Qwen2.5-7B` Base，不要用 Instruct checkpoint。

## 环境准备

建议把工作目录、venv、模型缓存和输出都放在数据盘。示例目录：

```text
/root/autodl-tmp/baselite_stage_b_restore_aug_full_20epoch/
  packages/
  work/
  venv/
  hf_cache/
  logs/
```

创建并激活环境：

```bash
python3 -m venv --system-site-packages /root/autodl-tmp/baselite_stage_b_restore_aug_full_20epoch/venv
source /root/autodl-tmp/baselite_stage_b_restore_aug_full_20epoch/venv/bin/activate
python -m pip install --upgrade pip
```

如果基础环境没有可用的 CUDA PyTorch，先按服务器 CUDA 版本安装。CUDA 12.1 示例：

```bash
pip install --index-url https://download.pytorch.org/whl/cu121 torch
```

安装其余依赖：

```bash
pip install -r requirements-stage-b.txt
```

设置 Hugging Face 缓存目录：

```bash
export HF_HOME=/root/autodl-tmp/baselite_stage_b_restore_aug_full_20epoch/hf_cache
export TRANSFORMERS_CACHE=/root/autodl-tmp/baselite_stage_b_restore_aug_full_20epoch/hf_cache/transformers
```

如果直连 Hugging Face 不稳定，可以使用已验证过的镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

## 训练前检查

训练前先跑数据、环境和单元测试：

```bash
python scripts/build_baselite_restore_template_preview.py \
  --augmentation-policy restore_aug_v1 \
  --output-dir data/baselite_smiles_aug_v1 \
  --summary

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
  tests/test_train_stage_b_restore_smoke.py \
  tests/test_build_baselite_restore_template_preview.py \
  -q
```

期望数据检查结果：

```text
training train rows: 37056
training valid rows: 1158
training test rows: 1158
augmentation_failures: 0
view/restore round-trip failures: 0
view/restore length overflow: 0
```

## 启动 20 epoch 全量训练

直接使用 Hugging Face model id：

```bash
python scripts/train_stage_b_restore_full.py \
  --config configs/stage_b_restore_aug_full_20epoch_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --output-dir outputs/stage_b_restore_aug_full_20epoch \
  --eval-preview-path data/baselite_smiles_aug_v1/robustness_eval_preview.jsonl \
  --eval-output-prefix robustness
```

如果模型已经提前下载到本地目录：

```bash
python scripts/train_stage_b_restore_full.py \
  --config configs/stage_b_restore_aug_full_20epoch_bf16.yaml \
  --model-name-or-path /data/models/Qwen2.5-7B \
  --output-dir outputs/stage_b_restore_aug_full_20epoch \
  --eval-preview-path data/baselite_smiles_aug_v1/robustness_eval_preview.jsonl \
  --eval-output-prefix robustness
```

当前配置要点：

```text
max_epochs: 20
train rows per epoch: 37056
valid rows: 1158
per_device_train_batch_size: 1
gradient_accumulation_steps: 16
effective batch size: 16
estimated optimizer steps per epoch: 2316
estimated optimizer steps at 20 epochs: 46320
quick eval every: 1000 optimizer steps
quick eval samples: 256 rows, 32 decode samples
epoch checkpoint eval: full valid rows, 128 decode samples
early stopping: enabled after min 10 epochs, patience 5, metric loss/min
final identity eval: 1158 valid rows + 1158 test rows, 128 decode samples per split
robustness eval: valid/test, 128 decode samples per split
```

当前 Stage B full 脚本会保存 epoch checkpoint、epoch metrics、quick eval metrics、最终 LoRA adapter、restore head、tokenizer、主 identity valid/test 指标、robustness valid/test 指标和 reload smoke 结果。

## 预期输出

```text
outputs/stage_b_restore_aug_full_20epoch/
  eval_metrics.json
  eval_report.md
  failed_cases.jsonl
  predictions.jsonl
  epoch_metrics.csv
  epoch_metrics.jsonl
  quick_eval_metrics.jsonl
  identity_test_eval_metrics.json
  identity_test_failed_cases.jsonl
  identity_test_predictions.jsonl
  identity_test_eval_report.md
  robustness_valid_eval_metrics.json
  robustness_valid_failed_cases.jsonl
  robustness_valid_predictions.jsonl
  robustness_valid_eval_report.md
  robustness_test_eval_metrics.json
  robustness_test_failed_cases.jsonl
  robustness_test_predictions.jsonl
  robustness_test_eval_report.md
  checkpoints/
    epoch_001/
    ...
  lora_adapter/
  reload_smoke.json
  restore_head/
  stage_b_restore_aug_full_20epoch_bf16.yaml
  tokenizer/
  training_config.json
```

最终输出目录中的 `reload_smoke.json` 应报告 `"status": "passed"`。

## 验收标准

这轮训练可认为工程上成功，需要满足：

- 所有 loss 均为有限值；
- `train_loss_decreased` 为 `true`；
- `reload_smoke.status == "passed"`；
- 主 identity valid 指标正常写入 `eval_metrics.json`；
- 主 identity test 指标正常写入 `identity_test_eval_metrics.json`；
- robustness valid/test 指标正常写入 `robustness_*_eval_metrics.json`；
- `epoch_metrics.csv/jsonl`、`quick_eval_metrics.jsonl` 和 `checkpoints/epoch_*` 正常写入；
- `failed_cases.jsonl`、`predictions.jsonl` 和 robustness predictions 可用于后续错误分析；
- 输出 artifact 完整，包含 LoRA adapter、restore head、tokenizer 和配置快照。

## 结果复盘建议

优先比较：

- 主 valid：`loss`、`token_accuracy`、`exact_string_match`、`canonical_match`
- 结构有效性：`rdkit_validity`、`two_attachment_validity`
- robustness valid/test：同一组指标在扰动输入下的下降幅度
- failed cases：重点看 `light_denoise` 是否出现可恢复但未恢复的局部错误

这仍不是最终 BaseLite checkpoint，只是 Stage B restore-only 增强恢复能力训练结果。
