"""Publish one UPC / phase / cycle partition in dlm_kpi_new.

Each table is published as an S3-like object pair:
    <silver_root>/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/dlm_kpi_new/<table>.parquet
    <silver_root>/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/dlm_kpi_new/<table>.csv
"""

from __future__ import annotations

from pathlib import Path

from ris_silver.app import PathsMissing
from ris_silver.context import RunContext
from ris_silver.io.paths import silver_partition_dir


def publish(ctx: RunContext, tables: dict | None = None) -> dict[str, int]:
    """Write each Silver table into the UPC's dlm_kpi_new directory."""
    if not ctx.silver_root:
        raise PathsMissing("paths.silver_root is empty")
    frames = tables if tables is not None else (ctx.frames.get("tables") or {})
    counts = {}
    for name, frame in frames.items():
        directory = silver_partition_dir(ctx, name)
        _replace_table(directory, frame, name)
        counts[name] = 0 if frame is None else len(frame)
    print("publish: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return counts


def _replace_table(directory: Path, frame, table_name: str) -> None:
    """Replace only this table's CSV and Parquet files, preserving sibling tables."""
    if directory is None:
        return

    directory.mkdir(parents=True, exist_ok=True)

    parquet_path = directory / f"{table_name}.parquet"
    csv_path = directory / f"{table_name}.csv"
    parquet_staging = Path(str(parquet_path) + ".staging")
    csv_staging = Path(str(csv_path) + ".staging")

    frame.to_parquet(parquet_staging, index=False)
    frame.to_csv(csv_staging, index=False)

    parquet_staging.replace(parquet_path)
    csv_staging.replace(csv_path)
