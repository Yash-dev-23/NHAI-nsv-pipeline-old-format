#!/usr/bin/env bash
# Derive per-survey S3 destinations only after Zone/Phase/Cycle/UPC are resolved.
# OUTPUT_ROOT is the Silver layer base; partition values come from the current run.

resolve_runtime_s3_paths() {
  local base="${OUTPUT_ROOT:-${SILVER_S3_ROOT:-}}"
  if [[ -z "${base}" ]]; then
    echo "ERROR: OUTPUT_ROOT and SILVER_S3_ROOT are both empty" >&2
    return 2
  fi
  base="${base%/}"

  local upc_key="${UPC//\//-}"
  upc_key="${upc_key//_/-}"
  while [[ "${upc_key}" == -* ]]; do upc_key="${upc_key#-}"; done
  while [[ "${upc_key}" == *- ]]; do upc_key="${upc_key%-}"; done

  SILVER_UPC_ROOT="${base}/zone=${ZONE}/phase=${PHASE}/cycle=${CYCLE}/${upc_key}"
  SILVER_DATA_OUTPUT_DIR="${SILVER_UPC_ROOT}/dlm_kpi_new"
  LOG_DIR="${SILVER_UPC_ROOT}"
  RUN_LOG_S3="${SILVER_UPC_ROOT}/run.log"
  UPC_LOG_S3="${LOG_DIR}/${LOG_NAME}"
  OUTPUT_ROOT="${base}"
  export SILVER_UPC_ROOT SILVER_DATA_OUTPUT_DIR LOG_DIR RUN_LOG_S3 UPC_LOG_S3 OUTPUT_ROOT
}
