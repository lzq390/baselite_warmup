# BaseLite Qwen2.5-7B Warmup 模板设计方案

生成日期：2026-05-08  
基座模型：`Qwen/Qwen2.5-7B` Base  
tokenizer：`models/qwen2.5-7b-tokenizer/`  
适用目标：BaseLite 多任务 warmup，作为后续预测、生成、解释等功能的底座模型

---

## 1. 设计结论

BaseLite warmup 不是单一 SMILES 去噪恢复任务。当前模板设计必须同时服务四类目标：

| 任务 | 目标 | 文本侧输入 / 监督 | 是否需要 graph / fragment 张量 |
|---|---|---:|---:|
| 任务 1：字符串恢复 `L_restore` | 从文本视图和结构表示恢复 canonical SMILES | `text_view_1` 输入 + 独立 `restore_labels` | 需要 graph memory |
| 任务 2：Text-Graph 对齐 `L_align` | 让文本表示和图表示进入同一结构语义空间 | `text_view_1` 输入 | 需要 graph tensor |
| 任务 3：片段存在性 `L_fragment_presence` | 让 fused 表示显式学习规则片段语义 | `text_view_1` 输入 | 需要 fragment labels |
| 任务 4：片段一致性 `L_fragment_consistency` | 稳定同一片段在图侧和融合侧的 embedding | `text_view_2` 输入 | 需要 fragment instances |

第一版模板策略：

```text
不使用 Qwen chat template
不新增 special tokens
不把 graph 序列化塞进文本 prompt
不把 fragment label 明文塞进 prompt
文本侧只描述 polymer SMILES view
graph / fragment 信息走张量侧和监督头
```

原因：

1. 当前基座是 Qwen2.5-7B Base，不是 Instruct 模型，不应使用聊天格式。
2. 新增 special tokens 需要 resize embedding，会引入额外变量，第一版先避免。
3. graph 和 fragment 的核心价值在结构张量和局部实例边界，不应退化成文本标签复制。
4. BaseLite 训练后要作为预测/生成底座，模板应保持稳定、简单、可迁移。

---

## 2. 当前 tokenizer 约束

已验证 Qwen2.5-7B tokenizer 对当前 11,580 条 canonical SMILES 可用：

```text
round-trip failure: 0
raw SMILES 推荐 max_seq_len: 512
train token max: 220
valid token max: 151
test token max: 366
```

注意：

```text
该统计只针对 raw canonical_smiles。
模板定稿后必须分别统计 view 输入长度和 restore label 长度。
```

第一版不新增以下 token：

```text
<polymer>
<view1>
<view2>
<target>
<frag>
<graph>
```

这些字符串可以作为普通文本标签出现，但不注册为 special token。

---

## 3. 通用文本视图模板

所有非生成表示任务统一使用一个短模板，减少任务间 prompt 分布差异。

### 3.1 Text View 模板

```text
<polymer_smiles>
{text_view}
</polymer_smiles>
```

示例：

```text
<polymer_smiles>
*#Cc1cccc(C#C[SiH](C#*)c2ccccc2)c1
</polymer_smiles>
```

用途：

```text
任务 2: L_align
任务 3: L_fragment_presence
任务 4: L_fragment_consistency 的 text_view_2
```

loss：

```text
不计算 token-level LM loss
只取 decoder hidden states 做 text projector / fusion / downstream heads
```

---

## 4. 任务 1：字符串恢复模板

### 4.1 任务定位

`L_restore` 是辅助约束，不是 BaseLite 的全部目标。它的作用是：

```text
让 Qwen LoRA 适应 polymer SMILES 语法
让 fused representation 保留可恢复的结构细节
给后续生成任务提供 canonical 输出能力
```

### 4.2 输入模板

```text
<polymer_view_smiles>
{text_view_1}
</polymer_view_smiles>
```

示例：

```text
<polymer_view_smiles>
*#Cc1cccc(C#C[SiH](C#*)c2ccccc2)c1
</polymer_view_smiles>
```

### 4.3 Restore target

`L_restore` 的 target 不拼进 decoder trunk 输入。target 单独 tokenize 成 restore labels：

```text
{canonical_text_target}<|endoftext|>
```

原因：

```text
decoder trunk 的 `H_text_1` 同时送往 text projector 和 fusion layer。
canonical target 不能拼进 decoder trunk 输入，否则 text projector 会看到答案，污染 L_align。
```

正确路径：

```text
input_ids_view1
-> decoder trunk
-> H_text_1
   ├── text projector -> z_text -> L_align
   └── fusion / interaction layer + graph memory
       -> restore head
       -> L_restore(restore_logits, restore_labels)
```

伪代码：

```python
view1_text = (
    "<polymer_view_smiles>\n"
    f"{text_view_1}\n"
    "</polymer_view_smiles>\n"
)

input_ids_view1 = tokenizer.encode(view1_text, add_special_tokens=False)
restore_labels = tokenizer.encode(canonical_text_target + tokenizer.eos_token, add_special_tokens=False)

H_text_1 = decoder_trunk(input_ids_view1)
H_fused_1 = fusion_layer(H_text_1, graph_memory)
restore_logits = restore_head(H_fused_1, target_length=len(restore_labels))
L_restore = token_ce_loss(restore_logits, restore_labels)
```

