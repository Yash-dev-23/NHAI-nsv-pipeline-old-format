#!/usr/bin/env bash
# One UPC, Bronze to Silver, on EC2.
# A list runner passes UPC, ZONE, PHASE, CYCLE; no-argument execution preserves
# the standalone defaults below.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -a
# shellcheck disable=SC1091
source "${ROOT}/pipeline.env"
set +a
# shellcheck disable=SC1091
source "${ROOT}/scripts/runtime_paths.sh"

# Preserve the existing standalone execution defaults.
ZONE="B"
PHASE="1"
CYCLE="2"
UPC="N_02001_09001_RJ"
if [[ $# -ge 1 && -n "${1}" ]]; then UPC="$1"; fi
if [[ $# -ge 2 && -n "${2}" ]]; then ZONE="$2"; fi
if [[ $# -ge 3 && -n "${3}" ]]; then PHASE="$3"; fi
if [[ $# -ge 4 && -n "${4}" ]]; then CYCLE="$4"; fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="${TMPDIR:-/tmp}/ris-silver/${ZONE}_${PHASE}_${CYCLE}_${UPC}"
LOCAL_BRONZE="${WORK}/bronze"
LOCAL_SILVER="${WORK}/silver"
LOCAL_TRACKER="${WORK}/tracker.xlsx"
PREFIX="Zone=${ZONE}/Phase=${PHASE}/Cycle=${CYCLE}/UPC=${UPC}"
LOG_NAME="${UPC}_Z${ZONE}_P${PHASE}_C${CYCLE}_${STAMP}.log"
LOG_FILE="${ROOT}/logs/${LOG_NAME}"
PIPELINE_STATUS="NOT_STARTED"
RUN_STARTED="$(date +%s)"

# Crucially, resolve S3 paths after command-line values have replaced defaults.
resolve_runtime_s3_paths
BRONZE_NSV_UPC_S3="${BRONZE_NSV_ROOT%/}/${PREFIX}"
BRONZE_BACKUP_UPC_S3="${BRONZE_NSV_BACKUP_ROOT%/}/${PREFIX}"

mkdir -p "${LOCAL_BRONZE}" "${LOCAL_SILVER}" "${ROOT}/logs"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${LOG_FILE}"
}

format_elapsed() {
  local seconds="$1"
  printf '%02d:%02d:%02d (%ss)' "$((seconds / 3600))" "$(((seconds % 3600) / 60))" "$((seconds % 60))" "${seconds}"
}

count_named() {
  local root="$1"
  local name="$2"
  local under="${3:-}"
  if [[ ! -d "${root}" ]]; then echo 0; return; fi
  if [[ -n "${under}" ]]; then
    find "${root}" -type f -path "*/${under}/*" -name "${name}" | wc -l | tr -d ' '
  else
    find "${root}" -type f -name "${name}" | wc -l | tr -d ' '
  fi
}

list_named() {
  local root="$1"
  local name="$2"
  [[ -d "${root}" ]] || return
  find "${root}" -type f -name "${name}" | sort | while read -r path; do
    log "  $(wc -c < "${path}" | tr -d ' ') bytes  ${path#${root}/}"
  done
}

finish() {
  local code=$?
  log "---- summary ----"
  log "pipeline_status=${PIPELINE_STATUS} exit=${code}"
  log "upc_elapsed=$(format_elapsed "$(( $(date +%s) - RUN_STARTED ))")"
  log "bronze_parquet=$(count_named "${LOCAL_BRONZE}" '*.parquet')"
  log "silver_parquet=$(count_named "${LOCAL_SILVER}" '*.parquet')"
  log "silver_csv=$(count_named "${LOCAL_SILVER}" '*.csv')"
  if [[ -f "${LOG_FILE}" ]]; then
    log "stages reached:"
    grep -E '^(reference|facts|correction|canonical|hierarchy|enrich|master_chainage|publish|validate):' "${LOG_FILE}" | tee -a "${LOG_FILE}" || true
  fi
  if [[ -n "${LOG_DIR:-}" ]]; then
    log "upc_log_upload=STARTED destination=${UPC_LOG_S3}"
    if aws s3 cp "${LOG_FILE}" "${UPC_LOG_S3}"; then
      log "upc_log_upload=PASSED destination=${UPC_LOG_S3}"
    else
      local upload_code=$?
      log "upc_log_upload=FAILED exit=${upload_code} local_log=${LOG_FILE}"
    fi
  fi
}
trap finish EXIT

log "resolved_run zone=${ZONE} phase=${PHASE} cycle=${CYCLE} upc=${UPC}"
log "resolved_s3 bronze_nsv=${BRONZE_NSV_UPC_S3}"
log "resolved_s3 bronze_backup=${BRONZE_BACKUP_UPC_S3}"
log "resolved_s3 tracker=${TRACKER_S3}"
log "resolved_s3 silver_layer_root=${OUTPUT_ROOT}"
log "resolved_s3 silver_upc_root=${SILVER_UPC_ROOT}"
log "resolved_s3 silver_data_output=${SILVER_DATA_OUTPUT_DIR}"
log "resolved_s3 upc_log=${UPC_LOG_S3}"
log "resolved_s3 batch_logs=${BATCH_LOG_S3:-}"
log "resolved_local intermediate_workspace=${WORK}"
log "local_log=${LOG_FILE}"

log "STAGE sync_deliverables start"
aws s3 sync "${BRONZE_NSV_UPC_S3}/" "${LOCAL_BRONZE}/Source=NSV/${PREFIX}/" | tee -a "${LOG_FILE}"
log "STAGE sync_deliverables done parquet=$(count_named "${LOCAL_BRONZE}/Source=NSV" '*.parquet')"

log "STAGE sync_backup start"
aws s3 sync "${BRONZE_BACKUP_UPC_S3}/" "${LOCAL_BRONZE}/Source=NSV_Backup/${PREFIX}/" | tee -a "${LOG_FILE}"
log "STAGE sync_backup done parquet=$(count_named "${LOCAL_BRONZE}/Source=NSV_Backup" '*.parquet')"

log "STAGE tracker start source=${TRACKER_S3}"
if aws s3 cp "${TRACKER_S3}" "${LOCAL_TRACKER}" | tee -a "${LOG_FILE}"; then
  TRACKER_FILE="${LOCAL_TRACKER}"
  log "STAGE tracker done local=${TRACKER_FILE}"
else
  TRACKER_FILE="${WORK}/missing_tracker.xlsx"
  log "STAGE tracker missing source=${TRACKER_S3}; pipeline may use defaults"
fi

# Python reads a local tree. S3 URIs are used only by the shell sync/upload steps.
# Images are the jpg/png files already inside this UPC's NSV deliverables, including D3.
export BRONZE_S3_ROOT=""
export SILVER_S3_ROOT=""
export TRACKER_S3=""
export BRONZE_ROOT="${LOCAL_BRONZE}"
export SILVER_ROOT="${LOCAL_SILVER}"
export TRACKER_PATH="${TRACKER_FILE}"
export IMAGE_ROOT="${LOCAL_BRONZE}/Source=NSV/${PREFIX}"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONUNBUFFERED=1

log "STAGE pipeline start"
PIPELINE_STATUS="RUNNING"
cd "${ROOT}"
set +e
python3 -m ris_silver run --zone "${ZONE}" --phase "${PHASE}" --cycle "${CYCLE}" --upc "${UPC}" 2>&1 | tee -a "${LOG_FILE}"
PIPELINE_CODE=${PIPESTATUS[0]}
set -e
if [[ "${PIPELINE_CODE}" -ne 0 ]]; then
  PIPELINE_STATUS="FAILED"
  log "STAGE pipeline failed exit=${PIPELINE_CODE}"
  exit "${PIPELINE_CODE}"
fi
PIPELINE_STATUS="PASSED"
log "STAGE pipeline done"

log "STAGE silver_files"
log "silver parquet=$(count_named "${LOCAL_SILVER}" '*.parquet')"
log "silver csv=$(count_named "${LOCAL_SILVER}" '*.csv')"
list_named "${LOCAL_SILVER}" '*.parquet'
list_named "${LOCAL_SILVER}" '*.csv'

# The local tree already contains zone/phase/cycle/UPC partitions. Sync at the
# Silver layer root to avoid nesting those partitions twice.
log "STAGE upload_silver start source=${LOCAL_SILVER}/ destination=${OUTPUT_ROOT}/"
aws s3 sync "${LOCAL_SILVER}/" "${OUTPUT_ROOT}/" | tee -a "${LOG_FILE}"
log "STAGE upload_silver done destination=${OUTPUT_ROOT}/"
log "done upc=${UPC} zone=${ZONE} phase=${PHASE} cycle=${CYCLE}"
