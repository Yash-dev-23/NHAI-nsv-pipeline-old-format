#!/usr/bin/env bash
# Run the surveys in a text file, one after another.
# One survey failing does not stop the rest.
# Each line is: UPC ZONE PHASE CYCLE
# A line with only a UPC uses the ZONE, PHASE, and CYCLE set in run_upc.sh.
# Usage: ./run_list.sh batches/upcs_1.txt

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

log "run_elapsed=$(format_elapsed "$(( $(date +%s) - RUN_STARTED ))") upc_count=${count} passed=${passed} failed=${failed}"
log "batch_log=${LOG_FILE}"

if [[ "${failed}" -ne 0 ]]; then
  exit 1
fi
exit 0
