"""D4 pothole records. D2 sheet is used only when D4 has no usable rows."""

from __future__ import annotations

import difflib
import os
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from ris_silver.domain.lanes import direction_of_lane, normalize_lane
from ris_silver.ingest.columns import pick
from ris_silver.io.reader import read_parquet

POTHOLE_SHEET_MIN_SCORE = 0.85
_MIN_DEFECT_COLS = {"severity", "area_sq_m", "area", "type_of_defect", "lane_no"}
_EXCLUDE = ("roughness", "rut,", "crack", "raveling", "ravelling")
_SEGMENT_M = 10


def _sheet_token(name: str) -> str:
    return os.path.splitext(name)[0].rsplit("_", 1)[-1].strip()


def pothole_sheet_score(name: str) -> float:
    token = _sheet_token(name).lower()
    token = re.sub(r"^[a-z]{3}-?\d{2}\s*", "", token)
    token = re.sub(r"[^a-z]", "", token)
    if not token:
        return 0.0
    if "pothole" in token:
        return 1.0
    if len(token) >= 2 and "potholes".startswith(token):
        return 0.9
    return difflib.SequenceMatcher(None, token, "potholes").ratio()


def load_d4_potholes(d4_dir) -> pd.DataFrame:
    folder = Path(d4_dir) if d4_dir else None
    if folder is None or not folder.is_dir():
        return pd.DataFrame()
    names = [
        path.name
        for path in sorted(folder.iterdir(), key=lambda item: item.name)
        if path.is_file()
        and path.name.endswith(".parquet")
        and "pothole" in path.name.lower()
        and not any(word in path.name.lower() for word in _EXCLUDE)
    ]
    frames = []
    for name in names:
        part = read_parquet(str(folder / name))
        if {column.lower() for column in part.columns} & _MIN_DEFECT_COLS:
            frames.append(part)
    if not frames:
        return pd.DataFrame()
    frame = pd.concat(frames, ignore_index=True)
    return _standardize_d4(frame)


def _chainage_from_km_m(frame, km_col, m_col, chain_col):
    km = pd.to_numeric(frame[km_col], errors="coerce").fillna(0).astype(int)
    metres = pd.to_numeric(frame[m_col], errors="coerce").fillna(0).astype(int)
    chainage = km * 1000 + metres
    spilled = metres > 999
    if spilled.any() and chain_col:
        direct = pd.to_numeric(frame[chain_col], errors="coerce").fillna(0).astype(int)
        chainage = chainage.copy()
        chainage.loc[spilled] = direct.loc[spilled]
    return chainage


def _standardize_d4(frame: pd.DataFrame) -> pd.DataFrame:
    columns = list(frame.columns)
    from_km = pick(columns, "from_ch_km") or pick(columns, "from", "km")
    from_m = pick(columns, "from_ch_m") or pick(columns, "from", "meter")
    to_km = pick(columns, "to_ch_km") or pick(columns, "to", "km")
    to_m = pick(columns, "to_ch_m") or pick(columns, "to", "meter")
    chain = pick(columns, "chainage")
    lane = pick(columns, "lane_no") or pick(columns, "lane no") or pick(columns, "lane")
    if from_km and from_m:
        frame["Start_Chainage"] = _chainage_from_km_m(frame, from_km, from_m, chain)
    elif chain:
        frame["Start_Chainage"] = pd.to_numeric(frame[chain], errors="coerce").fillna(0)
        frame.loc[frame["Start_Chainage"] < 1000, "Start_Chainage"] *= 1000
    else:
        frame["Start_Chainage"] = 0
    if to_km and to_m:
        to_km_vals = pd.to_numeric(frame[to_km], errors="coerce")
        to_m_vals = pd.to_numeric(frame[to_m], errors="coerce")
        end = _chainage_from_km_m(frame, to_km, to_m, chain)
        frame["End_Chainage"] = end
        both_null = to_km_vals.isna() & to_m_vals.isna()
        frame.loc[both_null, "End_Chainage"] = frame.loc[both_null, "Start_Chainage"]
    else:
        frame["End_Chainage"] = frame["Start_Chainage"]
    frame["Lane"] = frame[lane].map(normalize_lane).fillna("Unknown") if lane else "Unknown"
    rename = {}
    for keywords, target in (
        (("latitude",), "Latitude"),
        (("longitude",), "Longitude"),
        (("image_name",), "Image_Name"),
        (("image name",), "Image_Name"),
        (("severity",), "Severity"),
        (("type_of_defect",), "Type_of_Defect"),
        (("area_sq_m",), "Area_sq_m"),
        (("max_depth_mm",), "Max_Depth_mm"),
        (("average_depth_mm",), "Average_Depth_mm"),
        (("datetime",), "Survey_Date"),
        (("side",), "Side"),
    ):
        source = pick(columns, *keywords)
        if source and target not in rename.values():
            rename[source] = target
    # image name has two keyword attempts; pick() takes keywords that must ALL match.
    if "Image_Name" not in rename.values():
        source = pick(columns, "image", "name")
        if source:
            rename[source] = "Image_Name"
    if "Area_sq_m" not in rename.values():
        source = pick(columns, "area", "sq")
        if source:
            rename[source] = "Area_sq_m"
    if "Max_Depth_mm" not in rename.values():
        source = pick(columns, "max", "depth")
        if source:
            rename[source] = "Max_Depth_mm"
    if "Average_Depth_mm" not in rename.values():
        source = pick(columns, "average", "depth")
        if source:
            rename[source] = "Average_Depth_mm"
    if "Survey_Date" not in rename.values():
        source = pick(columns, "date")
        if source:
            rename[source] = "Survey_Date"
    if "Type_of_Defect" not in rename.values():
        source = pick(columns, "type", "defect")
        if source:
            rename[source] = "Type_of_Defect"
    return frame.rename(columns=rename)


