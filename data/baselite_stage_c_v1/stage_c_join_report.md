# BaseLite Stage C Non-vocab Dataset Audit

- generated_at_utc: `2026-05-25T07:31:54.208883+00:00`
- dataset_dir: `/home/lzq390/gith/baselite_warmup/data/baselite_smiles_v1`
- graph_path: `/home/lzq390/gith/baselite_warmup/data/processed/repeat_unit_graphs.jsonl`
- dataset rows: `11580`
- graph rows: `11580`
- split counts: `{'train': 9264, 'valid': 1158, 'test': 1158}`

## Join Quality

- missing graph by record_id: `0`
- missing graph by canonical_hash: `0`
- canonical hash mismatches: `0`
- extra graph records: `0`

## Graph Feature Schema

- node feature dim: `38`
- edge feature dim: `7`
- node categorical sizes: `{'element': 24, 'hybridization': 5, 'attachment_role': 3}`
- edge categorical sizes: `{'bond_type': 4}`

## Stage C Scope

- Opens `L_restore` and `L_align`.
- Closes fragment vocab, fragment matcher, fragment presence, and fragment consistency.
- This audit does not copy graph tensors; training reads the canonical dataset and graph JSONL sources.
