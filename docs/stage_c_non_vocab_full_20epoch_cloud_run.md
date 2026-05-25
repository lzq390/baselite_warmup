# Stage C Non-vocab 全量 20 epoch 云端运行说明

这个包用于执行一版更完整的 Stage C non-vocab 训练：

```text
text_view + repeat_unit_graph -> L_restore + L_align -> checkpoint/reload/eval
```

它沿用已经通过 smoke 验证的 Stage C 主链路，去掉 train/valid 样本上限，最多训练 20 个 epoch，并在每个 epoch 末保存可加载的模型组件快照和验证指标。当前配置启用了保守 early stopping：只在至少完成 10 个 epoch 后，才会根据 checkpoint validation loss 是否长期不再改善来提前停止。

## 训练范围

本轮启用：

- `L_restore`
- `L_align`
- Qwen2.5-7B Base LoRA
- 纯 PyTorch graph encoder
- 来自 `data/processed/repeat_unit_graphs.jsonl` 的 repeat-unit graph tensor 输入
- 每个 epoch 末的 checkpoint 快照和验证指标
- 基于 checkpoint validation loss 的 early stopping

本轮不启用：

- chat template
- 新增 special tokens
- fragment vocab
- fragment matcher
- `L_fragment_presence`
- `L_fragment_consistency`

这仍然是 Stage C non-vocab 路线。fragment-aware Stage D 应继续等待 fragment matcher 输出稳定后再启动。

## 包内容

上传清单在：

```text
packaging/stage_c_non_vocab_full_20epoch_files.txt
```

包内包含 Stage A template preview 数据集、repeat-unit graph JSONL、Stage C graph feature schema/audit 报告、训练脚本、测试、20epoch 配置和 tokenizer 文件。包内不包含 Qwen2.5-7B 模型权重、Hugging Face 缓存或历史训练输出。

注意：20epoch 上传包不包含 1epoch/3epoch/smoke 的训练配置、cloud-run 说明、打包清单或结果分析，避免云端误跑旧配置。脚本名 `train_stage_c_non_vocab_smoke.py` 是历史入口名，当前运行模式由 `configs/stage_c_non_vocab_full_20epoch_bf16.yaml` 决定。

## 服务器要求

- Linux + NVIDIA GPU。
- CUDA 版 PyTorch，版本需匹配服务器驱动/runtime。
- 单卡 bf16-capable GPU，显存至少 48 GB。
- 推荐：RTX 4090D 48GB；备选：L20 48GB、L40S 48GB、A100 80GB。
- 数据盘建议至少 160 GB，用于包、模型缓存、日志、checkpoint 和最终输出。
- 使用 `Qwen/Qwen2.5-7B` Base，不要用 Instruct checkpoint。

## 环境准备

建议把工作目录、venv、模型缓存和输出都放在数据盘。示例目录：

```text
/root/autodl-tmp/baselite_stage_c_full_20epoch/
  packages/
  work/
  venv/
  hf_cache/
  logs/
```

创建并激活环境：

```bash
python3 -m venv --system-site-packages /root/autodl-tmp/baselite_stage_c_full_20epoch/venv
source /root/autodl-tmp/baselite_stage_c_full_20epoch/venv/bin/activate
python -m pip install --upgrade pip
```

如果基础环境没有可用的 CUDA PyTorch，先按服务器 CUDA 版本安装。CUDA 12.1 示例：

```bash
pip install --index-url https://download.pytorch.org/whl/cu121 torch
```

安装其余依赖：

```bash
pip install -r requirements-stage-c.txt
```

设置 Hugging Face 缓存目录：

```bash
export HF_HOME=/root/autodl-tmp/baselite_stage_c_full_20epoch/hf_cache
export TRANSFORMERS_CACHE=/root/autodl-tmp/baselite_stage_c_full_20epoch/hf_cache/transformers
```

如果同一台服务器已经跑过 smoke，可以直接复用已有缓存，避免重新下载 Qwen2.5-7B：

```bash
export HF_HOME=/root/autodl-tmp/baselite_stage_c_smoke/hf_cache
export TRANSFORMERS_CACHE=/root/autodl-tmp/baselite_stage_c_smoke/hf_cache/transformers
```

如果直连 Hugging Face 不稳定，可以使用 smoke 阶段已验证过的镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

