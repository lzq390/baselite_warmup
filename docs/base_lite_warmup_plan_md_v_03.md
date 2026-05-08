# BaseLite Warmup 训练规划文档

版本：v0.3  
目标产物：`base_lite_warmup_v1.ckpt`  
训练类型：自监督预训练为主 + 规则弱监督辅助  
适用阶段：BaseLite warmup → Prop-first 性质预测微调

更新注记：当前基座模型已选择 Qwen2.5-7B Base。tokenizer 和模板设计以 `docs/baselite_qwen25_warmup_template_design.md` 为准：第一阶段不新增 special tokens，不使用 chat template，`L_restore` 的 canonical target 作为独立 `restore_labels` 监督 restore head，不拼入 decoder trunk 输入。

---

## 1. 文档目标

本文档用于定义 BaseLite warmup 阶段的完整训练规划，包括数据输入、预处理派生字段、模型结构、四个训练任务、损失函数、参数更新策略、训练配置、日志指标、checkpoint 导出以及与后续性质预测阶段的衔接方式。

BaseLite warmup 的核心原则是：

> 原始数据集只需要提供一个聚合物 SMILES / polymer string；其余训练字段均由预处理或 dataloader 自动派生。

也就是说，用户或数据集最初不需要人工提供 `repeat_unit_graph`、`text_view_1`、`text_view_2`、`fragment_instances` 或 `fragment_presence_multi_hot_labels`。

---

## 2. BaseLite Warmup 的定位

BaseLite warmup 不是最终性质预测训练，而是一个多任务预训练阶段。它的目标是先训练一个可复用的多模态聚合物表示底座。

该底座需要具备以下能力：

1. 理解和恢复聚合物字符串；
2. 解析并编码重复单元图结构；
3. 对齐文本表示和图表示；
4. 融合文本、图和片段级结构信息；
5. 形成稳定的片段 embedding，为后续 property attribution 做准备。

整体流程为：

```text
原始 SMILES
    ↓
预处理自动派生训练字段
    ↓
BaseLite warmup 四任务联合训练
    ↓
导出 base_lite_warmup_v1.ckpt
    ↓
接入 Prop-first finetune
```

---

## 3. 原始数据格式

### 3.1 最小数据集格式

原始数据最小只需要一个字段：

```csv
smiles
```

推荐至少包含样本 ID：

```csv
id,smiles
p000001,*CC(*)C(=O)O
p000002,*OC(=O)c1ccc(C(=O)O*)cc1
```

其中 `*` 或其他项目约定符号表示聚合物重复单元连接位点。

### 3.2 推荐数据集格式

```csv
id,smiles,source,split_hint,comment
p000001,*CC(*)C(=O)O,polymer_dataset_a,,linear polymer sample
p000002,*OC(=O)c1ccc(C(=O)O*)cc1,polymer_dataset_b,,aromatic polyester
```

字段说明：

| 字段 | 是否必需 | 说明 |
|---|---:|---|
| `id` | 推荐 | 样本唯一 ID |
| `smiles` / `polymer_string` | 必需 | 原始聚合物字符串 |
| `source` | 可选 | 数据来源 |
| `split_hint` | 可选 | 预指定 train / valid / test |
| `comment` | 可选 | 备注，不进入模型 |

---

## 4. 训练字段派生流程

从一个原始 SMILES 出发，数据管线需要自动生成以下字段：

```text
raw_polymer_string
    ↓
canonical_repeating_unit_string
    ├── canonical_text_target
    ├── text_view_1
    ├── text_view_2
    └── repeat_unit_graph
          ├── graph encoder input
          └── fragment_vocab_v1 规则匹配
                ├── fragment_instances
                └── fragment_presence_multi_hot_labels
```

训练阶段实际可用的样本结构为：

```json
{
  "id": "p000001",
  "raw_polymer_string": "...",
  "canonical_repeating_unit_string": "...",
  "canonical_text_target": "...",
  "text_view_1": "...",
  "text_view_2": "...",
  "repeat_unit_graph": {...},
  "fragment_instances": [...],
  "fragment_presence_multi_hot_labels": [...]
}
```

注意：这些字段不要求人工标注，可以离线生成并缓存，也可以在 dataloader 中在线生成。

---

## 5. 字符串标准化

### 5.1 输入与输出

输入：

```text
raw_polymer_string
```

输出：

