# Stage B Restore Full Eval Report

This checkpoint is a Stage B text-only restore training artifact.

- max epochs: `40`
- precision: `bf16`
- preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`

## Metrics

- `loss`: `0.19286947233593507`
- `token_accuracy`: `0.965566658577359`
- `exact_string_match`: `0.5438687392055268`
- `rdkit_validity`: `0.78566493955095`
- `two_attachment_validity`: `0.7815198618307426`
- `canonical_match`: `0.5459412780656304`
- `sample_count`: `5790`
- `decoded_sample_count`: `5790`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 443, 'exact_string_match': 0.613126079447323, 'rdkit_validity': 0.802245250431779, 'two_attachment_validity': 0.7996545768566494, 'canonical_match': 0.6174438687392055}, 'direction_flip': {'sample_count': 1158, 'failed_count': 633, 'exact_string_match': 0.45077720207253885, 'rdkit_validity': 0.7487046632124352, 'two_attachment_validity': 0.7452504317789291, 'canonical_match': 0.4533678756476684}, 'identity': {'sample_count': 1158, 'failed_count': 300, 'exact_string_match': 0.7400690846286702, 'rdkit_validity': 0.8773747841105354, 'two_attachment_validity': 0.8765112262521589, 'canonical_match': 0.7409326424870466}, 'light_denoise': {'sample_count': 1158, 'failed_count': 598, 'exact_string_match': 0.4835924006908463, 'rdkit_validity': 0.7677029360967185, 'two_attachment_validity': 0.7642487046632125, 'canonical_match': 0.4835924006908463}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 655, 'exact_string_match': 0.4317789291882556, 'rdkit_validity': 0.7322970639032815, 'two_attachment_validity': 0.7219343696027634, 'canonical_match': 0.43436960276338515}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.5438687392055268, 'rdkit_validity': 0.7856649395509498, 'two_attachment_validity': 0.7815198618307427, 'canonical_match': 0.5459412780656304, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `train_loss_first_window`: `0.250613576484571`
- `train_loss_last_window`: `0.00944009794755536`
- `train_loss_decreased`: `True`
- `completed_epochs`: `40`
- `optimizer_steps`: `115800`
- `train_sample_count`: `46320`
- `valid_sample_count`: `5790`
- `test_sample_count`: `5790`
- `early_stopped`: `False`
- `early_stop_reason`: `None`
- `early_stopping_monitor_only`: `True`
- `best_early_stopping_metric`: `0.5459412780656304`
- `best_early_stopping_checkpoint`: `epoch_040`
- `formal_eval_full_decode`: `True`
- `full_final_decode`: `True`
- `all_view_test_loss`: `0.1954279164021967`
- `all_view_test_canonical_match`: `0.5385146804835924`
- `identity_test_loss`: `0.1954279164021967`
- `identity_test_canonical_match`: `0.5385146804835924`
