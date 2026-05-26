# fragment_vocab_v1 生产核心字段说明

本文档说明 `fragment_vocab_v1.0.jsonl` 的生产核心字段。

生产核心词表只保留匹配、归属、去重和冲突处理必需字段。统计、示例、审核和下游模型配置应放入辅助文件。

## 核心字段

| 字段 | 类型 | 含义 | 是否必需 | 说明 |
|---|---:|---|---|---|
| `fragment_id` | string | fragment 的稳定唯一 ID | 必需 | 机器主键，不能随意改名 |
| `fragment_name` | string | fragment 短名称 | 必需 | 人类可读名称 |
| `version` | string | 规则版本 | 必需 | 用于复现和版本管理 |
| `category` | string | fragment 类别 | 必需 | 如 `functional_group`, `ring_structure`, `mainchain_linker` |
| `parent_fragment_id` | string / null | 父级 fragment ID | 可选 | 用于 `FG_AMIDE` / `FG_AROMATIC_AMIDE` 等父子层级；无父级时为 `null` 或省略 |
| `semantic_tags` | string[] | 语义标签 | 必需 | 用于解释、分组、性质关联；允许为空数组 |
| `match_rule` | object | 匹配规则 | 必需 | 定义如何在 graph/SMILES 上匹配 |
| `match_rule.type` | string | 规则类型 | 必需 | 如 `smarts`, `graph_pattern` |
| `match_rule.pattern` | string | SMARTS 或图模式 | 必需 | 核心可执行规则 |
| `match_rule.constraints` | object | 附加约束 | 必需 | 用于排除过匹配、限定环大小等；无约束时写 `{}` |
| `atom_roles` | object | 匹配原子的角色定义 | 必需 | SMARTS 规则必须使用 atom map number，`atom_roles` 的 key 必须是 map id 字符串 |
| `anchor_rule` | object | fragment 实例锚点规则 | 必需 | 用于稳定归属和去重 |
| `anchor_rule.anchor_type` | string | anchor 类型 | 必需 | 如 `atom`, `bond`, `composite` |
| `anchor_rule.anchor_role` | string | anchor 对应角色 | 必需 | 如 `carbonyl_carbon` |
| `ownership_rule` | string | 实例归属规则 | 必需 | 如 `anchor_in_RU0`, `bond_midpoint_in_RU0` |
| `periodic_radius` | integer | 周期展开半径 | 必需 | 通常为 `1`，表示看左右相邻 repeat unit |
| `allow_boundary_crossing` | boolean | 是否允许跨 repeat-unit 边界匹配 | 必需 | 主链连接类通常为 `true` |
| `enable_cut_shift_scan` | boolean | 是否启用切分偏移稳定性扫描 | 必需 | 用于验证不同 repeat-unit 切分是否一致 |
| `max_cut_shift` | integer | 最大切分偏移范围 | 必需 | 通常为 `1` |
| `dedup_key_fields` | string[] | instance 去重 key 的组成字段 | 必需 | 防止跨边界或多匹配重复计数 |
| `overlap_policy` | object | fragment 重叠处理策略 | 必需 | 处理父子 fragment 或互斥 fragment |
| `overlap_policy.exclusive_group` | string / null | 互斥/冲突组 | 必需 | 如 `carbonyl_family`；无互斥组时为 `null` |
| `overlap_policy.priority` | integer | 匹配优先级 | 必需 | 数值越高越优先 |
| `overlap_policy.allow_child_fragments` | boolean | 是否允许保留子 fragment | 必需 | 如 amide 可以允许 carbonyl 作为 child |

## 默认值

生产核心词表要求字段显式写出。生成 draft 时可使用以下默认值补齐：

| 字段 | 默认值 |
|---|---|
| `parent_fragment_id` | `null` |
| `semantic_tags` | `[]` |
| `match_rule.constraints` | `{}` |
| `periodic_radius` | `1` |
| `allow_boundary_crossing` | `true` |
| `enable_cut_shift_scan` | `false` |
| `max_cut_shift` | `1` |
| `overlap_policy.exclusive_group` | `null` |
| `overlap_policy.priority` | `0` |
| `overlap_policy.allow_child_fragments` | `true` |

## atom_roles 约定

SMARTS 规则必须显式使用 atom map number，`atom_roles` 的 key 必须是 map id 字符串。

正确：

```json
{
  "match_rule": {
    "type": "smarts",
    "pattern": "[NX3:1][CX3:2](=[OX1:3])",
    "constraints": {}
  },
  "atom_roles": {
    "1": "amide_nitrogen",
    "2": "carbonyl_carbon",
    "3": "carbonyl_oxygen"
  }
}
```

错误：

```json
{
  "match_rule": {
    "type": "smarts",
    "pattern": "[NX3][CX3](=O)"
  },
  "atom_roles": {
    "N": "amide_nitrogen",
    "C": "carbonyl_carbon",
    "O": "carbonyl_oxygen"
  }
}
```

元素符号不能作为 `atom_roles` key，否则同一 SMARTS 中出现多个同元素原子时无法稳定选择 anchor。

## 不写入核心词表的字段

| 字段 | 放到哪里 | 原因 |
|---|---|---|
| `display_name` | UI/report 配置 | 不影响匹配 |
| `source_smiles` | `fragment_vocab_v1.0.examples.jsonl` | 示例信息不应污染规则 |
| `stats` | `fragment_vocab_v1.0.stats.json` | 统计会随数据更新 |
| `review` | `review_report.json` | 审核信息和规则执行解耦 |
| `embedding_policy` | 下游模型配置 | 属于训练配置，不属于匹配规则 |

## 最小生产示例

```json
{
  "fragment_id": "FG_AMIDE",
  "fragment_name": "amide",
  "version": "v1.0",
  "category": "functional_group",
  "parent_fragment_id": null,
  "semantic_tags": [
    "polar",
    "hydrogen_bonding",
    "rigidifying",
    "backbone_possible"
  ],
  "match_rule": {
    "type": "smarts",
    "pattern": "[NX3:1][CX3:2](=[OX1:3])",
    "constraints": {
      "exclude": ["urea", "imide_if_more_specific"]
    }
  },
  "atom_roles": {
    "1": "amide_nitrogen",
    "2": "carbonyl_carbon",
    "3": "carbonyl_oxygen"
  },
  "anchor_rule": {
    "anchor_type": "atom",
    "anchor_role": "carbonyl_carbon"
  },
  "ownership_rule": "anchor_in_RU0",
  "periodic_radius": 1,
  "allow_boundary_crossing": true,
  "enable_cut_shift_scan": true,
  "max_cut_shift": 1,
  "dedup_key_fields": [
    "fragment_id",
    "anchor_type",
    "anchor_role",
    "anchor_canonical_id_in_RU0",
    "atom_role_pattern",
    "boundary_pattern"
  ],
  "overlap_policy": {
    "exclusive_group": "carbonyl_family",
    "priority": 80,
    "allow_child_fragments": true
  }
}
```