def load_d2_potholes(d2_dir) -> tuple[pd.DataFrame, str | None]:
    folder = Path(d2_dir) if d2_dir else None
    if folder is None or not folder.is_dir():
        return pd.DataFrame(), None
    candidates = []
    for path in sorted(folder.iterdir(), key=lambda item: item.name):
        if not path.name.endswith(".parquet"):
            continue
        score = pothole_sheet_score(path.name)
        if score < POTHOLE_SHEET_MIN_SCORE:
            continue
        frame = read_parquet(str(path))
        chain_col = pick(frame.columns, "chainage")
        lane_col = pick(frame.columns, "lane")
        if not chain_col or not lane_col:
            continue
        usable = pd.to_numeric(frame[chain_col], errors="coerce").notna().sum()
        if usable:
            candidates.append((score, int(usable), path.name, frame, chain_col, lane_col))
    if not candidates:
        return pd.DataFrame(), None
    _score, _usable, name, frame, chain_col, lane_col = sorted(candidates, key=lambda item: (-item[0], -item[1]))[0]
    return _standardize_d2(frame, chain_col, lane_col), name


def _text_column(frame, column):
    if not column:
        return pd.Series([None] * len(frame), index=frame.index, dtype="object")
    return frame[column].astype("object").map(lambda value: str(value).strip() if pd.notna(value) and str(value).strip() else None)


def _number_column(frame, column):
    if not column:
        return np.nan
    return pd.to_numeric(frame[column], errors="coerce").astype(float)


def _standardize_d2(frame: pd.DataFrame, chain_col: str, lane_col: str) -> pd.DataFrame:
    columns = list(frame.columns)
    chosen = {
        "from_km": pick(columns, "from_ch_km") or pick(columns, "from", "km"),
        "from_m": pick(columns, "from_ch_m") or pick(columns, "from", "meter"),
        "area": pick(columns, "area_sq_m") or pick(columns, "area"),
        "maxd": pick(columns, "max", "depth"),
        "avgd": pick(columns, "average", "depth") or pick(columns, "ave", "depth") or pick(columns, "avg", "depth"),
        "sev": pick(columns, "severity"),
        "type": pick(columns, "type_of_defect") or pick(columns, "type", "defect"),
        "lat": pick(columns, "latitude"),
        "lon": pick(columns, "longitude"),
        "img": pick(columns, "image"),
        "date": pick(columns, "datetime") or pick(columns, "date"),
        "side": pick(columns, "side"),
    }
    out = frame.copy()
    chainage = pd.to_numeric(out[chain_col], errors="coerce").astype(float)
    if chosen["from_km"] and chosen["from_m"]:
        alternate = pd.to_numeric(out[chosen["from_km"]], errors="coerce").astype(float) * 1000 + pd.to_numeric(
            out[chosen["from_m"]], errors="coerce"
        ).astype(float)
        chainage = chainage.fillna(alternate)
    if chainage.dropna().lt(1000).all():
        chainage = chainage * 1000
    out["Start_Chainage"] = chainage
    out["Lane"] = out[lane_col].map(normalize_lane)
    out = out.dropna(subset=["Start_Chainage", "Lane"]).reset_index(drop=True)
    out["Start_Chainage"] = out["Start_Chainage"].round().astype("int64")
    out["End_Chainage"] = out["Start_Chainage"]
    out["Area_sq_m"] = _number_column(out, chosen["area"])
    out["Max_Depth_mm"] = _number_column(out, chosen["maxd"])
    out["Average_Depth_mm"] = _number_column(out, chosen["avgd"])
    out["Severity"] = _text_column(out, chosen["sev"])
    out["Type_of_Defect"] = _text_column(out, chosen["type"]).fillna("Potholes")
    out["Latitude"] = _number_column(out, chosen["lat"])
    out["Longitude"] = _number_column(out, chosen["lon"])
    out["Image_Name"] = _text_column(out, chosen["img"])
    out["Survey_Date"] = pd.to_datetime(out[chosen["date"]], errors="coerce") if chosen["date"] else pd.NaT
    side_from_lane = out["Lane"].map(
        lambda lane: {"Increasing": "LHS", "Decreasing": "RHS"}.get(direction_of_lane(lane))
    )
    out["Side"] = _text_column(out, chosen["side"]).fillna(side_from_lane)
    out["Pothole_Source"] = "D2"
    return out