```text
canonical_repeating_unit_string
```

### 5.2 标准化目标

字符串标准化的目标是把同一个结构对象的不同表面写法统一到稳定表达。

需要处理：

1. 语法合法性检查；
2. 原子、键、括号、环闭合表达标准化；
3. 芳香性表达标准化；
4. 连接位点标准化；
5. head / tail 方向规范化；
6. 非法样本过滤。

### 5.3 推荐校验项

```text
- 是否可解析为分子 / 聚合物重复单元
- 是否包含合法连接位点
- 是否只有一个主重复单元结构
- 是否存在悬空键
- 是否存在非法价态
- 是否符合项目定义的 polymer string grammar
```

---

## 6. 文本视图生成

### 6.1 输出字段

从 `canonical_repeating_unit_string` 派生：

```text
canonical_text_target
text_view_1
text_view_2
```

其中：

```text
canonical_text_target = canonical_repeating_unit_string
```

二者内容通常相同，但训练角色不同：

- `canonical_repeating_unit_string` 是标准化产物；
- `canonical_text_target` 是任务 1 的恢复目标；
- `text_view_1` / `text_view_2` 是扰动后的输入视图。

### 6.2 text_view 增强方式

建议支持以下增强：

```text
- 等价 SMILES 扰动
- 方向翻转
- 局部 token dropout
- 局部 mask
- 去噪视图构造
```

示例：

```text
canonical_text_target:
    [*:1]CC(C)C(=O)O[*:2]

text_view_1:
    [*:2]OC(=O)C(C)CC[*:1]

text_view_2:
    [*:1]CC(<mask>)C(=O)O[*:2]
```

### 6.3 视图分工

```text
text_view_1:
    主要用于任务1字符串恢复、任务2 text-graph 对齐、任务3片段存在性。

text_view_2:
    主要用于任务4构造第二个 fragment-aware fused representation。
```

---

## 7. repeat_unit_graph 构建

### 7.1 为什么必须转图

图编码器不能直接吃 SMILES 字符串。它需要的是节点、边、节点特征和边特征。

因此图分支必须经过：

```text
canonical_repeating_unit_string
    ↓
parser
    ↓
repeat_unit_graph
    ↓
tensorization
    ↓
graph encoder
```

### 7.2 repeat_unit_graph 是什么

`repeat_unit_graph` 是：

```text
单个重复单元分子图
+
连接位点信息
+
repeat connection 标记
+
片段匹配所需结构注释
```

它不是无限展开的聚合物链。

在默认线性单重复单元场景下，`repeat_unit_graph` 通常应为连通图。

### 7.3 节点特征

推荐节点特征：

```text
atom_type
atomic_number
formal_charge
hybridization
aromaticity
degree
num_hydrogens
is_in_ring
chirality
is_connection_atom
connection_role
```

其中：

```text
connection_role ∈ {none, head, tail, unknown}
```

### 7.4 边特征

推荐边特征：

```text
bond_type
is_aromatic
is_conjugated
is_in_ring
stereo
is_repeat_connection
cross_monomer_flag
```

### 7.5 张量化输出

```python
{
    "x": node_features,
    "edge_index": edge_index,
    "edge_attr": edge_features,
    "batch": graph_batch,
    "connection_atoms": optional,
    "graph_meta": optional
}
```

---

## 8. 规则片段匹配

### 8.1 输入与输出

输入：

```text
repeat_unit_graph
```

输出：

```text
fragment_instances
fragment_presence_multi_hot_labels
```

### 8.2 fragment_vocab_v1

`fragment_vocab_v1` 是规则片段词表。每个片段建议包含：

```text
fragment_id
fragment_name
SMARTS / graph_pattern
priority
allow_overlap
description
```

示例：

```json
{
  "fragment_id": 12,
  "fragment_name": "ester",
  "pattern": "C(=O)O",
  "allow_overlap": true
}
```

### 8.3 fragment_instances

片段实例记录的是当前图中具体匹配到的片段位置。

```json
[
  {
    "fragment_type_id": 12,
    "atom_indices": [3, 4, 5],
    "bond_indices": [2, 3],
    "instance_id": "frag_0001"
  }
]
```

### 8.4 fragment_presence_multi_hot_labels

如果片段词表大小为 `K`，则标签为：

```text
y_frag ∈ {0,1}^K
```

其中：

