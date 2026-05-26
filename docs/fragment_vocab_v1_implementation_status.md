# fragment_vocab_v1 implementation status

本文档记录 `fragment_vocab_v1` 当前实现状态，避免把规划文档误读为已完成流水线。

## 当前状态

```text
status: specification_only
data_available: data/all_polymers_experiment_final.csv
cleaning_pipeline: not_implemented
canonicalizer: not_implemented
repeat_unit_graph_builder: not_implemented
fragment_matcher: not_implemented
seed_vocab: not_created
candidate_vocab: not_created
validation_reports: not_created
```

当前仓库已有：

```text
docs/fragment_vocab_construction_1_m_smiles_v_1.md
docs/fragment_vocab_v1_schema_fields.md
docs/fragment_vocab_repeat_unit_graph_matching_rules_v_1.md
docs/fragment_vocab_validation_workflow_v_1_md.md
data/all_polymers_experiment_final.csv
```

当前仓库尚未生成：

```text
data/processed/clean_polymer_strings_main.jsonl
data/processed/property_records_by_polymer.jsonl
data/processed/canonical_repeat_units.jsonl
data/processed/repeat_unit_graphs.jsonl
data/processed/graph_failed_cases.jsonl
fragments/seeds/seed_fragment_rules_v0.jsonl
fragments/mining/mined_motif_candidates.jsonl
fragments/vocab/fragment_vocab_v1.0.jsonl
fragments/vocab/fragment_vocab_v1.0.stats.json
fragments/vocab/fragment_vocab_v1.0.examples.jsonl
fragments/validation/fragment_vocab_v1.0.validation_report.md
```

## 已锁定的文档口径

```text
1. attachment normalization 必须包含 [[[*]]] -> * 与 [[*]] -> *。
2. [R] / [R1] / [R2] 等未定义 R 基默认进入 unresolved_R_group。
3. 当前 CSV 的临时 level 2 主构建集口径为 12,184 个 attachment-normalized two-attachment main unique strings。
4. SMARTS 规则必须使用 atom map number，atom_roles key 必须是 map id 字符串。
5. split 必须按 unique polymer identity / canonical graph identity 进行，禁止按 CSV row 切分。
```

## 下一步实现顺序

```text
Phase 0:
  implement data audit and cleaning script
  output record_type buckets
  output level 1-2 exact counts and dataset hash

Phase 1:
  implement canonicalizer and repeat_unit_graph builder
  output level 3-5 counts
  freeze split by graph identity

Phase 2:
  create seed_fragment_rules_v0.jsonl
  validate schema and SMARTS compile

Phase 3:
  run motif mining and coverage analysis

Phase 4:
  produce fragment_vocab_v1_candidate.jsonl and validation reports
```
