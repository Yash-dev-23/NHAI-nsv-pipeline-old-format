"""Defect image names, and CDN URLs when an upload endpoint is configured.

Pothole rows and cracking 10 m rows keep the file name in ``image_name`` and
``image_urls``. ``image_url`` stays empty unless ``IMAGE_UPLOAD_BASE_URL`` is
set. A breach row (one with a display id) is uploaded once per file name, and
the returned URL is written onto every row of this UPC that uses that name.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

from ris_silver.domain.spec import POTHOLE_TABLE

CRACKING_10M = "master_cracking_10m"
IMAGE_TABLES = {
    POTHOLE_TABLE: "pothole",
    CRACKING_10M: "cracking",
}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def image_fields(value) -> dict:
    """Notebook pair: the file name, and a one-item list when the name is present."""
    name = _text(value)
    return {"image_name": name, "image_urls": [name] if name else None}


def upload_base_url() -> str:
    return os.environ.get("IMAGE_UPLOAD_BASE_URL", "").strip().rstrip("/")


def index_images(image_root: str | None) -> dict[str, dict[str, str]]:
    """File name and stem, split by a cracking or pothole folder in the path."""
    index = {"cracking": {}, "pothole": {}}
    root = Path(image_root) if image_root else None
    if root is None or not root.is_dir():
        return index
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        folder = str(path.parent).lower()
        if "crack" in folder:
            kind = "cracking"
        elif "pothole" in folder:
            kind = "pothole"
        else:
            continue
        index[kind].setdefault(path.name, str(path))
        index[kind].setdefault(path.stem, str(path))
    return index


def find_image(index: dict[str, dict[str, str]], name: str, kind: str) -> str | None:
    other = "pothole" if kind == "cracking" else "cracking"
    stem = os.path.splitext(name)[0]
    for bucket in (kind, other):
        found = index.get(bucket, {}).get(name) or index.get(bucket, {}).get(stem)
        if found:
            return found
    return None


def safe_display_id(display_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", str(display_id))[:128]


def upload_frame(frame: pd.DataFrame, kind: str, index: dict, poster) -> tuple[pd.DataFrame, dict]:
    """Upload each missing breach image once and copy the URL onto matching names."""
    result = frame.copy()
    todo = _todo(result)
    tasks = []
    missing = 0
    for name, display_id in todo:
        path = find_image(index, name, kind)
        if not path:
            missing += 1
            continue
        tasks.append((name, path, display_id))
    uploaded = {}
    failed = 0
    for name, path, display_id in tasks:
        good, info = poster(path, kind, safe_display_id(display_id))
        if good and info:
            uploaded[name] = info
        else:
            failed += 1
    if uploaded:
        result = _merge_urls(result, uploaded)
    stats = {
        "defect_type": kind,
        "images_to_upload": len(todo),
        "no_file_found": missing,
        "uploaded": len(uploaded),
        "failed": failed,
        "rows_updated": int(result["image_name"].isin(uploaded).sum()) if uploaded and "image_name" in result.columns else 0,
    }
    return result, stats


def upload_defect_images(ctx, poster=None) -> list[dict]:
    """Fill ``image_url`` on the written pothole and cracking 10 m tables.

    With no upload URL and no injected poster, the written files are left as they
    are and ``image_url`` stays empty.
    """
    base = upload_base_url()
    if poster is None and not base:
        print("images: no upload url, image_url left empty")
        return []
    send = poster or _http_poster(f"{base}/defects/images/upload")
    index = index_images(getattr(ctx, "image_root", "") or "")
    summary = []
    from ris_silver.io.paths import silver_partition_dir
    from ris_silver.io.writer import _upsert_latest, _write_table_pair

    for table, kind in IMAGE_TABLES.items():
        directory = silver_partition_dir(ctx, table)
        path = None if directory is None else directory / f"{table}.parquet"
        if path is None or not path.is_file():
            continue
        frame = pd.read_parquet(path)
        updated, stats = upload_frame(frame, kind, index, send)
        stats["table"] = table
        if stats["uploaded"]:
            _write_table_pair(directory, table, updated)
            _upsert_latest(ctx, table, updated)
            tables = ctx.frames.get("tables") or {}
            if table in tables:
                tables[table] = updated
        summary.append(stats)
        print(
            f"images: {table} uploaded={stats['uploaded']} "
            f"missing_file={stats['no_file_found']} failed={stats['failed']} rows={stats['rows_updated']}"
        )
    return summary


def _todo(frame: pd.DataFrame) -> list[tuple[str, str]]:
    needed = {"image_name", "display_defect_id", "image_url"}
    if frame is None or frame.empty or not needed.issubset(frame.columns):
        return []
    chosen: dict[str, str] = {}
    for _, row in frame.iterrows():
        name = _text(row.get("image_name"))
        display_id = _text(row.get("display_defect_id"))
        if name is None or display_id is None or _text(row.get("image_url")) is not None:
            continue
        current = chosen.get(name)
        if current is None or display_id < current:
            chosen[name] = display_id
    return sorted(chosen.items())


def _merge_urls(frame: pd.DataFrame, uploaded: dict[str, str]) -> pd.DataFrame:
    result = frame.copy()
    names = result["image_name"].map(_text)
    for name, url in uploaded.items():
        match = names.eq(name)
        result.loc[match, "image_url"] = url
        for index in result.index[match]:
            if _urls_empty(result.at[index, "image_urls"]):
                result.at[index, "image_urls"] = [url]
    return result


def _urls_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        return False
    return False


def _text(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _http_poster(endpoint: str):
    def post(path: str, kind: str, display_id: str):
        try:
            import requests
        except ImportError:
            return False, "requests is not installed"
        try:
            with open(path, "rb") as handle:
                response = requests.post(
                    endpoint,
                    files={"image": (os.path.basename(path), handle, "image/jpeg")},
                    data={"defect_type": kind, "display_defect_id": display_id},
                    timeout=30,
                )
            if response.status_code == 201:
                return True, (response.json().get("data") or {}).get("url", "")
            return False, f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as exc:
            return False, str(exc)[:200]

    return post