```text
y_frag[k] = 1 表示第 k 类片段存在
y_frag[k] = 0 表示第 k 类片段不存在
```

该标签由规则自动生成，不需要人工标注。

---

## 9. Tokenizer 规划

### 9.1 Tokenizer 目标

第一阶段使用 Qwen2.5-7B Base 原生 tokenizer：

```text
models/qwen2.5-7b-tokenizer/
```

Tokenizer 需要稳定处理 polymer repeat-unit SMILES 中的：

```text
- 化学原子 token
- 键 token
- 括号、环闭合 token
- 聚合物连接位点 token
- 普通文本模板标签
```

### 9.2 Special tokens 策略

```text
不新增 special tokens
不 resize embedding
不训练自定义化学 tokenizer
不使用 Qwen chat template
```

`<polymer_smiles>`、`<polymer_view_smiles>` 等标签只是普通文本模板标签，由 Qwen tokenizer 按原词表切分。

### 9.3 聚合物连接位点表示

```text
[*]
[*:1]
[*:2]
*
```

聚合物连接位点保留 SMILES 原始表示，不额外引入 `[HEAD]`、`[TAIL]`、`[CONN]` 这类训练专用 token。

### 9.4 Embedding 初始化

```text
第一阶段没有新增 token，因此没有新增 embedding 初始化步骤。
```

LoRA、projector、graph encoder、fusion layer 和辅助 head 按训练配置初始化或加载。

### 9.5 任务输入模板

任务 1：

```text
输入：
<polymer_view_smiles>
{text_view_1}
</polymer_view_smiles>

监督目标：
{canonical_text_target}<|endoftext|>
```

任务 2：

```text
<polymer_smiles>
{text_view_1}
</polymer_smiles>
```

任务 4：

```text
<polymer_smiles>
{text_view_2}
</polymer_smiles>
```

任务 1 的 canonical target 单独 tokenize 成 `restore_labels`，只用于 `fusion / interaction layer -> restore head` 的 token-level CE loss；它不进入 decoder trunk，也不是 `L_align` 的输入。

---

## 10. 模型结构

BaseLite warmup 包含：

```text
Tokenizer
Decoder trunk
LoRA
Graph encoder
Graph memory / pooling
Text projector
Graph projector
Fusion / interaction layer
Restore head
Fragment presence head
Fragment consistency module
```

### 10.1 文本分支

```text
text_view
    ↓
Tokenizer
    ↓
decoder trunk + LoRA
    ↓
H_text
```

其中：

```text
decoder backbone 冻结
LoRA 可训练
```

### 10.2 LoRA 插入位置

推荐第一版插入：

```text
q_proj
k_proj
v_proj
o_proj
```

可选扩展到：

```text
gate_proj
up_proj
down_proj
```

推荐配置：

```yaml
lora_rank: 8
lora_alpha: 16
lora_dropout: 0.05
```

### 10.3 图分支

```text
repeat_unit_graph
    ↓
graph encoder
    ↓
atom embeddings
```

图编码器建议第一版使用 GIN / MPNN：

```yaml
graph_encoder:
  type: gin
  num_layers: 5
  hidden_dim: 256
  dropout: 0.1
```

### 10.4 Graph memory

Graph memory 建议包含多粒度 token：

```text
atom tokens
fragment tokens
global graph token
connection tokens optional
```

推荐构造：

```text
M_graph = concat(atom_tokens, fragment_tokens, global_token)
```

### 10.5 Projector

`text projector` 和 `graph projector` 用于任务 2 的 text-graph 对比对齐。

```text
text rep  -> text projector  -> z_text
graph rep -> graph projector -> z_graph
```

Projector 不负责融合，也不负责生成。它的主要作用是把两种模态投影到同一个 contrastive space。

### 10.6 Fusion / Interaction layer

Fusion 层负责把文本表示和 graph memory 融合。

```text
H_text + M_graph -> H_fused
```

可选实现：

1. Cross-attention fusion；
2. Gate fusion；
3. Concat + MLP fusion。

如果任务 4 要做片段级一致性，推荐 fusion 输出保留 atom-level 或 fragment-level 可索引结构。

---

## 11. Warmup 四个任务

## 11.1 任务1：字符串恢复 `L_restore`

### 定义

任务 1 的目标是从融合后的表示恢复 canonical 字符串。

