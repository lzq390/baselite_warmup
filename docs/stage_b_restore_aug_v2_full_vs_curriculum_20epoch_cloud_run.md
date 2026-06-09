# Stage B Restore v2 Full vs Curriculum 20 Epoch 云端运行说明

本轮用于对照两种 Stage B restore-only 训练策略：

```text
augmented_smiles_view -> L_restore -> canonical_smiles
```

两组实验都使用 `restore_aug_v2` 数据，都只训练 Qwen2.5-7B Base LoRA 与 restore cross-attention head，不接 graph tensor，不训练 `L_align`，也不启用 fragment vocab 或 fragment labels。

## 数据口径

主训练 preview：

```text
data/baselite_smiles_aug_v2/training_template_preview.jsonl
```

行数：

```text
train: 46320 = 9264 records * 5 views
valid: 5790  = 1158 records * 5 views
test:  5790  = 1158 records * 5 views
total: 57900
```

五个 view：

```text
identity
rdkit_random_smiles
direction_flip
attachment_rooted_smiles
light_denoise
```

robustness eval preview：

```text
data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl
```

行数：

```text
valid: 4632 = 1158 records * 4 views
test:  4632 = 1158 records * 4 views
total: 9264
```

robustness eval 使用四个非 identity view：

```text
rdkit_random_smiles
direction_flip
attachment_rooted_smiles
light_denoise
```

## 启动 full/equal-mixture

```bash
python scripts/train_stage_b_restore_full.py \
  --config configs/stage_b_restore_aug_v2_full_20epoch_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --eval-preview-path data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl \
  --eval-output-prefix robustness
```

输出目录：

```text
outputs/stage_b_restore_aug_v2_full_20epoch
```

## 启动 curriculum

```bash
python scripts/train_stage_b_restore_curriculum.py \
  --config configs/stage_b_restore_aug_v2_curriculum_full_20epoch_bf16.yaml \
  --model-name-or-path Qwen/Qwen2.5-7B \
  --eval-preview-path data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl \
  --eval-output-prefix robustness
```

输出目录：

```text
outputs/stage_b_restore_aug_v2_curriculum_full_20epoch
```

## 关键配置

两组配置都使用：

```text
max_epochs: 20
checkpoint_eval_samples: 0
checkpoint_eval_decode_samples: 0
eval_decode_samples: 0
formal_eval_full_decode: true
early_stopping_enabled: true
early_stopping_monitor_only: true
```

`formal_eval_full_decode: true` 表示正式 checkpoint/final/robustness 生成指标都按数据集长度 full decode，不使用旧配置中的 128 条采样口径。quick eval 仍保留轻量采样，只用于训练中观察趋势。

正式 decode 口径：

```text
epoch checkpoint valid decode: 5790
final valid decode: 5790
final test decode: 5790
robustness valid decode: 4632
robustness test decode: 4632
```

early stopping 只做 monitor：会记录 best checkpoint、wait 和 `would_stop_training`，但不会提前中断 20 epoch 训练。

## 验收标准

- 两组都完成 20 epoch；
- `eval_metrics.json` 中 `early_stopped` 为 `false`；
- `eval_metrics.json` 中 `formal_eval_full_decode` 为 `true`；
- epoch checkpoint 的 `decoded_sample_count` 为 `5790`；
- final valid/test 的 `decoded_sample_count` 为 `5790`；
- robustness valid/test 的 `decoded_sample_count` 为 `4632`；
- `reload_smoke.status == "passed"`；
- 输出包含 LoRA adapter、restore head、tokenizer、epoch metrics、quick eval metrics、checkpoint 目录和配置快照。
