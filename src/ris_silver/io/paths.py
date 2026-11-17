"""Where a run reads and writes. Roots are blank until storage paths are chosen.

S3-style convention:
    <silver_root>/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/run_date=<YYYY-MM-DD>/<table>/<table>.parquet
    and a sibling <table>.csv alongside the parquet object.
    The current copy lives at the silver root:
    <silver_root>/latest/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/<table>/
"""

from __future__ import annotations

from datetime import date
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


def _run_date(ctx: RunContext) -> str:
    explicit = getattr(ctx, "run_id", None) or getattr(ctx, "run_date", None)
    if explicit:
        return str(explicit)
    return date.today().isoformat()


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
    """Return the directory for a single table partition.

    Final object path is expected to be:
        <silver_root>/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/run_date=<date>/<table>/<table>.parquet
    """
    root = silver_run_root(ctx)
    if root is None:
        return None
    return root / f"run_date={_run_date(ctx)}" / table


def silver_latest_partition_dir(ctx: RunContext, table: str) -> Path | None:
    """Mirror the current run under latest at the silver root, not inside the UPC folder.

    Dated runs stay at zone/phase/cycle/upc/run_date. The newest copy is:
    <silver_root>/latest/zone=.../phase=.../cycle=.../<upc>/<table>/
    """
    if not ctx.silver_root:
        return None
    return (
        Path(ctx.silver_root)
        / "latest"
        / f"zone={ctx.zone}"
        / f"phase={ctx.phase}"
        / f"cycle={ctx.cycle}"
        / _upc_key(ctx.upc)
        / table
    )


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