```text
text_view_1 + graph memory
    ↓
fusion / interaction layer
    ↓
restore head
    ↓
canonical_text_target
```

这里的任务 1 不是简单 text-only copy，而是融合文本结构与图结构信息后恢复到 canonical target。

### 输入

```text
text_view_1
repeat_unit_graph / graph memory
```

### 目标

```text
canonical_text_target
```

### 损失

```text
L_restore = CE(predicted canonical tokens, canonical_text_target tokens)
```

### 作用

```text
- 让 decoder + LoRA 适应聚合物字符串
- 让 fusion 后表示保留结构细节
- 让模型学习 canonical 化和去噪恢复能力
```

---

## 11.2 任务2：Text-Graph 对比对齐 `L_align`

### 定义

让同一个 polymer 的 text rep 与 graph rep 在统一潜空间中靠近，不同样本远离。

```text
text rep <-> graph rep
```

### 前向流程

```text
text_view_1
    ↓
decoder trunk
    ↓
text pooling
    ↓
text projector
    ↓
z_text

repeat_unit_graph
    ↓
graph encoder
    ↓
graph pooling
    ↓
graph projector
    ↓
z_graph
```

### 损失

推荐 InfoNCE：

```text
L_align = CE(sim(z_text_i, z_graph_j) / τ, label=i)
```

推荐对称形式：

```text
L_align = 0.5 * L_text_to_graph + 0.5 * L_graph_to_text
```

### 作用

```text
- 让文本视图和图视图指向同一个结构对象
- 提升跨模态表示一致性
- 为后续 fusion 提供更稳定的输入空间
```

---

## 11.3 任务3：片段存在性 `L_fragment_presence`

### 定义

任务 3 是多标签分类任务，用 fused representation 预测当前 polymer 中出现了哪些规则片段。

```text
fused rep -> fragment presence head -> fragment_presence_logits
fragment_presence_multi_hot_labels -> BCE labels
```

### 标签来源

```text
repeat_unit_graph
    ↓
fragment_vocab_v1 规则匹配
    ↓
fragment_instances
    ↓
fragment_presence_multi_hot_labels
```

### 前向流程

```text
H_text + graph memory
    ↓
fusion / interaction layer
    ↓
H_fused
    ↓
fragment presence head
    ↓
logits_frag ∈ R^K
```

### 损失

```text
L_fragment_presence = BCEWithLogitsLoss(logits_frag, y_frag)
```

由于标签稀疏，建议使用：

```text
pos_weight
AUPRC
micro-F1 / macro-F1
```

### 作用

```text
- 让模型显式学习局部结构语义
- 强化 fused representation 中的片段信息
- 为后续片段级解释和归因打底
```

---

## 11.4 任务4：片段一致性 `L_fragment_consistency`

### 定义

任务 4 约束同一片段在不同表征路径下的 embedding 保持一致。

注意：

```text
fragment-aware fused rep view 2 不是 text_view_2 字符串本身。
```

它是经过 fusion / interaction layer 后得到的片段感知融合表示。

### View1 来源

`fragment embedding view 1` 来自纯图侧：

```text
atom embeddings
    + fragment_instances
    ↓
fragment pooling
    ↓
fragment_embedding_view1
```

公式：

```text
z_m_view1 = Pool({h_atom_i | i ∈ fragment_instance_m})
```

### View2 来源

`fragment-aware fused rep view 2` 来自融合侧：

```text
H_text_2 + graph memory
    ↓
fusion / interaction layer
    ↓
H_fused_2
    ↓
fragment readout / fragment pooling
    ↓
fragment_aware_fused_rep_view2
```

如果 fusion 输出保持 atom-level token：

```text
z_m_view2 = Pool({H_fused_atom_i | i ∈ fragment_instance_m})
```

如果 fusion 输出不是 atom-level，可以使用 fragment query readout：

```text
fragment query
    ↓
cross-attention over H_fused
    ↓
z_m_view2
```

### 损失

推荐第一版使用 cosine consistency：

```text
L_fragment_consistency = mean_m (1 - cos(z_m_view1, z_m_view2))
```

也可以使用 MSE：

```text
L_fragment_consistency = mean_m ||z_m_view1 - z_m_view2||^2
```

### presence label 的作用

`fragment_presence_multi_hot_labels` 只用于 `L_fragment_presence` 的多标签监督。

```text
不用于构造 view2
不作为 L_fragment_consistency 的输入
不作为 fragment consistency 的 mask / selector
```

