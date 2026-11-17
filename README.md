# NSV Bronze-to-Silver Pipeline

This repository contains the Bronze-to-Silver NSV processing logic for one UPC or a batch of UPCs. It preserves the existing Bronze-to-Silver transformation code while adding a project shell that matches the engineering conventions used in the working reference pipeline.

## Scope

This project is intentionally scoped to the Bronze-to-Silver layer only. It does not include the full end-to-end Gold layer or the full reference orchestration model, but it follows the same operational conventions around:

- project-level documentation
- root environment configuration
- execution wrappers
- logs and status reporting
- EC2-friendly setup instructions
- batch and one-UPC execution

## Repository layout

```text
NHAI-nsv-pipeline-old-format_bronze_to_silver/
├── README.md
├── requirements.txt
├── pipeline.env
├── run_pipeline.sh
├── run_batch.sh
├── EC2_RUN.md
├── logs/
├── tools/
├── bronze/
├── config/
├── silver_tables/
├── src/
├── tests/
├── .gitignore
├── pyproject.toml
└── ...
```

## Quick start

```bash
cd /home/softsensor/Desktop/New\ Folder\ 1/NHAI-nsv-pipeline-old-format_bronze_to_silver
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run_pipeline.sh plan
./run_pipeline.sh run --zone B --phase 2 --cycle 1 --upc "N_07024_01001_GJ"
```

## Batch execution

```bash
./run_batch.sh --root /home/softsensor/Desktop/New\ Folder\ 1/NHAI-nsv-pipeline-old-format_bronze_to_silver/bronze --upc "N_07024_01001_GJ"
```

## Environment settings

The runtime values are loaded from `pipeline.env` and may be overridden by command-line arguments.

Key variables:

- `PROJECT_ROOT`
- `RAW_S3_ROOT`
- `BRONZE_ROOT`
- `BRONZE_NSV_ROOT`
- `BRONZE_NSV_BACKUP_ROOT`
- `SILVER_S3_ROOT`
- `SILVER_ROOT`
- `LOG_DIR`
- `IMAGE_ROOT`
- `TRACKER_PATH`
- `ZONE`
- `PHASE`
- `CYCLE`
- `UPC`

## Operational path contract

The repo expects the Bronze data to be organized under a root that contains both source families:

```text
<BRONZE_ROOT>/
├── Source=NSV/
│   └── Zone=<Z>/Phase=<P>/Cycle=<C>/UPC=<UPC>/...
├── Source=NSV_Backup/
│   └── Zone=<Z>/Phase=<P>/Cycle=<C>/UPC=<UPC>/...
└── ...
```

Concrete S3 example:

```text
s3://nhai-dhms-uat/databricks-nsv-downloads/final_bronze_output/
├── Source=NSV/
│   └── Zone=A/Phase=1/Cycle=1/UPC=N_01001_01001_HR/...
├── Source=NSV_Backup/
│   └── Zone=A/Phase=1/Cycle=1/UPC=N_01001_01001_HR/...
└── ...
```

The Silver output root is:

```text
s3://dhms-new-stgae/DHMS/NSV/Silver/
```

For EC2 execution, the usual mounted equivalent is:

```text
/mnt/data/final_bronze_output/
├── Source=NSV/
│   └── Zone=A/Phase=1/Cycle=1/UPC=.../...
├── Source=NSV_Backup/
│   └── Zone=A/Phase=1/Cycle=1/UPC=.../...
├── /mnt/data/silver_tables
├── /mnt/data/logs
├── /mnt/data/images
├── /mnt/data/NSV_Activity_Tracker_ZoneWise_Standardized_17072026.xlsx
└── ...
```

## Logging and reporting

Runs are expected to be recorded under the `logs/` directory. Batch summaries are appended to
`logs/batch_summary.csv` and the output contract excludes the `issue_code` column.

## Execution notes

- The business logic in the existing Bronze-to-Silver pipeline is preserved.
- The project shell is aligned to the reference deployment pattern without changing the underlying transformation code.
- This repository is not a full Gold pipeline; it remains a Bronze-to-Silver implementation.
- The pipeline is intentionally path-aware and environment-driven rather than hardcoded to a machine-specific filesystem.

## Operational guidance

For production execution on EC2, use the guidance in `EC2_RUN.md` and ensure:

- Python dependencies are installed in a virtual environment
- `RAW_S3_ROOT`, `BRONZE_ROOT`, `SILVER_ROOT`, `LOG_DIR`, `IMAGE_ROOT`, and `TRACKER_PATH` are set correctly in `pipeline.env`
- the tracker file path is valid for the selected run
- the Bronze input tree matches the expected `Source=NSV` / `Source=NSV_Backup` layout
- the output path is writable and follows the project partition pattern
