# Stage B v3 checkpoint full-decode test evaluation

Generated: 2026-06-15 Asia/Shanghai

## Summary

| eval set | rows decoded | loss | token acc | canonical match | exact match | RDKit valid | two attachment |
|---|---:|---:|---:|---:|---:|---:|---:|
| V2 curated test | 5,790 | 0.982028 | 83.34% | 17.65% | 16.61% | 44.47% | 42.56% |
| V3 OMG test | 500,000 | 0.006074 | 99.80% | 93.99% | 93.88% | 98.57% | 98.54% |

## V3 test by strategy

| strategy | rows | canonical match | RDKit valid | two attachment | failed |
|---|---:|---:|---:|---:|---:|
| attachment_rooted_smiles | 100,000 | 99.45% | 99.85% | 99.84% | 547 |
| direction_flip | 100,000 | 97.75% | 99.22% | 99.19% | 2,248 |
| identity | 100,000 | 99.43% | 99.85% | 99.84% | 568 |
| light_denoise | 100,000 | 84.66% | 97.46% | 97.45% | 15,338 |
| rdkit_random_smiles | 100,000 | 88.66% | 96.45% | 96.36% | 11,336 |

## V2 curated test by strategy

| strategy | rows | canonical match | RDKit valid | two attachment | failed |
|---|---:|---:|---:|---:|---:|
| attachment_rooted_smiles | 1,158 | 18.74% | 42.92% | 40.76% | 941 |
| direction_flip | 1,158 | 12.09% | 41.62% | 39.38% | 1,018 |
| identity | 1,158 | 29.19% | 51.81% | 50.09% | 820 |
| light_denoise | 1,158 | 14.59% | 42.57% | 41.71% | 989 |
| rdkit_random_smiles | 1,158 | 13.64% | 43.44% | 40.85% | 1,000 |

## Failure mix

| eval set | correct | valid wrong canonical | invalid SMILES | attachment error |
|---|---:|---:|---:|---:|
| V2 curated test | 1,022 | 1,442 | 3,215 | 111 |
| V3 OMG test | 469,963 | 22,730 | 7,166 | 141 |

## Interpretation

- V3 full-decode result is strong on in-distribution OMG v3 test: 93.99% canonical match across 500,000 decoded rows.
- Strategy-level weakness is concentrated in light_denoise and rdkit_random_smiles; identity and attachment_rooted_smiles are both above 99.4%.
- V2 curated test transfer is poor: only 17.65% canonical match, 44.47% RDKit validity, and 42.56% two-attachment validity.
- The V2 failure indicates OMG v3 warmup alone should not replace curated Stage B training; use it as large-scale pretraining/warmup, then continue fine-tuning/evaluating on curated v2/v1 data.