真正决定片段边界的是：

```text
fragment_instances
```

### 作用

```text
- 稳定 fragment embedding
- 降低文本扰动导致的片段表示漂移
- 支持后续 property attribution
```

---

## 12. 总损失函数

```text
L_warmup =
    λ1 * L_restore
  + λ2 * L_align
  + λ3 * L_fragment_presence
  + λ4 * L_fragment_consistency
```

推荐初始权重：

```yaml
lambda_restore: 1.0
lambda_align: 1.0
lambda_fragment_presence: 0.5
lambda_fragment_consistency: 0.2
```

执行顺序：

```text
smoke test: 只开启 L_restore，验证 text-only restore 流程。
正式第一阶段: 开启 L_restore + L_align，不依赖 fragment 词表。
fragment-aware 阶段: fragment_vocab_v1 稳定后，再加入 L_fragment_presence + L_fragment_consistency。
```

---

## 13. 参数更新与冻结

### 13.1 训练时更新

```text
LoRA parameters
graph encoder
graph memory projection / pooling
fusion / interaction layer
text projector
graph projector
restore head
fragment presence head
fragment consistency projection optional
```

### 13.2 训练时冻结

```text
decoder backbone 主体
标准化规则
图构建 parser
fragment_vocab_v1 规则匹配器
```

说明：正式第一阶段不加载 fragment_vocab_v1 规则匹配器；该项只适用于后续 fragment-aware 阶段。

### 13.3 warmup 后保留

```text
decoder trunk + LoRA
graph encoder
graph memory projection / pooling
fusion / interaction layer
fragment pooling logic
```

### 13.4 warmup 后不保留

```text
restore head
text projector
graph projector
fragment presence head
```

这些 head 是 warmup 辅助头，主要用于把能力注入主干和融合模块。

---

## 14. 训练配置建议

```yaml
optimizer: AdamW
weight_decay: 0.01
betas: [0.9, 0.999]
eps: 1e-8

learning_rate:
  lora: 1.0e-4
  graph_encoder: 1.0e-4
  fusion: 1.0e-4
  projector: 2.0e-4
  aux_heads: 2.0e-4

scheduler:
  type: cosine
  warmup_ratio: 0.03
  min_lr_ratio: 0.1

train:
  global_batch_size: 128
  gradient_accumulation_steps: 4
  precision: bf16
  max_grad_norm: 1.0
  max_epochs: 20
```

对比学习依赖 batch 内负样本，因此任务 2 通常希望更大的 global batch。

---

## 15. Dataloader 输出结构

### 15.1 文本 batch

```python
{
    "input_ids_view1": LongTensor[B, L1],
    "attention_mask_view1": LongTensor[B, L1],
    "restore_labels": LongTensor[B, L_restore],
    "restore_label_mask": BoolTensor[B, L_restore],
    "input_ids_view2": LongTensor[B, L2],
    "attention_mask_view2": LongTensor[B, L2]
}
```

### 15.2 图 batch

```python
{
    "node_features": FloatTensor[N_total, node_dim],
    "edge_index": LongTensor[2, E_total],
    "edge_features": FloatTensor[E_total, edge_dim],
    "graph_batch": LongTensor[N_total]
}
```

### 15.3 片段 batch

```python
{
    "fragment_instances": List[List[FragmentInstance]],
    "fragment_presence_labels": FloatTensor[B, K],
    "fragment_atom_index": Optional[LongTensor],
    "fragment_batch_index": Optional[LongTensor]
}
```

---

## 16. 单步训练伪代码

