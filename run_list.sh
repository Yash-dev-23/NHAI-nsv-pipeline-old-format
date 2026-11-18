#!/usr/bin/env bash
# Run surveys from a text file sequentially. Individual UPC failures do not stop the list.
# Each line: UPC ZONE PHASE CYCLE (or UPC only, using run_upc.sh defaults).
# Usage: ./run_list.sh batches/upcs_1.txt

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT}/pipeline.env}"
if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi
BATCH_LOG_S3="${BATCH_LOG_S3:-s3://dhms-new-stgae/DHMS/NSV/logs}"

LIST="${1:-}"
RUNNER="${RUN_UPC_BIN:-${ROOT}/run_upc.sh}"

if [[ -z "${LIST}" || ! -f "${LIST}" ]]; then
  echo "Usage: ./run_list.sh upcs.txt" >&2
  exit 2
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="${ROOT}/logs/batch_${STAMP}.log"
RUN_STARTED="$(date +%s)"
passed=0
failed=0
count=0
batch_exit=0

mkdir -p "${ROOT}/logs"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${LOG_FILE}"
}

format_elapsed() {
  local seconds="$1"
  printf '%02d:%02d:%02d (%ss)' "$((seconds / 3600))" "$(((seconds % 3600) / 60))" "$((seconds % 60))" "${seconds}"
}

log "start list=${LIST}"

while IFS= read -r line || [[ -n "${line}" ]]; do
  line="${line%%$'\r'}"
  [[ "${line}" =~ ^[[:space:]]*# ]] && continue
  read -r upc zone phase cycle <<< "${line}"
  [[ -z "${upc}" ]] && continue

  upc_started="$(date +%s)"
  if [[ -n "${zone}" ]]; then
    "${RUNNER}" "${upc}" "${zone}" "${phase}" "${cycle}"
    code=$?
    label="upc=${upc} zone=${zone} phase=${phase} cycle=${cycle}"
  else
    "${RUNNER}" "${upc}"
    code=$?
    label="upc=${upc}"
  fi
  upc_elapsed="$(( $(date +%s) - upc_started ))"
  count=$((count + 1))
  if [[ "${code}" -eq 0 ]]; then
    passed=$((passed + 1))
    log "${label} status=PASSED exit=0 elapsed=$(format_elapsed "${upc_elapsed}")"
  else
    failed=$((failed + 1))
    log "${label} status=FAILED exit=${code} elapsed=$(format_elapsed "${upc_elapsed}")"
  fi
done < "${LIST}"

if [[ "${failed}" -ne 0 ]]; then
  batch_status="FAILED"
  batch_exit=1
else
  batch_status="PASSED"
fi
log "run_elapsed=$(format_elapsed "$(( $(date +%s) - RUN_STARTED ))") upc_count=${count} passed=${passed} failed=${failed} batch_status=${batch_status}"
log "batch_log=${LOG_FILE}"

BATCH_LOG_TARGET="${BATCH_LOG_S3%/}/$(basename "${LOG_FILE}")"
log "batch_log_upload=STARTED destination=${BATCH_LOG_TARGET}"
if command -v aws >/dev/null 2>&1; then
  if aws s3 cp "${LOG_FILE}" "${BATCH_LOG_TARGET}"; then
    log "batch_log_upload=PASSED destination=${BATCH_LOG_TARGET}"
  else
    upload_code=$?
    log "batch_log_upload=FAILED exit=${upload_code} local_log=${LOG_FILE}"
    batch_exit=1
  fi
else
  log "batch_log_upload=FAILED reason=aws_cli_not_found local_log=${LOG_FILE}"
  batch_exit=1
fi

exit "${batch_exit}"
