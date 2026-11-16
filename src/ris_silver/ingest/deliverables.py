"""D1 pavement context and D3 visual condition, cleaned the way the notebook cleans them."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ris_silver.domain.lanes import normalize_lane
from ris_silver.ingest.files import load_matching_parquets
from ris_silver.io.reader import read_parquet

_JUNK = {"lcms issue", "uc", "na", "n/a", ""}
_D3_DEFECTS = (
    ("crack", "Cracking"),
    ("roughness", "Roughness"),
    ("rutting", "Rutting"),
    ("rut", "Rutting"),
    ("pothole", "Pothole"),
    ("potholes", "Pothole"),
)


def _clean(frame: pd.DataFrame, value_col: str) -> pd.DataFrame:
    if frame.empty or value_col not in frame.columns:
        return frame
    mask = frame[value_col].fillna("").astype(str).str.strip().str.lower().isin(_JUNK)
    return frame.loc[~mask].copy()


def load_d1(d1_dir) -> dict[str, pd.DataFrame]:
    lrms, _ = load_matching_parquets(d1_dir, ["LRPMaster"])
    pavement, _ = load_matching_parquets(d1_dir, ["PavementType"])
    carriageway, _ = load_matching_parquets(d1_dir, ["CarriagewayType"])
    service, _ = load_matching_parquets(d1_dir, ["ServiceRoad"])
    pavement = _clean(pavement, "PavementType")
    carriageway = _clean(carriageway, "CarriagewayType")
    if not service.empty and "PavementType" in service.columns:
        service = _clean(service, "PavementType")
    else:
        service = pd.DataFrame()
    return {
        "lrms": lrms,
        "pavement": pavement,
        "carriageway": carriageway,
        "service_road": service,
    }


def load_d3(d3_dir) -> dict[str, pd.DataFrame]:
    """100 m bin, lane, and condition for each defect the D3 file name mentions."""
    folder = Path(d3_dir) if d3_dir else None
    found: dict[str, pd.DataFrame] = {}
    if folder is None or not folder.is_dir():
        return found
    for path in sorted(folder.iterdir(), key=lambda item: item.name):
        if not path.name.endswith(".parquet"):
            continue
        folded = path.name.lower()
        defect = next((label for token, label in _D3_DEFECTS if token in folded), None)
        if defect is None or defect in found:
            continue
        frame = read_parquet(str(path))
        if "Condition" not in frame.columns or "Start_Chainage" not in frame.columns:
            continue
        frame = frame.copy()
        frame["Start_Chainage"] = pd.to_numeric(frame["Start_Chainage"], errors="coerce")
        frame = frame.dropna(subset=["Start_Chainage"])
        lane_col = next((col for col in frame.columns if "lane" in str(col).lower().replace("\n", " ")), None)
        if lane_col:
            frame["Lane"] = frame[lane_col].map(normalize_lane)
        else:
            frame["Lane"] = "Unknown"
        frame["bin_100m"] = (frame["Start_Chainage"] // 100 * 100).astype(int)
        frame = frame[frame["Condition"].notna() & (frame["Condition"].astype(str) != "nan")]
        found[defect] = frame[["bin_100m", "Lane", "Condition"]].drop_duplicates(["bin_100m", "Lane"]).copy()
    return found