```python
for batch in dataloader:
    H_text_1 = decoder_trunk(
        input_ids=batch["input_ids_view1"],
        attention_mask=batch["attention_mask_view1"],
        lora=True
    )

    H_text_2 = decoder_trunk(
        input_ids=batch["input_ids_view2"],
        attention_mask=batch["attention_mask_view2"],
        lora=True,
        shared_params=True
    )

    H_atom = graph_encoder(
        x=batch["node_features"],
        edge_index=batch["edge_index"],
        edge_attr=batch["edge_features"],
        batch=batch["graph_batch"]
    )

    graph_memory = build_graph_memory(
        atom_embeddings=H_atom,
        fragment_instances=batch["fragment_instances"]
    )

    # Task 1: fused restore
    H_fused_1 = fusion_layer(H_text_1, graph_memory)
    restore_logits = restore_head(H_fused_1)
    L_restore = token_ce_loss(
        restore_logits,
        batch["restore_labels"],
        loss_mask=batch["restore_label_mask"]
    )

    # Task 2: text-graph align
    z_text = text_projector(pool_text(H_text_1))
    z_graph = graph_projector(pool_graph(graph_memory))
    L_align = contrastive_loss(z_text, z_graph)

    # Task 3: fragment presence
    frag_logits = fragment_presence_head(pool_fused(H_fused_1))
    L_frag_presence = bce_with_logits(
        frag_logits,
        batch["fragment_presence_labels"]
    )

    # Task 4: fragment consistency
    frag_view1 = fragment_pooling(H_atom, batch["fragment_instances"])
    H_fused_2 = fusion_layer(H_text_2, graph_memory, shared_params=True)
    frag_view2 = fragment_readout(H_fused_2, batch["fragment_instances"])
    L_frag_consistency = consistency_loss(frag_view1, frag_view2)

    loss = (
        lambda_restore * L_restore
        + lambda_align * L_align
        + lambda_fragment_presence * L_frag_presence
        + lambda_fragment_consistency * L_frag_consistency
    )

    loss.backward()
    optimizer.step()
    scheduler.step()
    optimizer.zero_grad()
```

---

## 16.5 不依赖词表的执行顺序

当前可以先不接入 fragment_vocab_v1，把微调主流程分三步打通。

### Step 0：模板和 dataloader preview

不训练，只生成并检查：

```text
input_ids_view1 / attention_mask_view1
input_ids_view2 / attention_mask_view2
restore_labels / restore_label_mask
repeat_unit_graph batch
length stats
round-trip stats
```

### Step 1：Text-only restore smoke test

用途：

```text
验证 Qwen2.5 tokenizer、LoRA、restore head、decode/eval、checkpoint 保存加载。
```

开启：

```text
L_restore
```

关闭：

```text
L_align
L_fragment_presence
L_fragment_consistency
graph encoder
fragment_vocab matcher
```

该阶段只作为工程冒烟测试和 baseline，不作为正式 BaseLite 底座。

### Step 2：Non-vocab BaseLite warmup

用途：

```text
打通正式第一阶段：text_view + repeat_unit_graph -> fusion / alignment / restore。
```

开启：

```text
L_restore
L_align
graph encoder
fusion / interaction layer
text projector
graph projector
restore head
```

关闭：

```text
L_fragment_presence
L_fragment_consistency
fragment_vocab matcher
fragment labels
```

验收指标：

```text
restore valid string rate
canonical exact match rate
text-to-graph retrieval top1 / top5
graph-to-text retrieval top1 / top5
checkpoint / adapter export and reload
```

### Step 3：Fragment-aware warmup

fragment_vocab_v1 稳定后再进入：

```text
L_restore
L_align
L_fragment_presence
L_fragment_consistency
fragment_vocab matcher
fragment_instances
fragment_presence_labels
```

---

## 17. 训练监控指标

### 17.1 Loss 指标

```text
L_restore
L_align
L_fragment_presence
L_fragment_consistency
L_total
```

### 17.2 任务1指标

```text
token accuracy
sequence accuracy
valid string rate
canonical exact match rate
edit distance
```

### 17.3 任务2指标

```text
text-to-graph retrieval top1 / top5
graph-to-text retrieval top1 / top5
mean positive similarity
mean negative similarity
```

### 17.4 任务3指标

```text
fragment micro-F1
fragment macro-F1
fragment AUROC
fragment AUPRC
positive recall
```

### 17.5 任务4指标

```text
same-fragment cosine similarity
same-fragment MSE
embedding variance across views
```

---

## 18. Checkpoint 保存策略

建议保存：

```text
best_by_valid_total_loss.ckpt
best_by_align_retrieval.ckpt
best_by_fragment_f1.ckpt
last.ckpt
```

最终导出：

```text
base_lite_warmup_v1.ckpt
```

Checkpoint 应包含：

```python
{
    "decoder_lora": ...,
    "graph_encoder": ...,
    "graph_memory_projection": ...,
    "fusion_layer": ...,
    "tokenizer_config": ...,
    "fragment_vocab_version": "fragment_vocab_v1",
    "preprocess_config": ...,
    "training_config": ...
}
```

