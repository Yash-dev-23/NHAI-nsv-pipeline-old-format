#!/usr/bin/env bash
# Run a batch of Bronze-to-Silver operations using the project shell conventions.
# This script does not change the transformation logic; it simply provides the
# standard wrapper expected by a production-ready project.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/pipeline.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

PYTHON="${PYTHON:-python3}"
export PYTHONPATH="${PYTHONPATH:-}${PYTHONPATH:+:}${ROOT}/src"

ROOT_DIR="${ROOT_DIR:-$ROOT/bronze}"
UPC_FILTER="${UPC_FILTER:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT_DIR="$2"
      shift 2
      ;;
    --upc)
      UPC_FILTER="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: ./run_batch.sh [--root /path/to/bronze-root] [--upc FILTER]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "$ROOT_DIR" ]]; then
  echo "ERROR: bronze root not found: $ROOT_DIR" >&2
  exit 2
fi

python3 -m ris_silver.io.batch_summary \
  --root "$ROOT_DIR" \
  --summary "$ROOT/logs/batch_summary.csv" \
  --zone "${ZONE:-B}" \
  --phase "${PHASE:-2}" \
  --cycle "${CYCLE:-1}" \
  --upc "$UPC_FILTER" \
  --status "QUEUED" \
  --notes "batch queued" 

echo "Batch summary written to $ROOT/logs/batch_summary.csv"
echo "Use ./run_pipeline.sh run --zone B --phase 2 --cycle 1 --upc <UPC> to execute a single UPC."
exit 0
