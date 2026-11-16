"""Where a run reads and writes. Roots are blank until storage paths are chosen."""

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


def silver_partition_dir(ctx: RunContext, table: str) -> Path | None:
    if not ctx.silver_root:
        return None
    return (
        Path(ctx.silver_root)
        / table
        / f"upc={ctx.upc}"
        / f"phase={ctx.phase}"
        / f"cycle={ctx.cycle}"
    )
