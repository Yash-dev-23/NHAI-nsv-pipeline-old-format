"""Where a run reads and writes. Roots are blank until storage paths are chosen.

S3-style conventions:
    <silver_root>/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/dlm_kpi_new/<table>.parquet
    <silver_root>/latest/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/dlm_kpi_new/<table>.parquet

Each Parquet object has a sibling CSV. The global latest root retains the
zone/phase/cycle/UPC partition hierarchy so updates from one UPC do not replace
other UPCs' outputs.
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
    """Return the historical/current output root for one UPC."""
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
    """Return this UPC's standard DLM KPI output directory."""
    root = silver_run_root(ctx)
    if root is None:
        return None
    return root / "dlm_kpi_new"


def silver_latest_partition_dir(ctx: RunContext, table: str) -> Path | None:
    """Return this UPC's partition under the shared Silver/latest root.

    The partition columns remain in the path so runs for different zones,
    phases, cycles, and UPCs coexist without overwriting one another.
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
        / "dlm_kpi_new"
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