辅助头可另存用于复现实验：

```text
auxiliary_heads.ckpt
```

---

## 19. 与 Prop-first Finetune 的衔接

Prop-first 阶段仍然从 SMILES 开始：

```text
SMILES
    ↓
same preprocessing
    ↓
text representation + graph memory
    ↓
BaseLite fusion
    ↓
property heads
```

下游保留：

```text
decoder trunk + LoRA
graph encoder
graph memory projection / pooling
fusion / interaction layer
```

下游新增：

```text
property regression heads
property classification heads
uncertainty head optional
attribution module optional
```

推荐微调策略：

```text
Stage 1: 冻结 BaseLite，只训练 property head
Stage 2: 解冻 fusion 和 graph memory
Stage 3: 小学习率联合训练 LoRA、graph encoder、fusion、property heads
```

---

## 20. 推荐项目目录结构

```text
baselite/
  configs/
    restore_smoke_test.yaml
    non_vocab_warmup_v1.yaml
    fragment_warmup_v1.yaml
    fragment_vocab_v1.yaml

  data/
    baselite_smiles_v1/
      train.jsonl
      valid.jsonl
      test.jsonl
      token_stats.json
    processed/
      repeat_unit_graphs.jsonl

  preprocessing/
    canonicalize.py
    build_repeat_unit_graph.py
    augment_text_view.py
    fragment_matcher.py

  models/
    decoder_lora.py
    graph_encoder.py
    graph_memory.py
    projectors.py
    fusion.py
    heads.py

  losses/
    restore_loss.py
    contrastive_loss.py
    fragment_presence_loss.py
    fragment_consistency_loss.py

  train/
    train_warmup.py
    datamodule.py
    trainer.py

  checkpoints/
    base_lite_warmup_v1.ckpt

  logs/
    tensorboard/
    wandb/
```

---

## 21. non_vocab_warmup_v1.yaml 示例

```yaml
experiment:
  name: baselite_non_vocab_warmup_v1
  seed: 42
  output_dir: checkpoints/baselite_non_vocab_warmup_v1
  stage: non_vocab_warmup

data:
  train_path: data/baselite_smiles_v1/train.jsonl
  valid_path: data/baselite_smiles_v1/valid.jsonl
  test_path: data/baselite_smiles_v1/test.jsonl
  graph_path: data/processed/repeat_unit_graphs.jsonl
  split:
    train: 0.80
    valid: 0.10
    test: 0.10

preprocess:
  canonicalize: true
  require_connected_repeat_unit_graph: true
  max_atoms: 256
  max_seq_len_view: 512
  max_seq_len_restore_label: 512
  fragment_vocab: null

augmentation:
  num_text_views: 2
  equivalent_smiles_aug: false
  random_direction_flip: false
  text_mask_ratio: 0.00

tokenizer:
  path: models/qwen2.5-7b-tokenizer
  use_chat_template: false
  add_polymer_special_tokens: false

model:
  decoder:
    freeze_backbone: true
    use_lora: true
    lora_rank: 8
    lora_alpha: 16
    lora_dropout: 0.05
    lora_target_modules:
      - q_proj
      - k_proj
      - v_proj
      - o_proj

  graph_encoder:
    type: gin
    num_layers: 5
    hidden_dim: 256
    dropout: 0.1

  graph_memory:
    use_atom_tokens: true
    use_fragment_tokens: false
    use_global_token: true
    hidden_dim: 256

  projector:
    align_dim: 256
    mlp_hidden_dim: 512
    normalize: true

  fusion:
    type: cross_attention
    hidden_dim: 256
    num_layers: 2
    num_heads: 4
    dropout: 0.1

loss:
  lambda_restore: 1.0
  lambda_align: 1.0
  lambda_fragment_presence: 0.0
  lambda_fragment_consistency: 0.0
  contrastive_temperature: 0.07

tasks:
  enable_restore: true
  enable_align: true
  enable_fragment_presence: false
  enable_fragment_consistency: false

train:
  optimizer: adamw
  lr_lora: 1.0e-4
  lr_graph_encoder: 1.0e-4
  lr_fusion: 1.0e-4
  lr_projector: 2.0e-4
  lr_aux_heads: 2.0e-4
  weight_decay: 0.01
  scheduler: cosine
  warmup_ratio: 0.03
  batch_size: 128
  gradient_accumulation_steps: 4
  precision: bf16
  max_grad_norm: 1.0
  max_epochs: 20
```

