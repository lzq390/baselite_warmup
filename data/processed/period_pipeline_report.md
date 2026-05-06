# sliding period 生成与过滤报告

- 生成时间 UTC: `2026-05-06T07:22:20.476486+00:00`
- 输入文件: `\\wsl.localhost\Ubuntu\home\lzq390\gith\baselite_warmup\data\processed\unique_standardized_smiles.csv`
- period 候选输出: `\\wsl.localhost\Ubuntu\home\lzq390\gith\baselite_warmup\data\processed\periods_from_unique_standardized_smiles.csv`
- 过滤去重输出: `\\wsl.localhost\Ubuntu\home\lzq390\gith\baselite_warmup\data\processed\periods2_from_unique_standardized_smiles.csv`
- failed cases: `\\wsl.localhost\Ubuntu\home\lzq390\gith\baselite_warmup\data\processed\period_pipeline_failed_cases.jsonl`
- RDKit 版本: `2026.03.1`

## 功能说明

本流程按 `periods_construct.py -> dataset_filter.py` 的功能处理 `unique_standardized_smiles.csv`：

1. 对每个两连接点标准化 SMILES 构造三聚体。
2. 沿两个 `*` 之间的 shortest backbone path 滑动切分，生成 period candidates。
3. 对 period candidates 做 RDKit 解析、恰好两个 `*`、query atom 过滤和 canonical 去重。

## 关键风险

- attachment 左右角色仍沿用历史脚本的 RDKit atom index 规则，不等于生产级 canonical orientation。
- 三聚体连接仍按 single bond 构造，未推断真实 periodic bond order。
- backbone 使用两个 `*` 之间 shortest path，复杂环/支化结构可能不稳定。
- 本流程适合作为 sliding period candidate 生成，不等同于最终 periodic graph matcher。

## 统计

- 输入唯一标准化 SMILES 数: `11580`
- generation 通过数: `11580`
- generation 失败数: `0`
- period candidate 总行数: `62297`
- 含 source 去重前 unique period_smiles 数: `55060`
- filter prefilter 失败数: `0`
- filter RDKit/结构失败数: `0`
- filter 重复数: `7237`
- periods2 保留数: `55060`

## 每个输入生成 period 数分布

- `1` 个 period: `1811` 个输入
- `2` 个 period: `1421` 个输入
- `3` 个 period: `1485` 个输入
- `4` 个 period: `1548` 个输入
- `5` 个 period: `891` 个输入
- `6` 个 period: `1059` 个输入
- `7` 个 period: `674` 个输入
- `8` 个 period: `628` 个输入
- `9` 个 period: `382` 个输入
- `10` 个 period: `365` 个输入
- `11` 个 period: `254` 个输入
- `12` 个 period: `207` 个输入
- `13` 个 period: `151` 个输入
- `14` 个 period: `154` 个输入
- `15` 个 period: `137` 个输入
- `16` 个 period: `113` 个输入
- `17` 个 period: `80` 个输入
- `18` 个 period: `64` 个输入
- `19` 个 period: `32` 个输入
- `20` 个 period: `28` 个输入
- `21` 个 period: `19` 个输入
- `22` 个 period: `11` 个输入
- `23` 个 period: `13` 个输入
- `24` 个 period: `8` 个输入
- `25` 个 period: `9` 个输入
- `26` 个 period: `6` 个输入
- `27` 个 period: `4` 个输入
- `28` 个 period: `8` 个输入
- `29` 个 period: `4` 个输入
- `30` 个 period: `3` 个输入
- `31` 个 period: `2` 个输入
- `32` 个 period: `3` 个输入
- `33` 个 period: `3` 个输入
- `35` 个 period: `1` 个输入
- `36` 个 period: `1` 个输入
- `39` 个 period: `1` 个输入

## generation 失败原因


## filter 失败原因

- `duplicate`: `7237`

## 失败样本示例

