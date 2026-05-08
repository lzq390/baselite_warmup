# Qwen2.5-7B tokenizer 统计报告

- tokenizer 路径: `/home/lzq390/gith/baselite_warmup/models/qwen2.5-7b-tokenizer`
- vocab size: `151665`
- is_fast: `True`
- pad token: `<|endoftext|>`
- eos token: `<|endoftext|>`
- unk token: `None`
- corpus 文件: `/home/lzq390/gith/baselite_warmup/data/baselite_smiles_v1/tokenizer_corpus.txt`

## 结论

- train/valid/test 总 round-trip 失败数: `0`
- raw SMILES 推荐 `max_seq_len`: `512`
- 本统计只针对 raw `canonical_smiles`，尚未把训练 prompt 模板拼接进去。

## 各 split 长度统计

| split | count | token p50 | token p90 | token p95 | token p99 | token max | char max | 推荐 max_seq_len |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 9264 | 31 | 70 | 81 | 103 | 220 | 314 | 256 |
| valid | 1158 | 31 | 69 | 80 | 108 | 151 | 220 | 256 |
| test | 1158 | 33 | 70 | 83 | 105 | 366 | 475 | 512 |

## 特殊字符覆盖

### train
- `%`: `101`
- `*`: `9264`
- `/`: `547`
- `[`: `759`
- `\\`: `84`
- `]`: `759`

### valid
- `%`: `12`
- `*`: `1158`
- `/`: `67`
- `[`: `115`
- `\\`: `8`
- `]`: `115`

### test
- `%`: `11`
- `*`: `1158`
- `/`: `66`
- `[`: `91`
- `\\`: `9`
- `]`: `91`

## 最长样本

- train: `ru_010431`，token length `220`，char length `314`
- valid: `ru_010421`，token length `151`，char length `220`
- test: `ru_010959`，token length `366`，char length `475`