def build_segment_index(cracking: pd.DataFrame) -> dict[str, pd.DataFrame]:
    segments = {}
    if cracking is None or cracking.empty or "Start_Chainage" not in cracking.columns:
        return segments
    lane_col = "Source_Lane_Folder" if "Source_Lane_Folder" in cracking.columns else "Lane"
    grouped = cracking.groupby(cracking[lane_col].map(normalize_lane), sort=False)
    for lane, group in grouped:
        group = group.reset_index(drop=True)
        start = pd.to_numeric(group["Start_Chainage"], errors="coerce").astype(float)
        if "End_Chainage" in group.columns:
            end = pd.to_numeric(group["End_Chainage"], errors="coerce").astype(float)
        else:
            end = start + _SEGMENT_M
        segments[lane] = pd.DataFrame(
            {
                "lo": np.fmin(start, end),
                "hi": np.fmax(start, end),
                "pos": np.arange(len(group)),
                "img": group["Image_Name"].values if "Image_Name" in group.columns else None,
                "lat": pd.to_numeric(group["Start_Lat"], errors="coerce").values if "Start_Lat" in group.columns else np.nan,
                "lon": pd.to_numeric(group["Start_Lon"], errors="coerce").values if "Start_Lon" in group.columns else np.nan,
                "date": group["SurveyDate"].values if "SurveyDate" in group.columns else None,
            }
        )
    return segments


def image_file_index(image_root) -> dict[tuple[str, int], set[str]]:
    found: dict[tuple[str, int], set[str]] = defaultdict(set)
    root = Path(image_root) if image_root else None
    if root is None or not root.is_dir():
        return found
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            match = re.search(r"_([LR]\d+)_(\d+)_(\d+)\.(?:jpe?g|png)$", name, re.I)
            if match:
                found[(match.group(1).upper(), int(match.group(3)))].add(name)
    return found


def map_pothole_segments(frame: pd.DataFrame, segments: dict, images: dict) -> pd.DataFrame:
    rows = []
    for _, row in frame.iterrows():
        result = {"img": None, "src": None, "lat": np.nan, "lon": np.nan, "date": None}
        lane = normalize_lane(row.get("Lane"))
        segment = segments.get(lane)
        chainage = pd.to_numeric(row.get("Start_Chainage"), errors="coerce")
        if segment is not None and pd.notna(chainage):
            hit = segment[(segment["lo"] <= chainage) & (segment["hi"] > chainage)]
            if hit.empty:
                distance = np.minimum((segment["lo"] - chainage).abs(), (segment["hi"] - chainage).abs())
                if distance.min() <= _SEGMENT_M:
                    hit = segment[distance == distance.min()]
            if not hit.empty:
                chosen = hit.iloc[0]
                result.update(lat=chosen["lat"], lon=chosen["lon"], date=chosen["date"])
                names = images.get((lane, int(chosen["pos"])), set())
                if len(names) == 1:
                    result.update(img=next(iter(names)), src="segment_frame_image_file")
                elif pd.notna(chosen["img"]) and str(chosen["img"]).strip():
                    result.update(img=str(chosen["img"]).strip(), src="backup_cracking_segment")
                elif len(names) > 1:
                    result["src"] = "ambiguous_frame"
        rows.append(result)
    return pd.DataFrame(rows, index=frame.index)


def resolve_potholes(d4, d2, cracking, image_root, survey_end=None, force_d2: bool = False) -> tuple[pd.DataFrame, str | None]:
    """D4 wins. D2 fills image, lat, long, and date from the cracking 10 m segment."""
    if force_d2:
        d4 = pd.DataFrame()
    segments = build_segment_index(cracking)
    images = image_file_index(image_root)
    if (d4 is None or d4.empty) and d2 is not None and not d2.empty:
        d2 = d2.copy()
        mapped = map_pothole_segments(d2, segments, images)
        missing_image = d2["Image_Name"].isna()
        d2.loc[missing_image, "Image_Name"] = mapped.loc[missing_image, "img"]
        d2["Image_Source"] = np.where(missing_image, mapped["src"], "d2_sheet")
        d2["Latitude"] = d2["Latitude"].fillna(pd.to_numeric(mapped["lat"], errors="coerce"))
        d2["Longitude"] = d2["Longitude"].fillna(pd.to_numeric(mapped["lon"], errors="coerce"))
        d2["Survey_Date"] = pd.to_datetime(d2["Survey_Date"], errors="coerce").fillna(
            pd.to_datetime(mapped["date"], errors="coerce")
        )
        if d2["Survey_Date"].isna().all() and survey_end:
            d2["Survey_Date"] = pd.Timestamp(survey_end)
        return d2, "D2"
    if d4 is not None and not d4.empty:
        d4 = d4.copy()
        d4["Pothole_Source"] = "D4"
        return d4, "D4"
    return pd.DataFrame(), None
