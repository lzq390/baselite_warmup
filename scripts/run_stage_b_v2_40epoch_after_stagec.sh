#!/usr/bin/env bash
set -euo pipefail

STAGE_C_ROOT="${STAGE_C_ROOT:-/root/autodl-tmp/baselite_stage_c_aug_v2}"
STAGE_B_ROOT="${STAGE_B_ROOT:-/root/autodl-tmp/baselite_stage_b_restore_aug_v2}"
WORK_DIR="${WORK_DIR:-${STAGE_B_ROOT}/work}"
MODEL_DIR="${MODEL_DIR:-${STAGE_B_ROOT}/models/Qwen2.5-7B}"
PYTHON_BIN="${PYTHON_BIN:-/root/miniconda3/bin/python}"
LOG_DIR="${LOG_DIR:-${STAGE_B_ROOT}/logs/stage_b_v2_40epoch_after_stagec}"
WAIT_INTERVAL_SECONDS="${WAIT_INTERVAL_SECONDS:-300}"

mkdir -p "${LOG_DIR}"

log() {
  printf '[%s] %s\n' "$(date -Iseconds)" "$*"
}

stage_c_running() {
  pgrep -f 'train_stage_c_non_vocab_.*\.py' >/dev/null 2>&1 && return 0
  pgrep -f 'run_stagec_30epoch\.sh' >/dev/null 2>&1 && return 0
  pgrep -f 'stagec_30epoch' >/dev/null 2>&1 && return 0
  return 1
}

wait_for_stage_c() {
  log "waiting for Stage C jobs to finish before starting Stage B 40epoch runs"
  while stage_c_running; do
    log "Stage C still running; sleeping ${WAIT_INTERVAL_SECONDS}s"
    sleep "${WAIT_INTERVAL_SECONDS}"
  done
  log "Stage C appears finished; starting Stage B 40epoch sequential runs"
}

run_stage_b() {
  local name="$1"
  local script="$2"
  local config="$3"
  local output_dir="$4"
  local log_file="${LOG_DIR}/${name}_$(date +%Y%m%d_%H%M%S).log"

  cd "${WORK_DIR}"
  if [[ -f "${output_dir}/eval_metrics.json" ]]; then
    log "${name} already has eval_metrics.json; skipping"
    return 0
  fi
  if [[ -d "${output_dir}" ]]; then
    log "${name} output directory exists without eval_metrics.json: ${output_dir}"
    log "refusing to append to a partial run"
    return 2
  fi

  log "run=${name}"
  "${PYTHON_BIN}" "${script}" \
    --config "${config}" \
    --model-name-or-path "${MODEL_DIR}" \
    --eval-preview-path data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl \
    --eval-output-prefix robustness \
    2>&1 | tee "${log_file}"
  log "${name} finished successfully"
}

main() {
  log "Stage B v2 40epoch after-Stage-C launcher started"
  log "stage_c_root=${STAGE_C_ROOT}"
  log "stage_b_work=${WORK_DIR}"
  log "model_dir=${MODEL_DIR}"
  wait_for_stage_c
  run_stage_b \
    "stage_b_restore_aug_v2_full_40epoch" \
    "scripts/train_stage_b_restore_full.py" \
    "configs/stage_b_restore_aug_v2_full_40epoch_bf16.yaml" \
    "outputs/stage_b_restore_aug_v2_full_40epoch"
  run_stage_b \
    "stage_b_restore_aug_v2_curriculum_full_40epoch" \
    "scripts/train_stage_b_restore_curriculum.py" \
    "configs/stage_b_restore_aug_v2_curriculum_full_40epoch_bf16.yaml" \
    "outputs/stage_b_restore_aug_v2_curriculum_full_40epoch"
  log "Stage B v2 40epoch sequential training completed"
}

main "$@"