## 训练前检查

训练前先跑数据 join audit、环境检查和单元测试：

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

期望 audit 结果：

```text
dataset rows: 11580
graph rows: 11580
missing graph by record_id: 0
missing graph by canonical_hash: 0
canonical hash mismatches: 0
```

## 启动 20 epoch 全量训练

直接使用 Hugging Face model id：

```bash
python scripts/train_stage_c_non_vocab_smoke.py \
  --config configs/stage_c_non_vocab_full_20epoch_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --output-dir outputs/stage_c_non_vocab_full_20epoch
```

如果模型已经提前下载到本地目录：

```bash
python scripts/train_stage_c_non_vocab_smoke.py \
  --config configs/stage_c_non_vocab_full_20epoch_bf16.yaml \
  --model-name-or-path /data/models/Qwen2.5-7B \
  --output-dir outputs/stage_c_non_vocab_full_20epoch
```

当前配置要点：

```text
max_train_samples: null
max_valid_samples: null
max_epochs: 20
train rows per epoch: 9264
valid rows: 1158
per_device_train_batch_size: 2
gradient_accumulation_steps: 8
effective batch size: 16
estimated optimizer steps per epoch: 579
estimated optimizer steps at 20 epochs: 11580
quick eval every: 500 optimizer steps
epoch checkpoints: epoch_001 ... epoch_020
checkpoint eval: full 1158 valid rows, 128 decode samples, 512 retrieval samples
final eval: 1158 valid rows, 128 decode samples, 512 retrieval samples
early stopping: validation loss, min mode, min_epochs=10, patience=5, min_delta=0.001
```

`checkpoint_eval_samples: 0` 表示每个 epoch-end checkpoint 都跑完整 valid set，用于观察 20 epoch 的 validation loss / token accuracy 曲线；decode 和 retrieval 仍保留采样上限，避免每个 epoch 的生成评估过慢。

## 预期输出

```text
outputs/stage_c_non_vocab_full_20epoch/
  epoch_metrics.csv
  epoch_metrics.jsonl
  eval_metrics.json
  eval_report.md
  failed_cases.jsonl
  retrieval_predictions.jsonl
  lora_adapter/
  restore_head/
  graph_encoder/
  projectors/
  reload_smoke.json
  stage_c_non_vocab_full_20epoch_bf16.yaml
  tokenizer/
  training_config.json
  checkpoints/
    epoch_001/
      eval_metrics.json
      checkpoint_metadata.json
      lora_adapter/
      restore_head/
      graph_encoder/
      projectors/
    ...
```

最终输出目录中的 `reload_smoke.json` 应报告 `"status": "passed"`。

## 验收标准

这轮训练可认为工程上成功，需要满足：

- 所有 loss 均为有限值；
- `train_loss_decreased` 为 `true`；
- `reload_smoke.status == "passed"`；
- epoch checkpoint 存在，并包含验证指标；
- 每个 checkpoint 都能产出 restore/retrieval 指标；
- `epoch_metrics.csv` / `epoch_metrics.jsonl` 包含每个 epoch 的 loss、token accuracy、decode validity、retrieval top-k 和 early-stopping 状态；
- 最终输出 artifact 完整；
- `eval_metrics.json` 中存在 `completed_epochs` 和 early-stopping 相关字段；
- text-to-graph / graph-to-text top-k 可与本地保留的 smoke baseline 比较。

这仍不是最终 BaseLite checkpoint，只是 Stage C non-vocab 路线的第一版长训练结果。

## 曲线复盘建议

20 epoch 结果优先用 `epoch_metrics.csv` 观察：

- train 曲线：`checkpoint_epoch_train_loss_mean`
- valid 曲线：`loss`、`restore_loss`、`align_loss`、`token_accuracy`
- 结构有效性：`rdkit_validity`、`two_attachment_validity`、`canonical_match`
- 对齐质量：`text_to_graph_top1/top5`、`graph_to_text_top1/top5`

选 checkpoint 时优先看完整 valid loss 的最低点，再确认 token accuracy、decode validity 和 retrieval top-k 是否同步改善。最终目录保存的是最后一轮模型；如果 best epoch 更早，应使用 `checkpoints/epoch_xxx/` 中的组件作为候选 checkpoint。
