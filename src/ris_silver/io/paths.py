"""Where a run reads and writes. Roots are blank until storage paths are chosen.

S3-style convention:
    <silver_root>/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/dlm_kpi_new/<table>.parquet
    and a sibling <table>.csv in dlm_kpi_new.
"""

from __future__ import annotations

from pathlib import Path

from ris_silver.context import RunContext


def bronze_upc_dir(ctx: RunContext) -> Path | None:
    if not ctx.bronze_root:
        return None
    return (
        Path(ctx.bronze_root)
        / f"Zone={ctx.zone}"
        / f"Phase={ctx.phase}"
        / f"Cycle={ctx.cycle}"
        / f"UPC={ctx.upc}"
    )


def _upc_key(value: str) -> str:
    return str(value).replace("/", "-").replace("_", "-").strip("-")


def silver_run_root(ctx: RunContext) -> Path | None:
    if not ctx.silver_root:
        return None
    return (
        Path(ctx.silver_root)
        / f"zone={ctx.zone}"
        / f"phase={ctx.phase}"
        / f"cycle={ctx.cycle}"
        / _upc_key(ctx.upc)
    )


def silver_partition_dir(ctx: RunContext, table: str) -> Path | None:
    """Return the dlm_kpi_new directory for this UPC partition.

    Final object paths are:
        <silver_root>/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/dlm_kpi_new/<table>.parquet
        <silver_root>/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/dlm_kpi_new/<table>.csv
    """
    root = silver_run_root(ctx)
    if root is None:
        return None
    return root / "dlm_kpi_new"


def silver_latest_partition_dir(ctx: RunContext, table: str) -> Path | None:
    """Keep the latest output in the UPC's dlm_kpi_new directory."""
    return silver_partition_dir(ctx, table)


def silver_parquet_path(ctx: RunContext, table: str) -> Path | None:
    directory = silver_partition_dir(ctx, table)
    if directory is None:
        return None
    return directory / f"{table}.parquet"


def silver_csv_path(ctx: RunContext, table: str) -> Path | None:
    directory = silver_partition_dir(ctx, table)
    if directory is None:
        return None
    return directory / f"{table}.csv"
