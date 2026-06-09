# Stage B / Stage C Aug v2 Full vs Curriculum 20 Epoch 云端运行说明

本轮用于建立四组同口径实验：

```text
Stage B full        restore-only, equal-mixture aug_v2
Stage B curriculum  restore-only, curriculum aug_v2
Stage C full        restore + graph + align, equal-mixture aug_v2
Stage C curriculum  restore + graph + align, curriculum aug_v2
```

跨 Stage 主比较只使用 restore 指标。Stage C 的 `align_loss`、retrieval top-k 和 graph 相关指标用于分析多任务训练效果，不直接和 Stage B restore-only 横比。

## 数据与评估口径

四组都使用：

```text
data/baselite_smiles_aug_v2/training_template_preview.jsonl
```

行数：

```text
train: 46320 = 9264 records * 5 views
valid: 5790  = 1158 records * 5 views
test:  5790  = 1158 records * 5 views
```

五个训练/eval view：

```text
identity
rdkit_random_smiles
direction_flip
attachment_rooted_smiles
light_denoise
```

robustness eval 使用：

```text
data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl
```

valid/test 各 `4632 = 1158 records * 4 non-identity views`，正式 restore decode 全量跑。

Stage C 的正式 retrieval eval 对 `record_id` 去重：valid/test 各 `1158` 个 graph identity，避免同一 graph 的五个 text view 互相干扰 top-k。

## 启动命令

Stage B full：

```bash
python scripts/train_stage_b_restore_full.py \
  --config configs/stage_b_restore_aug_v2_full_20epoch_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --eval-preview-path data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl \
  --eval-output-prefix robustness
```

Stage B curriculum：

```bash
python scripts/train_stage_b_restore_curriculum.py \
  --config configs/stage_b_restore_aug_v2_curriculum_full_20epoch_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --eval-preview-path data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl \
  --eval-output-prefix robustness
```

Stage C full：

```bash
python scripts/train_stage_c_non_vocab_full.py \
  --config configs/stage_c_non_vocab_aug_v2_full_20epoch_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --eval-preview-path data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl \
  --eval-output-prefix robustness
```

Stage C curriculum：

```bash
python scripts/train_stage_c_non_vocab_curriculum.py \
  --config configs/stage_c_non_vocab_aug_v2_curriculum_full_20epoch_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --eval-preview-path data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl \
  --eval-output-prefix robustness
```

## 对齐配置

四组用于比较的关键项保持一致；其中 Stage B 保持 20 epoch，Stage C 两种策略改为 30 epoch：

```text
Stage B max_epochs: 20
Stage C max_epochs: 30
effective batch size: 16
seed: 42
LoRA target/rank/alpha/dropout: identical
restore head config: identical
learning_rate_lora: 1.0e-4
learning_rate_restore_head: 5.0e-5
checkpoint_at_epoch_end: true
checkpoint_every_steps: 0
early_stopping_enabled: true
early_stopping_monitor_only: true
formal_eval_full_decode: true
```

Stage C 额外启用：

```text
graph encoder/projectors optimizer groups
L_restore + 0.2 * L_align
early_stopping_metric: restore_loss
formal_eval_dedup_retrieval: true
```

Stage C 的 eval/checkpoint metrics 会同时记录：

```text
restore_loss
align_loss
weighted_align_loss = 0.2 * align_loss
align_to_restore_ratio = weighted_align_loss / restore_loss
```

## 主要比较指标

用于 Stage B vs Stage C 横比：

```text
restore_loss
canonical_match
exact_string_match
rdkit_validity
two_attachment_validity
per-strategy restore aggregates
robustness canonical_match / validity by strategy
```

不用于 Stage B vs Stage C 直接横比：

```text
loss
align_loss
weighted_align_loss
align_to_restore_ratio
text_to_graph_top1/top5
graph_to_text_top1/top5
```

`loss` 在 Stage B 是 restore-only loss，在 Stage C 是 `L_restore + 0.2 * L_align`，只能做 stage 内趋势观察。
Stage C monitor-only checkpoint 记录使用 `restore_loss`，避免 best-checkpoint 元信息被 align loss 带偏；Stage B/Stage C 主横比仍以 final checkpoint 的 restore 指标为准。

## Restore 产物

四组都会保存完整 restore decode 逐样本输出：

```text
predictions.jsonl
failed_cases.jsonl
all_view_test_predictions.jsonl
robustness_valid_predictions.jsonl
robustness_test_predictions.jsonl
```

Stage C 额外保存 retrieval 输出：

```text
retrieval_predictions.jsonl
all_view_test_retrieval_predictions.jsonl
```

## 验收标准

- Stage B 两组完成 20 epoch，Stage C 两组完成 30 epoch，`early_stopped` 为 `false`。
- 四组正式 valid/test `decoded_sample_count` 为 `5790`。
- 四组 robustness valid/test `decoded_sample_count` 为 `4632`。
- Stage C 正式 valid/test `retrieval_sample_count` 为 `1158`。
- epoch checkpoint 中记录 `formal_eval_full_decode: true`。
- Stage C checkpoint/final 中记录 `formal_eval_dedup_retrieval: true`。
- reload check 通过。
