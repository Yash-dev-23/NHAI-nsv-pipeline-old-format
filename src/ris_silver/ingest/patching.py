"""Patching area is a PCI input. It has no silver table of its own."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ris_silver.domain.lanes import normalize_lane
from ris_silver.ingest.files import discover_lane_folders
from ris_silver.io.reader import read_parquet

_GRID = 10


def load_patching(backup_dir) -> pd.DataFrame:
    """Sum patch area onto the lane × 10 m bin. Missing files yield an empty frame."""
    frames = []
    for lane in discover_lane_folders(backup_dir):
        lane_dir = Path(backup_dir) / f"Lane={lane}"
        if not lane_dir.is_dir():
            continue
        matches = sorted(
            path for path in lane_dir.iterdir()
            if path.is_file() and path.name.endswith(".parquet") and "patch" in path.name.lower()
        )
        for path in matches:
            part = read_parquet(str(path))
            folded = {str(column).lower(): column for column in part.columns}
            chain_col = folded.get("chainage") or folded.get("start_chainage")
            area_col = folded.get("area") or folded.get("area_sq_m") or folded.get("total_area")
            if not chain_col or not area_col:
                continue
            piece = part[[chain_col, area_col]].copy()
            piece.columns = ["Chainage", "Area"]
            piece["Lane"] = normalize_lane(lane)
            piece["Chainage"] = pd.to_numeric(piece["Chainage"], errors="coerce")
            piece["Area"] = pd.to_numeric(piece["Area"], errors="coerce").fillna(0.0)
            frames.append(piece)
    if not frames:
        return pd.DataFrame(columns=["lane", "start_chainage", "patching_area"])
    all_patch = pd.concat(frames, ignore_index=True).dropna(subset=["Chainage", "Lane"])
    all_patch["start_chainage"] = (all_patch["Chainage"] // _GRID * _GRID).astype(int)
    grouped = all_patch.groupby(["Lane", "start_chainage"], as_index=False)["Area"].sum()
    return grouped.rename(columns={"Lane": "lane", "Area": "patching_area"})
