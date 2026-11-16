"""Replace one UPC / phase / cycle partition. Other UPCs stay in place."""

from __future__ import annotations

import shutil
from pathlib import Path

from ris_silver.app import PathsMissing
from ris_silver.context import RunContext
from ris_silver.io.paths import silver_partition_dir


def publish(ctx: RunContext, tables: dict | None = None) -> dict[str, int]:
    """Write each silver table under its own partition. A second run replaces that partition only."""
    if not ctx.silver_root:
        raise PathsMissing("paths.silver_root is empty")
    frames = tables if tables is not None else (ctx.frames.get("tables") or {})
    counts = {}
    for name, frame in frames.items():
        directory = silver_partition_dir(ctx, name)
        _replace_partition(directory, frame)
        counts[name] = 0 if frame is None else len(frame)
    print("publish: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return counts


def _replace_partition(directory: Path, frame) -> None:
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(str(directory) + ".staging")
    previous = Path(str(directory) + ".previous")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    frame.to_parquet(staging / "part-000.parquet", index=False)
    if previous.exists():
        shutil.rmtree(previous)
    if directory.exists():
        directory.rename(previous)
    try:
        staging.rename(directory)
    except Exception:
        if previous.exists() and not directory.exists():
            previous.rename(directory)
        raise
    if previous.exists():
        shutil.rmtree(previous)
