# BaseLite Stage A Restore-Only 模板预览报告

- 生成时间 UTC: `2026-05-20T00:45:50.067255+00:00`
- tokenizer 路径: `/home/lzq390/gith/baselite_warmup/models/qwen2.5-7b-tokenizer`
- tokenizer class: `Qwen2Tokenizer`
- vocab size: `151643`
- eos token: `<|endoftext|>` / `151643`
- pad token: `<|endoftext|>` / `151643`
- 总记录数: `11580`

## Stage A 口径

- 本阶段是 restore-only template preview，不训练模型。
- `text_view_1_strategy` 固定为 `identity`，不做扰动。
- 不生成 `text_view_2`。
- 不接 graph tensor。
- 不接 fragment vocab / fragment labels。
- target 单独 tokenize 为 `restore_labels`，不拼入 `input_text_view1`。

## 模板

```text
<polymer_view_smiles>
{text_view_1}
</polymer_view_smiles>
```

restore target:

```text
{canonical_text_target}<|endoftext|>
```

## 长度统计

| split | count | view p50 | view p90 | view p95 | view p99 | view max | restore p50 | restore p90 | restore p95 | restore p99 | restore max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 9264 | 45 | 85 | 96 | 118 | 235 | 32 | 71 | 82 | 104 | 221 |
| valid | 1158 | 46 | 84 | 95 | 123 | 166 | 32 | 70 | 81 | 109 | 152 |
| test | 1158 | 48 | 85 | 98 | 120 | 381 | 34 | 71 | 84 | 106 | 367 |

## 质量检查

- view template round-trip failures: `0`
- restore label round-trip failures: `0`
- view length overflow: `0`
- restore label length overflow: `0`
- mask failures: `0`

## 输出文件

- preview JSONL: `/home/lzq390/gith/baselite_warmup/data/baselite_smiles_v1/training_template_preview.jsonl`
- stats JSON: `/home/lzq390/gith/baselite_warmup/data/baselite_smiles_v1/training_template_stats.json`
- report MD: `/home/lzq390/gith/baselite_warmup/data/baselite_smiles_v1/training_template_report.md`
