#!/usr/bin/env bash
# One UPC, bronze to silver, on EC2.
# S3 paths come from pipeline.env. Edit only ZONE, PHASE, CYCLE, and UPC.
# The pipeline keeps the latest year/month/day under Source=NSV and Source=NSV_Backup.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -a
# shellcheck disable=SC1091
source "${ROOT}/pipeline.env"
set +a

ZONE="B"
PHASE="1"
CYCLE="2"
UPC="N_04006_03001_GJ"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="${TMPDIR:-/tmp}/ris-silver/${ZONE}_${PHASE}_${CYCLE}_${UPC}"
LOCAL_BRONZE="${WORK}/bronze"
LOCAL_SILVER="${WORK}/silver"
LOCAL_TRACKER="${WORK}/tracker.xlsx"
PREFIX="Zone=${ZONE}/Phase=${PHASE}/Cycle=${CYCLE}/UPC=${UPC}"
LOG_NAME="${UPC}_Z${ZONE}_P${PHASE}_C${CYCLE}_${STAMP}.log"
LOG_FILE="${ROOT}/logs/${LOG_NAME}"
PIPELINE_STATUS="NOT_STARTED"

mkdir -p "${LOCAL_BRONZE}" "${LOCAL_SILVER}" "${WORK}/images" "${ROOT}/logs"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${LOG_FILE}"
}

count_named() {
  local root="$1"
  local name="$2"
  local under="${3:-}"
  if [[ ! -d "${root}" ]]; then
    echo 0
    return
  fi
  if [[ -n "${under}" ]]; then
    find "${root}" -type f -path "*/${under}/*" -name "${name}" | wc -l | tr -d ' '
  else
    find "${root}" -type f -name "${name}" | wc -l | tr -d ' '
  fi
}

list_named() {
  local root="$1"
  local name="$2"
  if [[ ! -d "${root}" ]]; then
    return
  fi
  find "${root}" -type f -name "${name}" | sort | while read -r path; do
    log "  $(wc -c < "${path}" | tr -d ' ') bytes  ${path#${root}/}"
  done
}

finish() {
  local code=$?
  log "---- summary ----"
  log "pipeline_status=${PIPELINE_STATUS} exit=${code}"
  log "bronze_parquet=$(count_named "${LOCAL_BRONZE}" '*.parquet')"
  log "silver_parquet_run_date=$(count_named "${LOCAL_SILVER}" '*.parquet' 'run_date=*')"
  log "silver_csv_run_date=$(count_named "${LOCAL_SILVER}" '*.csv' 'run_date=*')"
  log "silver_parquet_latest=$(count_named "${LOCAL_SILVER}" '*.parquet' 'latest')"
  log "silver_csv_latest=$(count_named "${LOCAL_SILVER}" '*.csv' 'latest')"
  if [[ -f "${LOG_FILE}" ]]; then
    log "stages reached:"
    grep -E '^(reference|facts|correction|canonical|hierarchy|enrich|master_chainage|publish|validate):' "${LOG_FILE}" | tee -a "${LOG_FILE}" || true
  fi
  if [[ -n "${LOG_DIR:-}" ]]; then
    aws s3 cp "${LOG_FILE}" "${LOG_DIR}/${LOG_NAME}" || log "log upload failed"
  fi
}
trap finish EXIT

log "start upc=${UPC} zone=${ZONE} phase=${PHASE} cycle=${CYCLE}"
log "bronze_nsv=${BRONZE_NSV_ROOT}"
log "bronze_backup=${BRONZE_NSV_BACKUP_ROOT}"
log "silver=${OUTPUT_ROOT}"
log "log_file=${LOG_FILE}"

log "STAGE sync_deliverables start"
aws s3 sync "${BRONZE_NSV_ROOT}/${PREFIX}/" "${LOCAL_BRONZE}/Source=NSV/${PREFIX}/" | tee -a "${LOG_FILE}"
log "STAGE sync_deliverables done parquet=$(count_named "${LOCAL_BRONZE}/Source=NSV" '*.parquet')"

log "STAGE sync_backup start"
aws s3 sync "${BRONZE_NSV_BACKUP_ROOT}/${PREFIX}/" "${LOCAL_BRONZE}/Source=NSV_Backup/${PREFIX}/" | tee -a "${LOG_FILE}"
log "STAGE sync_backup done parquet=$(count_named "${LOCAL_BRONZE}/Source=NSV_Backup" '*.parquet')"

log "STAGE tracker start"
if aws s3 cp "${TRACKER_S3}" "${LOCAL_TRACKER}" | tee -a "${LOG_FILE}"; then
  TRACKER_FILE="${LOCAL_TRACKER}"
  log "STAGE tracker done"
else
  TRACKER_FILE="${WORK}/missing_tracker.xlsx"
  log "STAGE tracker missing, CA defaults will be used"
fi

# Reader opens a local tree. Keep the S3 URIs only for sync and upload.
export BRONZE_S3_ROOT=""
export SILVER_S3_ROOT=""
export TRACKER_S3=""
export BRONZE_ROOT="${LOCAL_BRONZE}"
export SILVER_ROOT="${LOCAL_SILVER}"
export TRACKER_PATH="${TRACKER_FILE}"
export IMAGE_ROOT="${WORK}/images"
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
log "run_date parquet=$(count_named "${LOCAL_SILVER}" '*.parquet')"
log "run_date csv=$(count_named "${LOCAL_SILVER}" '*.csv')"
list_named "${LOCAL_SILVER}" '*.parquet'
list_named "${LOCAL_SILVER}" '*.csv'

log "STAGE upload_silver start ${OUTPUT_ROOT}"
aws s3 sync "${LOCAL_SILVER}/" "${OUTPUT_ROOT}/" | tee -a "${LOG_FILE}"
log "STAGE upload_silver done"
log "done upc=${UPC} zone=${ZONE} phase=${PHASE} cycle=${CYCLE}"
