# Stage B Restore Full Eval Report

This checkpoint is a Stage B text-only restore training artifact.

- max epochs: `1`
- precision: `bf16`
- preview path: `data/baselite_smiles_aug_v3/training_template_preview.jsonl`

## Metrics

- `loss`: `0.006177950955105677`
- `token_accuracy`: `0.9979487998590469`
- `exact_string_match`: `0.96875`
- `rdkit_validity`: `1.0`
- `two_attachment_validity`: `1.0`
- `canonical_match`: `0.96875`
- `sample_count`: `500000`
- `decoded_sample_count`: `128`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 25, 'failed_count': 0, 'exact_string_match': 1.0, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 1.0}, 'direction_flip': {'sample_count': 26, 'failed_count': 0, 'exact_string_match': 1.0, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 1.0}, 'identity': {'sample_count': 26, 'failed_count': 0, 'exact_string_match': 1.0, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 1.0}, 'light_denoise': {'sample_count': 25, 'failed_count': 2, 'exact_string_match': 0.92, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 0.92}, 'rdkit_random_smiles': {'sample_count': 26, 'failed_count': 2, 'exact_string_match': 0.9230769230769231, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 0.9230769230769231}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.9686153846153847, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 0.9686153846153847, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `train_loss_first_window`: `0.10176681501556442`
- `train_loss_last_window`: `0.008207843565674302`
- `train_loss_decreased`: `True`
- `completed_epochs`: `1`
- `optimizer_steps`: `250000`
- `train_sample_count`: `4000000`
- `valid_sample_count`: `500000`
- `test_sample_count`: `500000`
- `early_stopped`: `False`
- `early_stop_reason`: `None`
- `early_stopping_monitor_only`: `True`
- `best_early_stopping_metric`: `None`
- `best_early_stopping_checkpoint`: `None`
- `formal_eval_full_decode`: `False`
- `full_final_decode`: `False`
- `all_view_test_loss`: `0.006055140897246442`
- `all_view_test_canonical_match`: `0.90625`
- `identity_test_loss`: `0.006055140897246442`
- `identity_test_canonical_match`: `0.90625`
