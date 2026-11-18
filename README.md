# NSV Bronze-to-Silver Pipeline

This repository contains the Bronze-to-Silver NSV processing logic for one UPC or a sequential batch of UPCs. It includes execution wrappers, environment configuration, logging, and S3-based inputs and outputs.

## Scope

This project covers the Bronze-to-Silver layer. It does not include the full Gold layer.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run_pipeline.sh plan
./run_pipeline.sh run --zone B --phase 2 --cycle 1 --upc "N_07024_01001_GJ"
```

## Run a batch list

Each file in `batches/` contains one survey per line in this order:

```text
UPC ZONE PHASE CYCLE
```

Run a list sequentially on an EC2 instance:

```bash
chmod +x run_list.sh run_upc.sh
./run_list.sh batches/upcs_1.txt
```

The script continues to the next UPC if a UPC run fails, and returns a non-zero status if any UPC failed. It writes the batch execution log to the repository's local `logs/` directory and, after processing the full list, uploads that log with AWS CLI to the configured `BATCH_LOG_S3` destination. Local logs are retained. The batch command exits non-zero if the batch log upload fails, while preserving the local log for diagnosis.

The destination is configurable in `pipeline.env`:

```dotenv
BATCH_LOG_S3="${BATCH_LOG_S3:-s3://dhms-new-stgae/DHMS/NSV/logs}"
```

The log is uploaded with its existing filename, for example:

```text
s3://dhms-new-stgae/DHMS/NSV/logs/batch_20261118T092800Z.log
```

An exported `BATCH_LOG_S3` value can override the default. The EC2 instance must have AWS CLI installed, valid AWS credentials/instance-role access, and permission to write to the destination. If upload fails, the error is recorded in the local batch log and the command exits non-zero.

To distribute work across three instances, execute one batch list per instance:

```bash
# Instance 1
./run_list.sh batches/upcs_1.txt
# Instance 2
./run_list.sh batches/upcs_2.txt
# Instance 3
./run_list.sh batches/upcs_3.txt
```

## Environment settings

Runtime S3 paths and execution defaults are in `pipeline.env`. Important variables include `RAW_S3_ROOT`, `BRONZE_S3_ROOT`, `SILVER_S3_ROOT`, `TRACKER_S3`, `IMAGE_ROOT`, `BATCH_LOG_S3`, `ZONE`, `PHASE`, `CYCLE`, and `UPC`.

- `BATCH_LOG_S3`: S3 directory/prefix for completed batch logs. Defaults to `s3://dhms-new-stgae/DHMS/NSV/logs`.
- `TRACKER_S3`: tracker workbook S3 URI.
- `BRONZE_S3_ROOT`: root containing both Bronze source families.
- `SILVER_S3_ROOT`: Silver layer root.

## Operational path contract

Bronze inputs are organized under a root containing both source families:

```text
<BRONZE_ROOT>/
├── Source=NSV/Zone=<Z>/Phase=<P>/Cycle=<C>/UPC=<UPC>/...
└── Source=NSV_Backup/Zone=<Z>/Phase=<P>/Cycle=<C>/UPC=<UPC>/...
```

Silver outputs use the configured root, currently `s3://dhms-new-stgae/DHMS/NSV/Silver/`. Consolidated latest datasets are stored under `Silver/latest/`.

## Logging and reporting

Per-UPC logs and completed batch logs are retained locally under `logs/`. Each `run_list.sh` execution creates a uniquely named `batch_<UTC timestamp>.log`; after all UPCs finish, that file is copied to `BATCH_LOG_S3` using AWS CLI. The upload uses `aws s3 cp` and does not remove or move the local file. UPC failures do not stop subsequent entries, but any UPC failure or batch-log upload failure makes the overall command return non-zero.

## Operational guidance

For EC2 execution, install Python dependencies and AWS CLI, configure the instance role or credentials for required Bronze reads and Silver/log writes, and verify the configured tracker and S3 destinations are accessible before running a batch.