---

## 22. 里程碑计划

### Milestone 1：模板和基础数据管线打通

验收标准：

```text
- raw SMILES 可生成 canonical string
- 可生成 text_view_1 / text_view_2
- 可生成 repeat_unit_graph
- dataloader 可正常 batch
- tokenizer round-trip 无失败
- restore label mask 正确
```

### Milestone 2：Text-only restore smoke test

验收标准：

```text
- 小数据集上 L_restore 下降
- decoded string 可完成后处理和 RDKit 校验
- checkpoint / adapter 可保存和重新加载
- 明确该阶段只作为 baseline，不作为正式 BaseLite 底座
```

### Milestone 3：Non-vocab BaseLite warmup

验收标准：

```text
- L_restore 和 L_align 同时可训练
- validation retrieval 提升
- canonical exact match 或 valid string rate 不劣化
- checkpoint / adapter export 可用于下游加载
```

### Milestone 4：Fragment-aware warmup

验收标准：

```text
- fragment_vocab_v1 matcher 稳定
- 可生成 fragment_instances
- 可生成 multi-hot labels
- 四个 loss 不爆炸
- validation retrieval 提升
- fragment F1 提升
```

### Milestone 5：导出 checkpoint

验收标准：

```text
- 生成 base_lite_warmup_v1.ckpt
- tokenizer config 保存完整
- fragment vocab version 保存完整
- downstream 可加载
```

### Milestone 6：Prop-first 验证

验收标准：

```text
- 与随机初始化 baseline 对比
- 与 text-only baseline 对比
- 与 graph-only baseline 对比
- 至少一个性质任务收敛更快或指标更优
```

---

## 23. 主要风险

### 23.1 text_view 扰动过弱

如果大量样本中：

```text
text_view == canonical_text_target
```

任务 1 会退化为复制任务。

建议监控：

```text
view_target_exact_same_ratio
edit_distance(view, target)
```

### 23.2 fragment vocab 质量不足

过粗会导致任务太简单，过细会导致标签稀疏。建议第一版使用中等规模词表：

```text
100 ~ 1000 fragment types
```

### 23.3 batch 内负样本不足

任务 2 对 batch size 敏感。建议使用：

```text
larger global batch
gradient accumulation
distributed all-gather negatives
```

### 23.4 fusion 输出不支持片段索引

如果 fusion 只输出 global vector，则任务 4 很难做实例级片段一致性。建议保留 atom-level 或 fragment-level token。

### 23.5 多任务梯度冲突

建议使用 curriculum：

```yaml
epoch 0-2:
  enable_restore: true
  enable_align: true
  enable_fragment_presence: false
  enable_fragment_consistency: false

epoch 3-5:
  enable_fragment_presence: true

epoch 6+:
  enable_fragment_consistency: true
```

---

## 24. 消融实验建议

| 实验 | 配置 | 目的 |
|---|---|---|
| full warmup | 四个任务全开 | 主实验 |
| w/o restore | 去掉 `L_restore` | 验证恢复约束 |
| w/o align | 去掉 `L_align` | 验证跨模态对齐 |
| w/o fragment presence | 去掉任务 3 | 验证规则片段弱监督 |
| w/o consistency | 去掉任务 4 | 验证片段 embedding 稳定性 |
| text-only | 只用文本分支 | 验证图分支贡献 |
| graph-only | 只用图分支 | 验证文本分支贡献 |
| no LoRA | 不训练 LoRA | 验证文本适配能力 |

---

## 25. 最终总结

BaseLite warmup 可以概括为：

```text
一个 SMILES 输入
    ↓
自动派生文本视图、repeat unit graph、片段实例和片段标签
    ↓
文本分支学习 canonical 表达与稳定字符串表示
    ↓
图分支学习 repeat unit topology
    ↓
projector 对齐 text rep 与 graph rep
    ↓
fusion 层学习 text-graph 结构融合
    ↓
fragment presence 与 fragment consistency 强化片段级语义
    ↓
导出 base_lite_warmup_v1.ckpt
```

最终保留下游最需要的能力：

```text
稳定文本表示
稳定图表示
text-graph 对齐
结构保真的 fused representation
片段级解释基础
```

这就是后续性质预测、片段归因和 polymer design 的基础底座。
