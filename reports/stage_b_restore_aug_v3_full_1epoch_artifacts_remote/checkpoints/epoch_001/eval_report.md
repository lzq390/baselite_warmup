# Stage B Restore Full Eval Report

This checkpoint is a Stage B text-only restore training artifact.

- max epochs: `1`
- precision: `bf16`
- preview path: `data/baselite_smiles_aug_v3/training_template_preview.jsonl`

## Metrics

- `loss`: `0.005396987014536717`
- `token_accuracy`: `0.9980779826164246`
- `exact_string_match`: `0.96875`
- `rdkit_validity`: `1.0`
- `two_attachment_validity`: `1.0`
- `canonical_match`: `0.96875`
- `sample_count`: `10000`
- `decoded_sample_count`: `128`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 25, 'failed_count': 0, 'exact_string_match': 1.0, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 1.0}, 'direction_flip': {'sample_count': 26, 'failed_count': 0, 'exact_string_match': 1.0, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 1.0}, 'identity': {'sample_count': 26, 'failed_count': 0, 'exact_string_match': 1.0, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 1.0}, 'light_denoise': {'sample_count': 25, 'failed_count': 2, 'exact_string_match': 0.92, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 0.92}, 'rdkit_random_smiles': {'sample_count': 26, 'failed_count': 2, 'exact_string_match': 0.9230769230769231, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 0.9230769230769231}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.9686153846153847, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 0.9686153846153847, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `checkpoint_name`: `epoch_001`
- `checkpoint_epoch`: `1`
- `checkpoint_optimizer_step`: `250000`
- `checkpoint_recent_train_loss`: `0.004670290742069483`
- `checkpoint_epoch_train_loss_mean`: `0.030147588076369386`
- `formal_eval_full_decode`: `False`
- `full_epoch_decode`: `False`
