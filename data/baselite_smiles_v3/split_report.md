# BaseLite OMG v3 Dataset Split Report

- generated_at_utc: `2026-06-10T07:38:32.249854+00:00`
- source OMG CSV: `OMG_polymers.csv`
- dataset name: `baselite_smiles_v3`
- target count: `1000000`
- floor per reaction: `1000`
- split unit: `graph_hash`
- split counts: `{'train': 800000, 'valid': 100000, 'test': 100000}`

## Quality Checks

- total records: `1000000`
- unique record_id: `1000000`
- unique canonical_hash: `1000000`
- unique graph_hash: `1000000`
- canonical hash leakage: `0`
- graph hash leakage: `0`
- current dataset overlap by canonical_hash: `0`

## Reaction Counts

- reaction_idx `1`: selected `292740`, quota `292765`
- reaction_idx `2`: selected `21934`, quota `21944`
- reaction_idx `3`: selected `644751`, quota `644667`
- reaction_idx `4`: selected `15904`, quota `15904`
- reaction_idx `5`: selected `4441`, quota `4442`
- reaction_idx `6`: selected `8628`, quota `8628`
- reaction_idx `7`: selected `1254`, quota `1254`
- reaction_idx `8`: selected `3188`, quota `3188`
- reaction_idx `9`: selected `1632`, quota `1632`
- reaction_idx `10`: selected `873`, quota `876`
- reaction_idx `11`: selected `720`, quota `737`
- reaction_idx `12`: selected `1021`, quota `1021`
- reaction_idx `13`: selected `446`, quota `454`
- reaction_idx `14`: selected `40`, quota `43`
- reaction_idx `15`: selected `181`, quota `186`
- reaction_idx `16`: selected `732`, quota `744`
- reaction_idx `17`: selected `1515`, quota `1515`

## Quota Redistribution

- quota shortfalls after filtering: `{'10': 3, '11': 17, '13': 8, '14': 3, '15': 5, '16': 12}`
- replacement count: `48`
- replacement reaction counts: `{'3': 48}`

## Graph Hash Deduplication

- graph duplicate drop count: `57`
- graph replacement count: `57`
- graph replacement reaction counts: `{'3': 57}`
