"""CA and IRC limitation columns from the D2 parquet files of this survey."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ris_silver.io.reader import read_parquet

_CA_DEFAULTS = {
    "roughness_bi": 2400.0,
    "roughness_iri": 2400.0,
    "rutting_mm": 10.0,
    "cracking_pct": 10.0,
    "ravelling": 10.0,
    "ravelling_unit": "pct",
}


def _first_number(frame: pd.DataFrame, column: str):
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.iloc[0])


def parse_d2_thresholds(d2_dir) -> dict:
    """Combined CA/IRC limitation parse. IRC roughness lands in roughness_iri."""
    thresholds = dict(_CA_DEFAULTS)
    folder = Path(d2_dir) if d2_dir else None
    if folder is None or not folder.is_dir():
        thresholds["warnings"] = ["D2 path not found, using defaults"]
        return thresholds
    ca_set, irc_set = set(), set()
    for path in sorted(folder.iterdir(), key=lambda p: p.name):
        if not path.name.endswith(".parquet"):
            continue
        if "roughness,rut,crack,rav" in path.name.lower():
            continue
        is_irc_file = "irc" in path.name.lower()
        frame = read_parquet(str(path))
        for column in frame.columns:
            folded = column.lower()
            if "limitation" not in folded and "limit" not in folded:
                continue
            if ">" in folded:
                continue
            limit = _first_number(frame, column)
            if limit is None:
                continue
            is_ca = "concession" in folded
            if ("irc" in folded and "roughness" in folded) or ("iri" in folded and "limitation" in folded):
                if is_irc_file:
                    if "roughness_iri" not in irc_set:
                        thresholds["roughness_iri"] = limit
                        irc_set.add("roughness_iri")
                elif "roughness_bi" not in ca_set:
                    thresholds["roughness_bi"] = limit
                    ca_set.add("roughness_bi")
            elif "bi" in folded or ("roughness" in folded and "irc" not in folded):
                if is_irc_file:
                    if "roughness_iri" not in irc_set:
                        thresholds["roughness_iri"] = limit
                        irc_set.add("roughness_iri")
                elif is_ca or "roughness_bi" not in ca_set:
                    thresholds["roughness_bi"] = limit
                    if is_ca:
                        ca_set.add("roughness_bi")
            elif "rut" in folded:
                if not is_irc_file:
                    thresholds["rutting_mm"] = limit
                    ca_set.add("rutting_mm")
                elif "rutting_mm" not in ca_set:
                    thresholds["rutting_mm"] = limit
            elif "crack" in folded:
                if not is_irc_file:
                    thresholds["cracking_pct"] = limit
                    ca_set.add("cracking_pct")
                elif "cracking_pct" not in ca_set:
                    thresholds["cracking_pct"] = limit
            elif "ravelling" in folded or "ravel" in folded:
                if not is_irc_file:
                    thresholds["ravelling"] = limit
                    ca_set.add("ravelling")
                elif "ravelling" not in ca_set:
                    thresholds["ravelling"] = limit
                if "sq" in folded or "area" in folded:
                    thresholds["ravelling_unit"] = "sqm"
                elif "%" in folded or "percent" in folded:
                    thresholds["ravelling_unit"] = "pct"
    thresholds["warnings"] = []
    return thresholds


def parse_irc_file_thresholds(d2_dir, ca: dict) -> dict:
    """First D2 file with 'irc' in the name. Missing cuts fall back to the CA values."""
    irc = {
        "roughness_iri": ca["roughness_iri"],
        "cracking_pct": None,
        "rutting_mm": None,
        "ravelling": None,
        "ravelling_unit": None,
    }
    folder = Path(d2_dir) if d2_dir else None
    if folder and folder.is_dir():
        for path in sorted(folder.iterdir(), key=lambda p: p.name):
            if not path.name.endswith(".parquet") or "irc" not in path.name.lower():
                continue
            frame = read_parquet(str(path))
            for column in frame.columns:
                folded = column.lower()
                if "limit" not in folded:
                    continue
                limit = _first_number(frame, column)
                if limit is None:
                    continue
                if "crack" in folded and irc["cracking_pct"] is None:
                    irc["cracking_pct"] = limit
                elif "rut" in folded and irc["rutting_mm"] is None:
                    irc["rutting_mm"] = limit
                elif "ravel" in folded and irc["ravelling"] is None:
                    irc["ravelling"] = limit
                    if "%" in folded or "pct" in folded:
                        irc["ravelling_unit"] = "pct"
                    elif "sq" in folded or "area" in folded:
                        irc["ravelling_unit"] = "sqm"
            break
    irc["cracking_pct"] = irc["cracking_pct"] or ca["cracking_pct"]
    irc["rutting_mm"] = irc["rutting_mm"] or ca["rutting_mm"]
    irc["ravelling"] = irc["ravelling"] or ca["ravelling"]
    irc["ravelling_unit"] = irc["ravelling_unit"] or ca["ravelling_unit"]
    return irc


def load_thresholds(d2_dir) -> dict:
    ca = parse_d2_thresholds(d2_dir)
    return {"ca": ca, "irc_file": parse_irc_file_thresholds(d2_dir, ca)}
