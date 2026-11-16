"""Activity tracker row for this zone / phase / cycle / UPC, then the D2 filename override."""

from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd

from ris_silver.io.reader import read_excel

_DEFECTS = ("ravelling", "rutting", "cracking", "roughness", "pothole")
# Tracker sheet is positional. These are the columns the notebook reads.
_COL = {
    "phase": 2,
    "cycle": 3,
    "state": 6,
    "piu": 7,
    "contractor": 8,
    "ae_ie": 9,
    "upc": 12,
    "survey_start": 21,
    "survey_end": 22,
    "pavement_type": 42,
    "pci": 43,
}
_STD_COLS = {
    "ravelling": (46, 47),
    "rutting": (48, 49),
    "cracking": (50, 51),
    "roughness": (52, 53),
}


def _parse_std(value) -> str | None:
    text = str(value).strip().upper() if pd.notna(value) else ""
    if "IRC" in text:
        return "IRC"
    if "CA" in text:
        return "CA"
    return None


def _parse_interval(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _text(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _pci(value):
    if pd.isna(value):
        return None
    token = str(value).replace(".", "", 1).replace("-", "", 1)
    if token.isdigit():
        return float(value)
    return None


def default_tracker() -> dict:
    standards = {name: {"standard": "CA", "interval_m": 100} for name in _DEFECTS}
    return {
        "survey_start_date": None,
        "survey_end_date": None,
        "piu": None,
        "ae_ie": None,
        "contractor": None,
        "state": None,
        "pavement_type": None,
        "pci": None,
        "threshold_label_override": None,
        "defect_standards": standards,
        "raw_defect_standards": copy.deepcopy(standards),
        "warnings": [],
    }


def _upc_key(value: str) -> str:
    return str(value).replace("/", "_").replace("_", "").lower()


def load_tracker(path, zone: str, phase: str, cycle: str, upc: str, d2_dir) -> dict:
    """Match the tracker row, then let a D2 'As per CA/IRC' filename override the standard."""
    ctx = default_tracker()
    sheet = {"A": "Zone A", "B": "Zone B", "C": "Zone C", "D": "Zone D", "E": "Zone E"}.get(zone, f"Zone {zone}")
    tracker_path = Path(path) if path else None
    if tracker_path is None or not tracker_path.is_file():
        ctx["warnings"].append(f"tracker not found: {path}")
        _apply_d2_override(ctx, d2_dir)
        return ctx
    try:
        table = read_excel(str(tracker_path), sheet=sheet, header=1)
    except Exception as exc:
        ctx["warnings"].append(f"tracker unreadable: {exc}")
        _apply_d2_override(ctx, d2_dir)
        return ctx

    upc_key = _upc_key(upc.replace("_", "/"))
    best = None
    for _, row in table.iterrows():
        if len(row) <= _COL["upc"]:
            continue
        cell = _upc_key(row.iloc[_COL["upc"]])
        if upc_key not in cell and cell not in upc_key:
            continue
        phase_val = str(row.iloc[_COL["phase"]]).lower().replace("phase", "").strip()
        cycle_val = str(row.iloc[_COL["cycle"]]).lower().replace("cycle", "").strip()
        if phase_val == str(phase).strip() and cycle_val == str(cycle).strip():
            best = row
            break
        if best is None:
            best = row
    if best is None:
        ctx["warnings"].append(f"UPC {upc} not found in tracker")
        _apply_d2_override(ctx, d2_dir)
        return ctx

    start = pd.to_datetime(best.iloc[_COL["survey_start"]], errors="coerce")
    end = pd.to_datetime(best.iloc[_COL["survey_end"]], errors="coerce")
    standards = {}
    for name, (std_col, interval_col) in _STD_COLS.items():
        standards[name] = {
            "standard": _parse_std(best.iloc[std_col]),
            "interval_m": _parse_interval(best.iloc[interval_col]) or 100,
        }
    standards["pothole"] = standards["cracking"].copy()
    ctx.update(
        {
            "survey_start_date": start.date() if pd.notnull(start) else None,
            "survey_end_date": end.date() if pd.notnull(end) else None,
            "piu": _text(best.iloc[_COL["piu"]]),
            "ae_ie": _text(best.iloc[_COL["ae_ie"]]),
            "contractor": _text(best.iloc[_COL["contractor"]]),
            "state": _text(best.iloc[_COL["state"]]),
            "pavement_type": _text(best.iloc[_COL["pavement_type"]]),
            "pci": _pci(best.iloc[_COL["pci"]]),
            "defect_standards": standards,
            "raw_defect_standards": copy.deepcopy(standards),
        }
    )
    _apply_d2_override(ctx, d2_dir)
    return ctx


def _apply_d2_override(ctx: dict, d2_dir) -> None:
    folder = Path(d2_dir) if d2_dir else None
    names = [path.name.lower() for path in folder.iterdir() if path.name.endswith(".parquet")] if folder and folder.is_dir() else []
    if any("as per ca" in name or "with ca" in name for name in names):
        ctx["threshold_label_override"] = "As per CA"
        label = "CA"
    elif any("as per irc" in name or "with irc" in name for name in names):
        ctx["threshold_label_override"] = "As per IRC"
        label = "IRC"
    else:
        return
    for spec in ctx["defect_standards"].values():
        spec["standard"] = label


def threshold_name(tracker: dict, defect: str) -> str | None:
    override = tracker.get("threshold_label_override")
    if override:
        return override
    standard = tracker["defect_standards"].get(defect, {}).get("standard")
    if standard in {"IRC", "CA"}:
        return f"As per {standard}"
    return None


def reporting_interval(tracker: dict, defect: str) -> int:
    return tracker["defect_standards"].get(defect, {}).get("interval_m") or 100
