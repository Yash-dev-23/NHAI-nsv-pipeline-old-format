"""Read the parquet files that belong to one deliverable or one lane."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ris_silver.domain.lanes import normalize_lane
from ris_silver.io.reader import read_parquet


def discover_lane_folders(base) -> list[str]:
    folder = Path(base) if base else None
    if folder is None or not folder.is_dir():
        return []
    return sorted(
        child.name.replace("Lane=", "")
        for child in folder.iterdir()
        if child.is_dir() and child.name.startswith("Lane=")
    )


def load_matching_parquets(base, patterns: list[str]) -> tuple[pd.DataFrame, list[str]]:
    folder = Path(base) if base else None
    if folder is None or not folder.is_dir():
        return pd.DataFrame(), []
    files = [
        child.name
        for child in sorted(folder.iterdir(), key=lambda p: p.name)
        if child.is_file() and child.name.endswith(".parquet") and any(p.lower() in child.name.lower() for p in patterns)
    ]
    if not files:
        return pd.DataFrame(), files
    frames = [read_parquet(str(folder / name)) for name in files]
    return pd.concat(frames, ignore_index=True), files


def load_backup_lane_parquets(base, suffixes) -> tuple[pd.DataFrame, list[str]]:
    if isinstance(suffixes, str):
        suffixes = [suffixes]
    frames, files = [], []
    for lane in discover_lane_folders(base):
        lane_dir = Path(base) / f"Lane={lane}"
        lane_name = normalize_lane(lane)
        matches = [
            child.name
            for child in sorted(lane_dir.iterdir(), key=lambda p: p.name)
            if child.is_file() and child.name.endswith(".parquet") and any(sfx.lower() in child.name.lower() for sfx in suffixes)
        ]
        for name in matches:
            part = read_parquet(str(lane_dir / name))
            if "Lane" not in part.columns and "LANE" not in part.columns:
                part["Lane"] = lane_name
            for column in ("Lane", "LANE"):
                if column in part.columns:
                    part[column] = part[column].map(normalize_lane).fillna(lane_name)
            part["Source_Lane_Folder"] = lane_name
            frames.append(part)
            files.append(f"Lane={lane}/{name}")
    if not frames:
        return pd.DataFrame(), files
    return pd.concat(frames, ignore_index=True), files
