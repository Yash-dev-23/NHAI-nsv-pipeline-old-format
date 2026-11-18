"""Publish UPC outputs and upsert them into consolidated Silver/latest tables.

Per-UPC outputs remain under the zone/phase/cycle/UPC DLM folder. The shared
latest directory contains flat table files (for example ``latest/master_roughness.parquet``).
Each latest table is an upsert keyed by ``upc_code``, ``phase``, and ``cycle``;
rows for other UPC/cycle identities are retained.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import boto3
import pandas as pd
from botocore.exceptions import ClientError

from ris_silver.app import PathsMissing
from ris_silver.context import RunContext
from ris_silver.io.paths import (
    PathLike,
    silver_latest_csv_path,
    silver_latest_parquet_path,
    silver_partition_dir,
)


def publish(ctx: RunContext, tables: dict | None = None) -> dict[str, int]:
    """Write per-UPC tables and upsert each table in the shared latest location."""
    if not ctx.silver_root:
        raise PathsMissing("paths.silver_root is empty")
    frames = tables if tables is not None else (ctx.frames.get("tables") or {})
    counts = {}
    for name, frame in frames.items():
        published = _with_run_metadata(ctx, frame)
        output_directory = silver_partition_dir(ctx, name)
        _write_table_pair(output_directory, name, published)
        _upsert_latest(ctx, name, published)
        counts[name] = len(published)
    print("publish: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return counts


def _with_run_metadata(ctx: RunContext, frame) -> pd.DataFrame:
    """Ensure every output row identifies its survey and UPC partition."""
    result = pd.DataFrame() if frame is None else frame.copy()
    tracker = ctx.frames.get("tracker") or {}
    metadata = {
        "upc_code": ctx.upc,
        "zone": ctx.zone,
        "phase": str(ctx.phase),
        "cycle": str(ctx.cycle),
        "survey_start_date": tracker.get("survey_start_date"),
        "survey_end_date": tracker.get("survey_end_date"),
    }
    for column, value in metadata.items():
        result[column] = value
    return result


def _upsert_latest(ctx: RunContext, table_name: str, current: pd.DataFrame) -> None:
    """Replace this UPC/phase/cycle's rows in a flat latest table, keeping all others."""
    parquet_path = silver_latest_parquet_path(ctx, table_name)
    csv_path = silver_latest_csv_path(ctx, table_name)
    if parquet_path is None or csv_path is None:
        return

    previous = _read_existing_pair(parquet_path, csv_path)
    if not previous.empty and {"upc_code", "phase", "cycle"}.issubset(previous.columns):
        same_identity = (
            previous["upc_code"].astype(str).eq(str(ctx.upc))
            & previous["phase"].astype(str).eq(str(ctx.phase))
            & previous["cycle"].astype(str).eq(str(ctx.cycle))
        )
        previous = previous.loc[~same_identity]

    merged = pd.concat([previous, current], ignore_index=True, sort=False)
    _write_frame(parquet_path, merged, file_format="parquet")
    _write_frame(csv_path, merged, file_format="csv")


def _read_existing_pair(parquet_path: PathLike, csv_path: PathLike) -> pd.DataFrame:
    if _exists(parquet_path):
        try:
            if _is_s3(parquet_path):
                body = _s3_get(parquet_path)
                return pd.read_parquet(BytesIO(body))
            return pd.read_parquet(parquet_path)
        except Exception as exc:
            raise RuntimeError(f"Could not read existing consolidated Parquet {parquet_path}: {exc}") from exc
    if _exists(csv_path):
        try:
            if _is_s3(csv_path):
                return pd.read_csv(BytesIO(_s3_get(csv_path)))
            return pd.read_csv(csv_path)
        except Exception as exc:
            raise RuntimeError(f"Could not read existing consolidated CSV {csv_path}: {exc}") from exc
    return pd.DataFrame()


def _write_table_pair(directory: PathLike | None, table_name: str, frame: pd.DataFrame) -> None:
    if directory is None:
        return
    _write_frame(_join(directory, f"{table_name}.parquet"), frame, "parquet")
    _write_frame(_join(directory, f"{table_name}.csv"), frame, "csv")


def _write_frame(path: PathLike, frame: pd.DataFrame, file_format: str) -> None:
    if _is_s3(path):
        buffer = BytesIO()
        if file_format == "parquet":
            frame.to_parquet(buffer, index=False)
        else:
            buffer.write(frame.to_csv(index=False).encode("utf-8"))
        bucket, key = _s3_parts(path)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())
        return

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(str(destination) + ".staging")
    try:
        if file_format == "parquet":
            frame.to_parquet(staging, index=False)
        else:
            frame.to_csv(staging, index=False)
        staging.replace(destination)
    finally:
        staging.unlink(missing_ok=True)


def _exists(path: PathLike) -> bool:
    if not _is_s3(path):
        return Path(path).is_file()
    bucket, key = _s3_parts(path)
    try:
        boto3.client("s3").head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def _s3_get(path: PathLike) -> bytes:
    bucket, key = _s3_parts(path)
    return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()


def _s3_parts(path: PathLike) -> tuple[str, str]:
    parsed = urlparse(str(path))
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Not a valid S3 URI: {path}")
    return parsed.netloc, parsed.path.lstrip("/")


def _is_s3(path: PathLike) -> bool:
    return str(path).startswith("s3://")


def _join(directory: PathLike, filename: str) -> PathLike:
    if _is_s3(directory):
        return str(directory).rstrip("/") + "/" + filename
    return Path(directory) / filename