### 4.4 text_view_1 策略

第一阶段：

```text
identity view
```

第二阶段再加入：

```text
random SMILES
方向翻转
轻量 mask
轻量 span dropout
```

不要在第一版使用过强扰动，否则 `L_restore` 会变成猜测任务。

---

## 5. 任务 2：Text-Graph 对齐模板

### 5.1 任务定位

`L_align` 是 BaseLite 的核心任务之一。它决定文本分支是否能和 graph encoder 形成同一个结构语义空间。

### 5.2 文本输入

使用通用 Text View 模板：

```text
<polymer_smiles>
{text_view_1}
</polymer_smiles>
```

### 5.3 图输入

图输入不进入文本 prompt，而是通过 dataloader 由同一个 `record_id` / `canonical_hash` 取出：

```text
repeat_unit_graph
node_features
edge_index
edge_features
graph_batch
```

### 5.4 训练目标

```text
text_view_1
-> Qwen decoder trunk
-> text projector
-> z_text

repeat_unit_graph
-> graph encoder
-> graph projector
-> z_graph
```

损失：

```text
InfoNCE(z_text, z_graph)
```

模板不包含 target，不计算 LM loss。

注意：

```text
L_align 不接收 restore head 输出，也不接收 restore labels。
它只比较 text projector 和 graph projector 的输出。
```

### 5.5 Pooling 建议

第一版建议：

```text
取最后一个非 padding token hidden state
或 mean pooling over non-padding tokens
```

后续可对比：

```text
attention pooling
learned query pooling
```

---

## 6. 任务 3：Fragment Presence 模板

### 6.1 任务定位

`L_fragment_presence` 是规则弱监督任务。它让模型显式学习局部结构片段，例如 amide、ester、imide、aromatic ring 等。

### 6.2 文本输入

仍使用通用 Text View 模板：

```text
<polymer_smiles>
{text_view_1}
</polymer_smiles>
```

### 6.3 禁止事项

第一版不把 fragment label 明文放进 prompt：

```text
不推荐:
<fragments>
amide, ester, aromatic_ring
</fragments>
```

原因：

```text
这会让任务退化为标签文本复制/记忆，不再检验模型是否从结构中学到片段语义。
```

### 6.4 标签来源

标签来自 matcher：

```text
repeat_unit_graph
-> fragment_vocab_v1
-> fragment_instances
-> fragment_presence_labels
```

训练输入：

```python
{
    "input_ids_view1": ...,
    "attention_mask_view1": ...,
    "graph_tensor": ...,
    "fragment_presence_labels": FloatTensor[B, K]
}
```

损失：

```text
BCEWithLogitsLoss(fragment_presence_head(pool_fused(H_fused_1)), labels)
```

---

## 7. 任务 4：Fragment Consistency 模板

### 7.1 任务定位

`L_fragment_consistency` 约束同一个 fragment instance 在不同路径下的 embedding 保持一致：

```text
graph atom embedding pooled fragment
vs
text-graph fused representation readout fragment
```

### 7.2 text_view_2 模板

使用通用 Text View 模板，但输入换成 `text_view_2`：

```text
<polymer_smiles>
{text_view_2}
</polymer_smiles>
```

### 7.3 View 设计

`text_view_2` 应该和 `text_view_1` 不完全相同，但保持同一结构语义：

```text
优先: random SMILES / direction flip
谨慎: token mask / span dropout
暂不: fragment mask
```

原因：

```text
fragment consistency 需要片段边界仍能通过 graph side 精确定位。
过强文本破坏会让一致性损失变成噪声。
```

### 7.4 损失输入

```text
fragment_instances
H_atom
H_fused_2
```

不需要生成 target，也不计算 LM loss。

---

## 8. 显式 Fragment-Text 对齐扩展

当前四任务中，fragment 通过 presence 和 consistency 注入模型。若后续要显式做 fragment-text 对齐，可以增加一个独立扩展任务。

### 8.1 Fragment Text 模板

```text
<fragment_description>
id: {fragment_id}
name: {fragment_name}
category: {category}
description: {description}
</fragment_description>
```

示例：

```text
<fragment_description>
id: FG_AMIDE
name: amide
category: functional_group
description: carbonyl connected to nitrogen
</fragment_description>
```

### 8.2 对齐目标

```text
fragment instance embedding -> z_fragment
fragment description text -> z_fragment_text
```

损失：

```text
InfoNCE(z_fragment, z_fragment_text)
```

该任务依赖：

```text
稳定 fragment_vocab_v1
稳定 fragment_instances
每个 fragment 的人工可读 description
```

因此不放入第一阶段模板实现。

---

## 9. Dataloader 字段方案

### 9.1 不依赖词表的字段

当前 `data/baselite_smiles_v1` 已有：

```text
record_id
canonical_smiles
canonical_hash
graph_hash
split
```

