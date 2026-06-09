# Stage B Restore Full Eval Report

This checkpoint is a Stage B text-only restore training artifact.

- max epochs: `20`
- precision: `bf16`
- preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`

## Metrics

- `loss`: `0.19977837758373454`
- `token_accuracy`: `0.9607569340725842`
- `exact_string_match`: `0.5044905008635578`
- `rdkit_validity`: `0.7449050086355786`
- `two_attachment_validity`: `0.7412780656303972`
- `canonical_match`: `0.5079447322970639`
- `sample_count`: `5790`
- `decoded_sample_count`: `5790`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 482, 'exact_string_match': 0.5794473229706391, 'rdkit_validity': 0.7668393782383419, 'two_attachment_validity': 0.7651122625215889, 'canonical_match': 0.5837651122625216}, 'direction_flip': {'sample_count': 1158, 'failed_count': 691, 'exact_string_match': 0.3998272884283247, 'rdkit_validity': 0.7063903281519862, 'two_attachment_validity': 0.6994818652849741, 'canonical_match': 0.40328151986183075}, 'identity': {'sample_count': 1158, 'failed_count': 316, 'exact_string_match': 0.7245250431778929, 'rdkit_validity': 0.8575129533678757, 'two_attachment_validity': 0.8540587219343696, 'canonical_match': 0.7271157167530224}, 'light_denoise': {'sample_count': 1158, 'failed_count': 663, 'exact_string_match': 0.42487046632124353, 'rdkit_validity': 0.7132987910189983, 'two_attachment_validity': 0.7098445595854922, 'canonical_match': 0.4274611398963731}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 697, 'exact_string_match': 0.39378238341968913, 'rdkit_validity': 0.6804835924006909, 'two_attachment_validity': 0.6778929188255614, 'canonical_match': 0.39810017271157166}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.5044905008635578, 'rdkit_validity': 0.7449050086355786, 'two_attachment_validity': 0.7412780656303972, 'canonical_match': 0.5079447322970638, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `train_loss_first_window`: `0.42757373270291066`
- `train_loss_last_window`: `0.017888869988237677`
- `train_loss_decreased`: `True`
- `completed_epochs`: `20`
- `optimizer_steps`: `57900`
- `train_sample_count`: `46320`
- `valid_sample_count`: `5790`
- `test_sample_count`: `5790`
- `early_stopped`: `False`
- `early_stop_reason`: `None`
- `early_stopping_monitor_only`: `True`
- `best_early_stopping_metric`: `0.1815412868028278`
- `best_early_stopping_checkpoint`: `epoch_010`
- `formal_eval_full_decode`: `True`
- `full_final_decode`: `True`
- `all_view_test_loss`: `0.19364622525406813`
- `all_view_test_canonical_match`: `0.5188255613126079`
- `identity_test_loss`: `0.19364622525406813`
- `identity_test_canonical_match`: `0.5188255613126079`
