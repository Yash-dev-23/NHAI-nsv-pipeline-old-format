"""PCI, NH number, and the two ratings, written onto the hierarchy tables.

PCI joins on the row's own interval: 10 m, 100 m, or 1 km. A side parent takes
the PCI of the lane that starts first in that bin.

rating_ca is the CA label of the row. A side parent takes the label of the lane
with the highest metric. rating_irc is filled on 10 m rows (D3, otherwise
Good/Poor on the fixed IRC cut) and on every cracking row (the IRC bands).
Cracking Good/Poor and the IRC bands replace the D3 cracking category.
Severity uses corrected crack width, then raw width. A longer row weights by crack count.
"""

from __future__ import annotations

import json
import math
import re

import pandas as pd

from ris_silver.domain.conditions import ravelling_condition, roughness_condition, rutting_condition
from ris_silver.domain.cracking import severity
from ris_silver.domain.hierarchy import bin_start, rollup_lanes
from ris_silver.domain.lanes import direction_of_lane, normalize_direction, normalize_lane, side_of_lane
from ris_silver.domain.pci import DEFAULT_WEIGHTS, build_pci
from ris_silver.domain.spec import POTHOLE_TABLE, linear_specs
from ris_silver.ingest.patching import load_patching

_NH_RE = re.compile(r"^\s*(?:N\.?\s*H\.?)?\s*[-_/ ]*0*(\d+)\s*([A-Za-z]*)\s*$", re.I)
_D3_NAME = {
    "cracking": "Cracking",
    "roughness": "Roughness",
    "rutting": "Rutting",
    "ravelling": "Ravelling",
    "pothole": "Pothole",
}


