# BaseLite OMG v3 Stage C Non-vocab Dataset Audit

- generated_at_utc: `2026-06-10T09:21:39.203105+00:00`
- dataset_dir: `data/baselite_smiles_v3`
- graph_path: `data/processed/omg_repeat_unit_graphs_v3.jsonl`
- dataset rows: `1000000`
- graph rows: `1000000`
- split counts: `{'train': 800000, 'valid': 100000, 'test': 100000}`

## Join Quality

- missing graph by record_id: `0`
- missing graph by canonical_hash: `0`
- canonical hash mismatches: `0`
- extra graph records: `0`

## Graph Feature Schema

- node feature dim: `25`
- edge feature dim: `7`
- node categorical sizes: `{'element': 11, 'hybridization': 5, 'attachment_role': 3}`
- edge categorical sizes: `{'bond_type': 4}`

## Stage C Scope

- Opens `L_restore` and `L_align`.
- Closes fragment vocab, fragment matcher, fragment presence, and fragment consistency.
- Graph tensors are represented by the graph JSONL sidecar.