可先生成：

```python
{
    "record_id": str,
    "canonical_text_target": str,
    "text_view_1": str,
    "text_view_2": str,
    "input_ids_view1": LongTensor[L1],
    "attention_mask_view1": LongTensor[L1],
    "input_ids_view2": LongTensor[L2],
    "attention_mask_view2": LongTensor[L2],
    "restore_labels": LongTensor[L_restore],
    "restore_label_mask": BoolTensor[L_restore]
}
```

字段关系：

```text
input_ids_view1:
    decoder trunk 的共享输入。
    分叉到 text projector -> L_align，以及 fusion layer -> restore / fragment presence。

input_ids_view2:
    decoder trunk 的第二文本视图输入。
    用于 fragment consistency 的 fused-side readout。

restore_labels:
    canonical_text_target 的 token ids。
    只监督 fusion -> restore head，不作为 L_align 的输入。
```

这些字段足够支持两个不依赖 fragment 词表的检查：

```text
1. text-only restore smoke test
2. non-vocab BaseLite warmup: L_restore + L_align
```

### 9.2 图接入后即可正式训练

只要 `repeat_unit_graphs.jsonl` 可用，即可追加图张量字段，并启动不依赖词表的正式第一阶段：

```python
{
    "node_features": FloatTensor[N_total, node_dim],
    "edge_index": LongTensor[2, E_total],
    "edge_features": FloatTensor[E_total, edge_dim],
    "graph_batch": LongTensor[N_total]
}
```

开启：

```text
L_restore
L_align
```

关闭：

```text
L_fragment_presence
L_fragment_consistency
```

### 9.3 fragment 词表稳定后

再追加：

```python
{
    "fragment_instances": List[List[FragmentInstance]],
    "fragment_presence_labels": FloatTensor[B, K]
}
```

---

## 10. 长度预算

raw SMILES 统计：

```text
推荐 max_seq_len: 512
最长 raw sample: test / ru_010959 / 366 tokens
```

模板定稿后建议重新统计：

```text
view1 length = tags + text_view_1
view2 length = tags + text_view_2
restore label length = canonical target + eos
```

第一版建议：

```yaml
max_seq_len_view: 512
max_seq_len_restore_label: 512
truncate: false
```

---

## 11. 阶段化实施方案

### Stage A：模板 preview

产物：

```text
data/baselite_smiles_v1/training_template_preview.jsonl
data/baselite_smiles_v1/training_template_stats.json
data/baselite_smiles_v1/training_template_report.md
```

验证：

```text
view template round-trip = 0 failure
restore label round-trip = 0 failure
restore label mask 正确
max length 明确
```

### Stage B：Text-only restore smoke test

目标：

```text
验证 Qwen tokenizer、LoRA、restore head、decode/eval、checkpoint 保存加载能跑通。
这是工程冒烟测试和 baseline，不是正式 BaseLite warmup 第一阶段。
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
```

建议：

```text
小样本 / 短步数
identity view 优先
只检查流程可运行和 loss 可下降
不要把该 checkpoint 当作正式底座
```

### Stage C：Non-vocab BaseLite warmup

目标：

```text
引入 repeat_unit_graph tensor，打通不依赖 fragment 词表的完整微调主链路。
这是当前正式第一阶段训练。
```

开启：

```text
L_restore
L_align
```

关闭：

```text
L_fragment_presence
L_fragment_consistency
fragment_vocab matcher
fragment labels
```

验证：

```text
restore valid / canonical match
text-to-graph retrieval top1 / top5
graph-to-text retrieval top1 / top5
checkpoint / adapter export
```

### Stage D：Fragment-aware warmup

目标：

```text
等待 fragment_vocab_v1 稳定后，接入 matcher 输出的 fragment_instances 和 fragment_presence_labels。
```

开启：

```text
L_restore
L_align
L_fragment_presence
L_fragment_consistency
```

---

## 12. 推荐采用的第一版模板

最终建议第一版固定为：

### Restore

输入：

```text
<polymer_view_smiles>
{text_view_1}
</polymer_view_smiles>
```

监督目标：

```text
{canonical_text_target}<|endoftext|>
```

### Representation View

```text
<polymer_smiles>
{text_view}
</polymer_smiles>
```

### Fragment Description Extension

```text
<fragment_description>
id: {fragment_id}
name: {fragment_name}
category: {category}
description: {description}
</fragment_description>
```

其中 Fragment Description Extension 不进入第一阶段训练，只作为后续显式 fragment-text 对齐方案保留。

---

## 13. 关键原则

1. `L_restore` 负责 canonical 输出能力，但不是唯一目标。
2. `L_align` 只使用 text projector / graph projector 输出，不经过 restore head。
3. `L_fragment_presence` 的标签不能写进 prompt。
4. `L_fragment_consistency` 的文本扰动不能破坏结构语义。
5. graph 和 fragment 是张量侧结构监督，不应被简化成纯文本 prompt。
6. 第一版不使用 chat template，不新增 special tokens。
7. 模板定稿后必须重新统计完整序列长度，再写训练 config。
