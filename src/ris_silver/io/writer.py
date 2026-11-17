"""Replace one UPC / phase / cycle partition. Other UPCs stay in place.

Each table is published as an S3-like object pair:
    <silver_root>/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/run_date=<date>/<table>/<table>.parquet
    <silver_root>/zone=<zone>/phase=<phase>/cycle=<cycle>/<upc>/run_date=<date>/<table>/<table>.csv
    plus a copy at <silver_root>/latest/zone=.../phase=.../cycle=.../<upc>/<table>/
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ris_silver.app import PathsMissing
from ris_silver.context import RunContext
from ris_silver.io.paths import silver_latest_partition_dir, silver_partition_dir


def publish(ctx: RunContext, tables: dict | None = None) -> dict[str, int]:
    """Write each silver table under its own partition while keeping a current latest alias."""
    if not ctx.silver_root:
        raise PathsMissing("paths.silver_root is empty")
    frames = tables if tables is not None else (ctx.frames.get("tables") or {})
    counts = {}
    for name, frame in frames.items():
        directory = silver_partition_dir(ctx, name)
        latest_directory = silver_latest_partition_dir(ctx, name)
        _replace_partition(directory, frame, name)
        _mirror_latest(directory, latest_directory)
        counts[name] = 0 if frame is None else len(frame)
    print("publish: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return counts


def _replace_partition(directory: Path, frame, table_name: str) -> None:
    if directory is None:
        return
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(str(directory) + ".staging")
    previous = Path(str(directory) + ".previous")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    parquet_path = staging / f"{table_name}.parquet"
    csv_path = staging / f"{table_name}.csv"
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False)
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


def _mirror_latest(source: Path, target: Path) -> None:
    if source is None or target is None:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, dirs_exist_ok=True)
