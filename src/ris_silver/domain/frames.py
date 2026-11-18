"""Lane frames. A backup row longer than 10 m is split from its own start chainage.

103–118 becomes 103–113 and 113–118. The start is not snapped onto the 10 m grid.
Roughness metric is BI, then IRI. Cracking CA breach is value > threshold.
Every other breach flag is value >= threshold. Lat, area, wheel-path values,
crack width, and the image name stay on every piece.
"""

from __future__ import annotations

import math

import pandas as pd

from ris_silver.domain.lanes import direction_of_lane, normalize_lane, side_of_lane

_COLUMNS = [
    "lane", "side", "direction",
    "start_chainage", "end_chainage", "length_m",
    "metric_name", "metric_value",
    "start_lat", "start_long", "end_lat", "end_long",
    "survey_date", "condition",
    "ca_breach", "irc_breach", "ca_threshold", "irc_threshold",
]


def _float(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def _int(value):
    number = _float(value)
    return int(number) if number is not None else None


def _text(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    return text or None


def _first(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        return value
    return None


def _flag_ge(value, threshold) -> int:
    if value is None or threshold is None:
        return 0
    return 1 if float(value) >= float(threshold) else 0


def _flag_gt(value, threshold) -> int:
    if value is None or threshold is None:
        return 0
    return 1 if float(value) > float(threshold) else 0


def _chainage(row) -> tuple[int | None, int | None]:
    start = _int(row.get("Start_Chainage"))
    end = _int(row.get("End_Chainage"))
    if start is None and end is None:
        return None, None
    if start is None:
        start = end
    if end is None:
        end = start
    if end < start:
        start, end = end, start
    return start, end


def expand_to_10m(rows: list[dict], step: int = 10) -> list[dict]:
    """Split from the row's own start. A row of ``step`` metres or less stays one piece.

    Chainage is rounded to the nearest metre first. The last piece ends at the
    real end, so it can be shorter than ``step``.
    """
    expanded = []
    for row in rows:
        start, end = row.get("start_chainage"), row.get("end_chainage")
        if start is None or end is None or end <= start:
            expanded.append(dict(row))
            continue
        start = int(round(float(start)))
        end = int(round(float(end)))
        if end <= start:
            piece = dict(row)
            piece["start_chainage"] = start
            piece["end_chainage"] = end
            expanded.append(piece)
            continue
        for seg_start in range(start, end, step):
            piece = dict(row)
            piece["start_chainage"] = seg_start
            piece["end_chainage"] = min(seg_start + step, end)
            piece["length_m"] = piece["end_chainage"] - piece["start_chainage"]
            expanded.append(piece)
    return expanded


def _base(row, lane, start, end, metric_name, metric_value, ca_threshold, irc_threshold, ca_breach, irc_breach) -> dict:
    return {
        "lane": lane,
        "side": side_of_lane(lane),
        "direction": direction_of_lane(lane),
        "start_chainage": start,
        "end_chainage": end,
        "length_m": None if start is None or end is None else end - start,
        "metric_name": metric_name,
        "metric_value": metric_value,
        "start_lat": _float(row.get("Start_Lat")),
        "start_long": _float(row.get("Start_Lon")),
        "end_lat": _float(row.get("End_Lat")),
        "end_long": _float(row.get("End_Lon")),
        "survey_date": row.get("SurveyDate"),
        "condition": _text(row.get("Condition")),
        "ca_breach": ca_breach,
        "irc_breach": irc_breach,
        "ca_threshold": ca_threshold,
        "irc_threshold": irc_threshold,
    }


def _roughness_probe(bi, metric):
    """IRC roughness uses BI, and treats 0 as missing, matching `roughness_bi or metric_value`."""
    if bi is None or bi == 0:
        return metric
    if isinstance(bi, float) and math.isnan(bi):
        return bi
    return bi


def build_canonical_frames(facts: dict, thresholds: dict) -> dict[str, pd.DataFrame]:
    ca = thresholds["ca"]
    irc = thresholds["irc_file"]
    return {
        "roughness": _frame("roughness", facts.get("roughness"), ca["roughness_bi"], irc["roughness_iri"]),
        "rutting": _frame("rutting", facts.get("rutting"), ca["rutting_mm"], irc["rutting_mm"]),
        "ravelling": _frame("ravelling", facts.get("ravelling"), ca["ravelling"], irc["ravelling"]),
        "cracking": _frame("cracking", facts.get("cracking"), ca["cracking_pct"], irc["cracking_pct"]),
    }


def _frame(defect: str, source, ca_threshold, irc_threshold) -> pd.DataFrame:
    if source is None or source.empty:
        return pd.DataFrame(columns=_COLUMNS)
    rows = []
    for _, row in source.iterrows():
        start, end = _chainage(row)
        if defect != "cracking" and start is None and end is None:
            continue
        lane = normalize_lane(row.get("Lane"))
        extra = {}
        if defect == "roughness":
            bi = _float(row.get("BI m/km"))
            iri = _float(row.get("IRI"))
            metric = _first(bi, iri)
            extra = {
                "roughness_bi": bi,
                "iri_value": iri,
                "lwp_iri": _float(row.get("LwpIri")),
                "rwp_iri": _float(row.get("RwpIri")),
            }
            ca_breach = _flag_ge(bi, ca_threshold)
            irc_breach = _flag_ge(_roughness_probe(bi, metric), irc_threshold)
            metric_name = "roughness_bi"
        elif defect == "rutting":
            metric = _float(row.get("Rutting"))
            extra = {
                "rutting_avg": metric,
                "rut_left": _float(row.get("Rutting Left")),
                "rut_right": _float(row.get("Rutting Right")),
            }
            ca_breach = _flag_ge(metric, ca_threshold)
            irc_breach = _flag_ge(metric, irc_threshold)
            metric_name = "rutting_avg"
        elif defect == "ravelling":
            metric = _float(row.get("Ravelling"))
            extra = {"ravelling_pct": metric, "rav_area_sqm": _float(row.get("Ravelling_Area_sq_m"))}
            ca_breach = _flag_ge(metric, ca_threshold)
            irc_breach = _flag_ge(metric, irc_threshold)
            metric_name = "ravelling_area"
        else:
            metric = _float(row.get("Cracking"))
            extra = {
                "cracking_pct": metric,
                "area_sq_m": _float(row.get("Area_sq_m")),
                "image_name": _text(row.get("Image_Name")),
                "crack_count": _float(row.get("crack_count")),
                "avg_corrected_width_mm": _float(row.get("avg_corrected_width_mm")),
                "avg_width_mm": _float(row.get("avg_width_mm")),
            }
            ca_breach = _flag_gt(metric, ca_threshold)
            irc_breach = _flag_ge(metric, irc_threshold)
            metric_name = "cracking_pct"
        record = _base(row, lane, start, end, metric_name, metric, ca_threshold, irc_threshold, ca_breach, irc_breach)
        record.update(extra)
        rows.append(record)
    rows = expand_to_10m(rows)
    frame = pd.DataFrame(rows)
    for column in _COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    return frame


def build_canonical(ctx):
    ctx.frames["canonical"] = build_canonical_frames(ctx.frames["facts"], ctx.frames["thresholds"])
    counts = {name: len(frame) for name, frame in ctx.frames["canonical"].items()}
    print("canonical 10m: " + " ".join(f"{name}={count}" for name, count in counts.items()))
    return ctx
