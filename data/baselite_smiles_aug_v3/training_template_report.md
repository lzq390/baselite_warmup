# BaseLite Stage B Restore v3 OMG Five-view Template Report

- generated_at_utc: `2026-06-10T18:56:48.406637+00:00`
- dataset_dir: `data/baselite_smiles_v3`
- graph_path: `data/processed/omg_repeat_unit_graphs_v3.jsonl`
- output_dir: `data/baselite_smiles_aug_v3`
- augmentation_policy: `restore_aug_v3`
- base records: `1000000`
- training rows: `5000000`
- expected training rows: `5000000`

## Strategy Counts

- `attachment_rooted_smiles`: `1000000`
- `direction_flip`: `1000000`
- `identity`: `1000000`
- `light_denoise`: `1000000`
- `rdkit_random_smiles`: `1000000`

## Quality Checks

- augmentation failures: `0`
- input-label conflicts: `0`
- record strategy bad count: `0`
- view roundtrip failures: `0`
- restore roundtrip failures: `0`
- view length overflow: `0`
- restore label length overflow: `0`

## Length Summary

- `train` view p95/max: `69` / `168`; restore p95/max: `52` / `128`
- `valid` view p95/max: `69` / `171`; restore p95/max: `52` / `131`
- `test` view p95/max: `69` / `162`; restore p95/max: `52` / `126`
