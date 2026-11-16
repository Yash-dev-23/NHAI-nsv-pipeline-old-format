"""PCI = 100 − weighted defect score. Indexes are 0–100 before weighting.

The 10 m score uses the max value seen in this survey. 100 m and 1 km scores
are the mean of the 10 m scores in that bin, including the empty 10 m slices.
"""

from __future__ import annotations

import pandas as pd

from ris_silver.domain.lanes import normalize_lane

# Notebook weights. Sum to 1.
DEFAULT_WEIGHTS = {
    "cracking": 0.12,
    "ravelling": 0.10,
    "pothole": 0.16,
    "patching": 0.08,
    "rutting": 0.14,
    "roughness": 0.40,
}

_GRID = 10


def scale_index(value, observed_max) -> float:
    if value is None or observed_max is None or observed_max <= 0:
        return 0.0
    scaled = float(value) / float(observed_max) * 100.0
    return min(100.0, max(0.0, scaled))


def pci_score(indexes: dict[str, float], weights: dict[str, float]) -> float:
    score = sum(float(indexes[name]) * float(weights[name]) for name in weights)
    return round(min(100.0, max(0.0, 100.0 - score)), 4)


def _empty_metric(alias: str) -> pd.DataFrame:
    return pd.DataFrame(columns=["lane", "start_chainage", alias])


def _binned(frame: pd.DataFrame, lane_col: str, chain_col: str, value_col: str, alias: str, how: str) -> pd.DataFrame:
    if frame is None or frame.empty or value_col not in frame.columns or chain_col not in frame.columns:
        return _empty_metric(alias)
    work = pd.DataFrame({
        "lane": frame[lane_col].map(normalize_lane) if lane_col in frame.columns else frame.get("lane"),
        "start_chainage": pd.to_numeric(frame[chain_col], errors="coerce"),
        "val": pd.to_numeric(frame[value_col], errors="coerce").fillna(0.0),
    }).dropna(subset=["lane", "start_chainage"])
    if work.empty:
        return _empty_metric(alias)
    work["start_chainage"] = (work["start_chainage"] // _GRID * _GRID).astype(int)
    grouped = work.groupby(["lane", "start_chainage"], as_index=False)["val"].agg(how)
    return grouped.rename(columns={"val": alias})


def _pothole_metric(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return _empty_metric("pothole_area")
    lane_col = "Lane" if "Lane" in frame.columns else "lane"
    chain_col = "Start_Chainage" if "Start_Chainage" in frame.columns else "start_chainage"
    area_col = "Area_sq_m" if "Area_sq_m" in frame.columns else "area"
    return _binned(frame, lane_col, chain_col, area_col, "pothole_area", "sum")


def _bounds(frames: list[pd.DataFrame]) -> pd.DataFrame:
    pieces = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        pieces.append(frame.groupby("lane", as_index=False)["start_chainage"].agg(min_ch="min", max_ch="max"))
    if not pieces:
        return pd.DataFrame(columns=["lane", "min_ch", "max_ch"])
    return pd.concat(pieces, ignore_index=True).groupby("lane", as_index=False).agg(min_ch=("min_ch", "min"), max_ch=("max_ch", "max"))


def _spine(bounds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lane, lo, hi in bounds.itertuples(index=False):
        start = int(lo // _GRID * _GRID)
        stop = int(hi // _GRID * _GRID)
        for chainage in range(start, stop + _GRID, _GRID):
            rows.append({"lane": lane, "start_chainage": chainage})
    return pd.DataFrame(rows, columns=["lane", "start_chainage"])


def build_pci(canonical: dict, potholes, patching, weights: dict | None = None) -> dict[str, pd.DataFrame]:
    """Lane × chainage PCI at 10 m, and the 100 m / 1 km means of those scores."""
    weights = weights or DEFAULT_WEIGHTS
    canonical = canonical or {}
    cracking = _binned(canonical.get("cracking"), "lane", "start_chainage", "metric_value", "cracking_pct", "max")
    ravelling = _binned(canonical.get("ravelling"), "lane", "start_chainage", "rav_area_sqm", "ravelling_area", "sum")
    rutting = _binned(canonical.get("rutting"), "lane", "start_chainage", "metric_value", "rutting_mm", "max")
    roughness = _binned(canonical.get("roughness"), "lane", "start_chainage", "iri_value", "roughness_iri", "max")
    pothole = _pothole_metric(potholes)
    patch = patching if patching is not None else _empty_metric("patching_area")
    if "patching_area" not in getattr(patch, "columns", []):
        patch = _empty_metric("patching_area")
    pieces = [cracking, ravelling, pothole, rutting, roughness, patch]
    spine = _spine(_bounds(pieces))
    empty = pd.DataFrame(columns=["lane", "start_chainage", "pci"])
    if spine.empty:
        return {"10m": empty, "100m": empty, "1km": empty}
    pci = spine
    for piece in pieces:
        pci = pci.merge(piece, on=["lane", "start_chainage"], how="left")
    raw_cols = ["cracking_pct", "ravelling_area", "pothole_area", "rutting_mm", "roughness_iri", "patching_area"]
    for column in raw_cols:
        if column not in pci.columns:
            pci[column] = 0.0
        pci[column] = pd.to_numeric(pci[column], errors="coerce").fillna(0.0)
    index_of = {
        "cracking_pct": "crack_index",
        "ravelling_area": "ravel_index",
        "pothole_area": "pothole_index",
        "patching_area": "patch_index",
        "rutting_mm": "rut_index",
        "roughness_iri": "roughness_index",
    }
    for raw, index in index_of.items():
        ceiling = float(pci[raw].max())
        pci[index] = (pci[raw] / ceiling * 100.0).clip(0, 100) if ceiling > 0 else 0.0
    pci["weighted_defect_score"] = (
        pci["crack_index"] * float(weights["cracking"])
        + pci["ravel_index"] * float(weights["ravelling"])
        + pci["pothole_index"] * float(weights["pothole"])
        + pci["patch_index"] * float(weights["patching"])
        + pci["rut_index"] * float(weights["rutting"])
        + pci["roughness_index"] * float(weights["roughness"])
    ).round(4)
    pci["pci"] = (100.0 - pci["weighted_defect_score"]).clip(0, 100).round(4)
    ten = pci[["lane", "start_chainage", "pci"]].copy()

    def _mean(grid: int) -> pd.DataFrame:
        work = ten.copy()
        work["start_chainage"] = (work["start_chainage"] // grid * grid).astype(int)
        rolled = work.groupby(["lane", "start_chainage"], as_index=False)["pci"].mean()
        rolled["pci"] = rolled["pci"].round(4)
        return rolled

    return {"10m": ten, "100m": _mean(100), "1km": _mean(1000)}