def standardize_nh_number(value) -> str | None:
    """NH0027 → NH-27, NH151A → NH-151A, 'NH 8a' → NH-8A, '27' → NH-27."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    if not text or text == "<NA>":
        return None
    match = _NH_RE.match(text)
    if not match:
        return text.upper()
    return f"NH-{int(match.group(1))}{match.group(2).upper()}"


def _num(value):
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


def _pick_col(columns, *candidates) -> str | None:
    folded = {"".join(ch.lower() for ch in str(column) if ch.isalnum()): column for column in columns}
    for candidate in candidates:
        key = "".join(ch.lower() for ch in candidate if ch.isalnum())
        if key in folded:
            return folded[key]
    for candidate in candidates:
        key = "".join(ch.lower() for ch in candidate if ch.isalnum())
        for column in columns:
            if key and key in "".join(ch.lower() for ch in str(column) if ch.isalnum()):
                return column
    return None


def _as_chainage(value):
    number = _num(value)
    if number is None:
        return None
    return int(round(number))


def _plain(value) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    if not text or text == "<NA>":
        return None
    return text


def prepare_lrms(frame) -> pd.DataFrame:
    columns = ["chainage", "nh_number", "section_code", "direction"]
    if frame is None or frame.empty:
        return pd.DataFrame(columns=columns)
    chain = _pick_col(frame.columns, "Chainage")
    nh = _pick_col(frame.columns, "NHNumber", "New NH number", "New NH number NHNumber")
    section = _pick_col(frame.columns, "SectionCode", "Section")
    direction = _pick_col(frame.columns, "Direction")
    rows = []
    for _, row in frame.iterrows():
        chainage = _as_chainage(row[chain]) if chain else None
        if chainage is None:
            continue
        rows.append({
            "chainage": chainage,
            "nh_number": standardize_nh_number(row[nh]) if nh else None,
            "section_code": _plain(row[section]) if section else None,
            "direction": normalize_direction(row[direction]) if direction else None,
        })
    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)


def _intervals(frame, fields: dict[str, tuple[str, ...]]) -> pd.DataFrame:
    columns = ["start_chainage", "end_chainage", "direction", *fields]
    if frame is None or frame.empty:
        return pd.DataFrame(columns=columns)
    start = _pick_col(frame.columns, "New NH number StartChainage", "Start_Chainage")
    end = _pick_col(frame.columns, "New NH number EndChainage", "End_Chainage")
    direction = _pick_col(frame.columns, "Direction")
    chosen = {name: _pick_col(frame.columns, *candidates) for name, candidates in fields.items()}
    rows = []
    for _, row in frame.iterrows():
        lo = _as_chainage(row[start]) if start else None
        hi = _as_chainage(row[end]) if end else None
        if lo is None and hi is None:
            continue
        if lo is None:
            lo = hi
        if hi is None:
            hi = lo
        if hi < lo:
            lo, hi = hi, lo
        record = {
            "start_chainage": lo,
            "end_chainage": hi,
            "direction": normalize_direction(row[direction]) if direction else None,
        }
        for name, column in chosen.items():
            if not column:
                record[name] = None
            elif name == "nh_number":
                record[name] = standardize_nh_number(row[column])
            else:
                record[name] = _plain(row[column])
        rows.append(record)
    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)


def prepare_pavement(frame) -> pd.DataFrame:
    return _intervals(frame, {
        "nh_number": ("New NH number NHNumber", "NHNumber"),
        "section_code": ("SectionCode", "Section"),
        "pavement_type": ("PavementType", "Surface Type"),
    })


def prepare_carriageway(frame) -> pd.DataFrame:
    return _intervals(frame, {
        "nh_number": ("New NH number", "NHNumber"),
        "section_code": ("SectionCode",),
        "carriageway": ("CarriagewayType",),
    })


def _same_direction(frame: pd.DataFrame, direction: str | None) -> pd.DataFrame:
    """Keep rows for this direction. Cache lives on the frame, not on id(frame).

    id() is reused after the previous enrich() frames are freed. A global cache
    then handed the LRMS frame to the pavement lookup, which has no start_chainage.
    """
    if frame is None or frame.empty or direction is None or "direction" not in frame.columns:
        return frame
    normalized = direction.strip().lower()
    cache = frame.attrs.get("_direction_cache")
    if isinstance(cache, dict) and normalized in cache:
        return cache[normalized]
    same = frame[frame["direction"].fillna("").astype(str).str.strip().str.lower() == normalized]
    filtered = same if not same.empty else frame
    # A frame must not sit inside its own attrs. The next slice deep-copies attrs,
    # and a missing direction makes `filtered` the frame itself.
    snapshot = filtered.copy()
    snapshot.attrs.clear()
    if not isinstance(cache, dict):
        cache = {}
        frame.attrs["_direction_cache"] = cache
    cache[normalized] = snapshot
    return snapshot


def _nh_value(row) -> str | None:
    value = row["nh_number"] if "nh_number" in row else None
    if _num(value) is None and not isinstance(value, str):
        return None
    text = standardize_nh_number(value)
    return text


def _field(row, name: str, *, nh: bool = False):
    if row is None or name not in row.index:
        return None
    if nh:
        return _nh_value(row) if name == "nh_number" else standardize_nh_number(row[name])
    value = row[name]
    return _plain(value)


def _nearest_row(frame, probe, direction):
    if frame is None or frame.empty or probe is None or "chainage" not in frame.columns:
        return None
    points = _same_direction(frame, direction)
    if points is None or points.empty or "chainage" not in points.columns:
        return None
    distance = (pd.to_numeric(points["chainage"], errors="coerce") - probe).abs()
    return points.loc[distance.idxmin()]


def _interval_row(frame, probe, direction):
    """Half-open [start, end). The last chainage of the road may sit on the end."""
    if frame is None or frame.empty or probe is None or "start_chainage" not in frame.columns:
        return None
    spans = _same_direction(frame, direction)
    if spans is None or spans.empty or "start_chainage" not in spans.columns or "end_chainage" not in spans.columns:
        return None
    half = spans[(spans["start_chainage"] <= probe) & (spans["end_chainage"] > probe)]
    if half.empty:
        half = spans[(spans["start_chainage"] <= probe) & (spans["end_chainage"] >= probe)]
    if half.empty:
        distance = pd.concat(
            [(spans["start_chainage"] - probe).abs(), (spans["end_chainage"] - probe).abs()],
            axis=1,
        ).min(axis=1)
        return spans.loc[distance.idxmin()]
    if len(half) > 1:
        widths = half["end_chainage"] - half["start_chainage"]
        half = half.loc[widths.sort_values().index]
    return half.iloc[0]


def nh_at(lrms: pd.DataFrame, pavement: pd.DataFrame, chainage, lane, direction) -> str | None:
    """LRMS nearest point wins. Pavement interval is used when LRMS has no number."""
    side = direction_of_lane(lane) or normalize_direction(direction)
    probe = _num(chainage)
    if probe is None:
        return None
    found = _field(_nearest_row(lrms, probe, side), "nh_number", nh=True)
    if found:
        return found
    return _field(_interval_row(pavement, probe, side), "nh_number", nh=True)


def pavement_for_span(pavement, start, end, lane, direction) -> str | None:
    """Pavement of [start, end). One overlapping D1 type is kept. More than one is Hybrid.

    A row that sits outside every D1 interval keeps the nearest-edge type.
    """
    found = _pavement_overlap(pavement, start, end, lane, direction)
    if found:
        return found
    side = direction_of_lane(lane) or normalize_direction(direction)
    probe = _num(start)
    if probe is None:
        probe = _num(end)
    return _field(_interval_row(pavement, probe, side), "pavement_type")


def _pavement_overlap(pavement, start, end, lane, direction) -> str | None:
    if pavement is None or pavement.empty or "pavement_type" not in getattr(pavement, "columns", []):
        return None
    start_n, end_n = _num(start), _num(end)
    if start_n is None and end_n is None:
        return None
    if start_n is None:
        start_n = end_n
    if end_n is None:
        end_n = start_n
    if end_n < start_n:
        start_n, end_n = end_n, start_n
    if end_n == start_n:
        return None
    side = direction_of_lane(lane) or normalize_direction(direction)
    spans = _same_direction(pavement, side)
    if spans is None or spans.empty:
        return None
    types = []
    for _, row in spans.iterrows():
        lo, hi = _num(row.get("start_chainage")), _num(row.get("end_chainage"))
        if lo is None or hi is None:
            continue
        if hi < lo:
            lo, hi = hi, lo
        if lo < end_n and hi > start_n:
            text = _plain(row.get("pavement_type"))
            if text and text not in types:
                types.append(text)
    if not types:
        return None
    if len(types) > 1:
        return "Hybrid"
    return types[0]


def road_context(lrms, pavement, carriageway, chainage, lane, direction) -> dict:
    """NH and section from LRMS, then pavement. Pavement type and carriageway stay on their own tables."""
    side = direction_of_lane(lane) or normalize_direction(direction)
    probe = _num(chainage)
    lrms_row = _nearest_row(lrms, probe, side)
    pavement_row = _interval_row(pavement, probe, side)
    carriage_row = _interval_row(carriageway, probe, side)
    return {
        "nh_number": _field(lrms_row, "nh_number", nh=True) or _field(pavement_row, "nh_number", nh=True),
        "section_code": _field(lrms_row, "section_code") or _field(pavement_row, "section_code"),
        "pavement_type": _field(pavement_row, "pavement_type"),
        "carriageway": _field(carriage_row, "carriageway"),
    }


def ca_rating(defect: str, metric, threshold) -> str | None:
    """CA label of one metric. Cracking uses the Good/Poor visual, not the five CA bands."""
    metric = _num(metric)
    if metric is None or threshold is None:
        return None
    if defect == "cracking":
        return "Good" if metric <= float(threshold) else "Poor"
    if defect == "roughness":
        return roughness_condition(None, metric, threshold)
    if defect == "rutting":
        return rutting_condition(metric, threshold)
    if defect == "ravelling":
        return ravelling_condition(metric, threshold)
    return None


def crack_irc_visual(metric) -> str | None:
    """IRC cracking bands. The lower edge of each band is included."""
    metric = _num(metric)
    if metric is None:
        return None
    if metric >= 30:
        return "Very Poor (>30%)"
    if metric >= 20:
        return "Poor (20-30%)"
    if metric >= 10:
        return "Fair (10-20%)"
    if metric >= 5:
        return "Good (5-10%)"
    return "Very Good (<5%)"


def _crack_color(metric, threshold, irc: bool) -> str | None:
    metric = _num(metric)
    if metric is None:
        return None
    if irc:
        if metric >= 30:
            return "#e31a1c"
        if metric >= 20:
            return "#ff7f00"
        if metric >= 10:
            return "#fff14b"
        if metric >= 5:
            return "#0f6ad0"
        return "#2a8524"
    return "#2a8524" if metric <= float(threshold) else "#e31a1c"


def worst_ca_rating(metrics, defect: str, threshold) -> str | None:
    """Parent rating is the lane with the highest metric, not the rating of the average."""
    numbers = [number for number in (_num(value) for value in metrics) if number is not None]
    if not numbers:
        return None
    return ca_rating(defect, max(numbers), threshold)


def _grid(interval) -> tuple[str, int]:
    if interval is None or int(interval) < 100:
        return "10m", 10
    if int(interval) < 1000:
        return "100m", 100
    return "1km", 1000


def _pci_index(lookups: dict) -> dict[str, dict]:
    indexed = {}
    for level, frame in lookups.items():
        if frame is None or frame.empty:
            indexed[level] = {}
            continue
        indexed[level] = {
            (str(row.lane), int(row.start_chainage)): float(row.pci)
            for row in frame.itertuples(index=False)
        }
    return indexed


def _d3_index(d3: dict) -> dict:
    found = {}
    for defect, label in _D3_NAME.items():
        frame = (d3 or {}).get(label)
        if frame is None or getattr(frame, "empty", True):
            continue
        for row in frame.itertuples(index=False):
            condition = row.Condition
            if pd.isna(condition):
                continue
            found[(defect, normalize_lane(row.Lane) or str(row.Lane), int(row.bin_100m))] = str(condition)
    return found


def _lane_choice(canonical, defect: str, length: int, threshold: float) -> dict:
    """Per side bin: the lane that starts first, and the highest lane metric."""
    lanes = rollup_lanes(canonical.get(defect), defect, length, threshold)
    choice = {}
    if lanes is None or lanes.empty:
        return choice
    for (side, start), group in lanes.groupby(["side", "bin"], dropna=False, sort=True):
        values = pd.to_numeric(group["metric_value"], errors="coerce")
        first = group.loc[pd.to_numeric(group["start_chainage"], errors="coerce").idxmin()]
        worst = _num(values.max()) if values.notna().any() else None
        choice[(side, int(start))] = {
            "lane": first["lane"],
            "start": int(first["start_chainage"]),
            "worst": worst,
        }
    return choice


def _irc_or_d3(defect, metric, lane, start, irc_threshold, d3_index) -> str | None:
    if start is None:
        return None
    visual = d3_index.get((defect, normalize_lane(lane) or lane, bin_start(start, 100)))
    if visual:
        return visual
    metric = _num(metric)
    if metric is None:
        return None
    return "Poor" if metric > float(irc_threshold) else "Good"


def _measures(existing, extra: dict) -> str:
    payload = json.dumps(extra)
    text = "" if existing is None or (isinstance(existing, float) and math.isnan(existing)) else str(existing).strip()
    if not text or text == "{}":
        return payload
    if text.endswith("}"):
        return text[:-1] + ", " + payload[1:]
    return payload


def _is_irc_name(threshold_name, kind: str) -> bool:
    """An IRC row is named for IRC alone. 'As per CA & IRC' stays the CA row."""
    name = "" if threshold_name is None else str(threshold_name).lower()
    if "ca" in name:
        return False
    if "irc" in name:
        return True
    return kind == "irc100"


def _crack_pieces(frame) -> list[dict]:
    if frame is None or getattr(frame, "empty", True):
        return []
    pieces = []
    for row in frame.itertuples(index=False):
        lane = normalize_lane(getattr(row, "lane", None))
        if lane is None:
            continue
        pieces.append({
            "lane": lane,
            "start": _num(getattr(row, "start_chainage", None)),
            "end": _num(getattr(row, "end_chainage", None)),
            "count": _num(getattr(row, "crack_count", None)) or 0.0,
            "corrected": _num(getattr(row, "avg_corrected_width_mm", None)),
            "raw": _num(getattr(row, "avg_width_mm", None)),
        })
    return pieces


def _piece_width(corrected, raw) -> float | None:
    if corrected is not None:
        return float(corrected)
    if raw is not None:
        return float(raw)
    return None


def severity_width(pieces: list[dict], lane, start, end, kind: str, side=None) -> float:
    """Corrected width, else raw width. A bin is the crack-count-weighted mean.

    A 10 m row uses its own piece. A longer row weights each piece by crack_count.
    No width and no count both become 0, which is the None band.
    """
    start = _num(start)
    end = _num(end)
    if start is None:
        return 0.0
    if end is None or end < start:
        end = start
    wanted = side if side in {"LHS", "RHS"} else side_of_lane(lane)
    lane_name = normalize_lane(lane) or lane
    matched = []
    for piece in pieces:
        if kind == "parent":
            if side_of_lane(piece["lane"]) != wanted:
                continue
        elif str(piece["lane"]) != str(lane_name):
            continue
        p0, p1 = piece["start"], piece["end"]
        if p0 is None:
            continue
        if p1 is None or p1 < p0:
            p1 = p0
        overlaps = p1 > start and p0 < end
        if not overlaps and p0 != start:
            continue
        matched.append(piece)
    if not matched:
        return 0.0
    if kind == "10m":
        exact = [piece for piece in matched if piece["start"] == start]
        piece = exact[0] if exact else matched[0]
        width = _piece_width(piece["corrected"], piece["raw"])
        return 0.0 if width is None else width
    total = 0.0
    weighted = 0.0
    for piece in matched:
        count = float(piece["count"] or 0.0)
        width = _piece_width(piece["corrected"], piece["raw"])
        weighted += (0.0 if width is None else width) * count
        total += count
    if total <= 0:
        return 0.0
    return weighted / total


def _crack_extra(metric, threshold, own_irc: bool, width: float) -> dict:
    label = severity(width)
    return {
        "severity_width_mm": round(float(width), 4),
        "severity": label,
        "visual_condition_ca": ca_rating("cracking", metric, threshold),
        "condition_color_ca": _crack_color(metric, threshold, False),
        "visual_condition_irc": crack_irc_visual(metric),
        "condition_color_irc": _crack_color(metric, threshold, True),
        "condition_color": _crack_color(metric, threshold, own_irc),
    }


def enrich(ctx):
    """Fill pci, nh_number, rating_ca, and rating_irc on the hierarchy tables."""
    canonical = ctx.frames.get("canonical") or {}
    facts = ctx.frames.get("facts") or {}
    weights = (ctx.pipeline or {}).get("pci_weights") or DEFAULT_WEIGHTS
    backup = (ctx.frames.get("layout") or {}).get("backup")
    patching = load_patching(backup)
    lookups = build_pci(canonical, facts.get("potholes"), patching, weights)
    ctx.frames["patching"] = patching
    ctx.frames["pci"] = lookups
    d1 = facts.get("d1") or {}
    lrms = prepare_lrms(d1.get("lrms"))
    pavement = prepare_pavement(d1.get("pavement"))
    d3_index = _d3_index(facts.get("d3") or {})
    intervals = ctx.pipeline["intervals"]
    specs = linear_specs(int(intervals["parent_m"]), int(intervals["child_100m"]), int(intervals["child_10m"]))
    ca_raw = ctx.frames["thresholds"]["ca"]
    ca = {
        "roughness": float(ca_raw["roughness_bi"]),
        "rutting": float(ca_raw["rutting_mm"]),
        "ravelling": float(ca_raw["ravelling"]),
        "cracking": float(ca_raw["cracking_pct"]),
    }
    irc = {
        "roughness": float(ctx.irc["roughness_mm_per_km"]),
        "rutting": float(ctx.irc["rutting_mm"]),
        "cracking": float(ctx.irc["cracking_percent"]),
        "ravelling": float(ctx.irc["ravelling_percent"]),
    }
    choice = {}
    kind_of = {}
    for defect, spec in specs.items():
        if spec.parent is not None:
            kind_of[spec.parent.table] = (defect, "parent")
            choice[defect] = _lane_choice(canonical, defect, int(spec.parent.length_m), ca[defect])
        for level in spec.children:
            kind_of[level.table] = (defect, level.kind)
    pci_at = _pci_index(lookups)
    crack_widths = _crack_pieces(canonical.get("cracking"))
    tables = ctx.frames.get("tables") or {}
    kind_of[POTHOLE_TABLE] = ("pothole", "parent")
    potholes = facts.get("potholes")
    filled = 0
    for name, frame in list(tables.items()):
        if frame is None or frame.empty or name not in kind_of:
            continue
        defect, kind = kind_of[name]
        updated = _fill_table(
            frame, defect, kind, ca, irc, choice, pci_at, d3_index, lrms, pavement, potholes, crack_widths,
        )
        filled += int(updated["pci"].notna().sum()) if "pci" in updated.columns else 0
        tables[name] = updated
    ctx.frames["tables"] = tables
    print(f"enrich: pci filled on {filled} rows")
    return ctx


def _fill_table(frame, defect, kind, ca, irc, choice, pci_at, d3_index, lrms, pavement, potholes, crack_widths=None):
    work = frame.copy()
    pothole_severity = _pothole_severity(potholes, len(work)) if defect == "pothole" else []
    pci_vals, ca_vals, irc_vals, nh_vals, roads, severities, measures, pavements = [], [], [], [], [], [], [], []
    has_measures = "measures" in work.columns
    for index, row in work.reset_index(drop=True).iterrows():
        rate_metric = _num(row.get("metric_value"))
        lane = row.get("lane")
        start = _num(row.get("start_chainage"))
        interval = row.get("reporting_interval_m")
        if defect != "pothole" and kind == "parent":
            picked = choice.get(defect, {}).get((row.get("side"), int(row.get("parent_start_chainage") or 0)))
            if picked:
                lane = picked["lane"]
                start = picked["start"]
                rate_metric = picked["worst"]
        level, grid = _grid(10 if defect == "pothole" else interval)
        join = None if start is None else bin_start(start, grid)
        pci_vals.append(None if join is None else pci_at.get(level, {}).get((str(lane), join)))
        nh_vals.append(nh_at(lrms, pavement, row.get("start_chainage"), row.get("lane"), row.get("direction")))
        pavements.append(pavement_for_span(
            pavement, row.get("start_chainage"), row.get("end_chainage"), row.get("lane"), row.get("direction"),
        ))
        ca_vals.append(_rating_ca(defect, kind, rate_metric, ca))
        irc_vals.append(_rating_irc(defect, kind, rate_metric, row, irc, d3_index))
        own_metric = _num(row.get("metric_value"))
        roads.append(_road(defect, kind, own_metric if defect == "cracking" else rate_metric, row, ca, d3_index))
        if defect == "cracking":
            width = severity_width(
                crack_widths or [],
                row.get("lane"),
                row.get("start_chainage"),
                row.get("end_chainage"),
                kind,
                row.get("side"),
            )
            severities.append(severity(width))
            own_irc = _is_irc_name(row.get("threshold_name"), kind)
            extra = _crack_extra(own_metric, ca["cracking"], own_irc, width)
            measures.append(_measures(row.get("measures"), extra))
        elif defect == "pothole":
            label = pothole_severity[index] if index < len(pothole_severity) else None
            ca_vals[-1] = label
            irc_vals[-1] = label
            severities.append(label)
            measures.append(row.get("measures") if has_measures else None)
        else:
            severities.append(None)
            measures.append(row.get("measures") if has_measures else None)
    work["pci"] = pci_vals
    work["rating_ca"] = ca_vals
    work["rating_irc"] = irc_vals
    work["nh_number"] = nh_vals
    work["pavement_type"] = pavements
    work["road_condition"] = roads
    if defect == "cracking":
        work["severity"] = severities
        if kind != "parent":
            work["measures"] = measures
    elif defect == "pothole":
        work["severity"] = severities
    return work


def _rating_ca(defect, kind, metric, ca) -> str | None:
    if defect == "pothole":
        return None
    return ca_rating(defect, metric, ca.get(defect))


def _rating_irc(defect, kind, metric, row, irc, d3_index) -> str | None:
    if defect == "pothole":
        return None
    if defect == "cracking":
        return crack_irc_visual(metric)
    if kind == "10m":
        return _irc_or_d3(defect, _num(row.get("metric_value")), row.get("lane"), row.get("start_chainage"), irc[defect], d3_index)
    return None


def _road(defect, kind, metric, row, ca, d3_index=None):
    """Cracking uses its own standard. Other CA rows are Good or Bad. An IRC row uses D3."""
    if defect == "cracking":
        if _is_irc_name(row.get("threshold_name"), kind):
            return crack_irc_visual(metric)
        return ca_rating("cracking", metric, ca["cracking"])
    if _is_irc_name(row.get("threshold_name"), kind):
        if not d3_index or row.get("start_chainage") is None:
            return None
        lane = normalize_lane(row.get("lane")) or row.get("lane")
        return d3_index.get((defect, lane, bin_start(_num(row.get("start_chainage")), 100)))
    flag = _num(row.get("ca_breach_flag"))
    if flag is None:
        flag = _num(row.get("breach_flag"))
    return "Bad" if flag == 1 else "Good"


def _pothole_severity(frame, rows: int) -> list:
    if frame is None or frame.empty or "Severity" not in frame.columns or len(frame) != rows:
        return [None] * rows
    labels = []
    for value in frame["Severity"].tolist():
        if value is None or (isinstance(value, float) and math.isnan(value)):
            labels.append(None)
            continue
        text = str(value).strip()
        labels.append(text or None)
    return labels
