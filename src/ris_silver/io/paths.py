"""Silver output locations for UPC runs and shared consolidated latest datasets."""

from __future__ import annotations

from pathlib import Path

from ris_silver.context import RunContext

PathLike = Path | str


def _join(root: str | Path, *parts: str) -> PathLike:
    """Join path components without mangling an S3 URI into ``s3:/...``."""
    value = str(root).rstrip("/")
    if value.startswith("s3://"):
        return value + "/" + "/".join(part.strip("/") for part in parts)
    return Path(root).joinpath(*parts)


def bronze_upc_dir(ctx: RunContext) -> Path | None:
    if not ctx.bronze_root:
        return None
    return Path(ctx.bronze_root) / "Source=NSV" / f"Zone={ctx.zone}" / f"Phase={ctx.phase}" / f"Cycle={ctx.cycle}" / f"UPC={ctx.upc}"


def _upc_key(value: str) -> str:
    return str(value).replace("/", "-").replace("_", "-").strip("-")


def silver_run_root(ctx: RunContext) -> PathLike | None:
    """Return the per-UPC Silver output root."""
    if not ctx.silver_root:
        return None
    return _join(
        ctx.silver_root,
        f"zone={ctx.zone}",
        f"phase={ctx.phase}",
        f"cycle={ctx.cycle}",
        _upc_key(ctx.upc),
    )


def silver_partition_dir(ctx: RunContext, table: str) -> PathLike | None:
    """Return this UPC's standard DLM KPI output directory."""
    root = silver_run_root(ctx)
    if root is None:
        return None
    return _join(root, "dlm_kpi_new")


def silver_latest_partition_dir(ctx: RunContext, table: str) -> PathLike | None:
    """Return the single shared directory containing one consolidated file per table."""
    if not ctx.silver_root:
        return None
    return _join(ctx.silver_root, "latest")


def silver_parquet_path(ctx: RunContext, table: str) -> PathLike | None:
    directory = silver_partition_dir(ctx, table)
    if directory is None:
        return None
    return _join(directory, f"{table}.parquet")


def silver_csv_path(ctx: RunContext, table: str) -> PathLike | None:
    directory = silver_partition_dir(ctx, table)
    if directory is None:
        return None
    return _join(directory, f"{table}.csv")


def silver_latest_parquet_path(ctx: RunContext, table: str) -> PathLike | None:
    directory = silver_latest_partition_dir(ctx, table)
    if directory is None:
        return None
    return _join(directory, f"{table}.parquet")


def silver_latest_csv_path(ctx: RunContext, table: str) -> PathLike | None:
    directory = silver_latest_partition_dir(ctx, table)
    if directory is None:
        return None
    return _join(directory, f"{table}.csv")
