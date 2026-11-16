"""LHS/RHS silver tables.

Lane rows are rolled up first. A parent is one row per side per bin: the value is the
average of that side's lanes, and the side breaches if any lane breaches CA.
IRC children use the fixed cuts and breach only when the value is strictly greater.
"""

from __future__ import annotations

import json
import math

import pandas as pd

from ris_silver.domain.lanes import direction_of_lane, normalize_lane, side_of_lane
from ris_silver.domain.metrics import bi_from_iri, lane_iri
from ris_silver.domain.spec import POTHOLE_TABLE, linear_specs

_LINEAR = ("roughness", "rutting", "ravelling", "cracking")


def parent_id(upc: str, side: str, bin_start: int, length_m: int) -> str:
    return f"{upc}_{side}_{int(bin_start)}_{int(bin_start) + int(length_m)}"


def bin_start(chainage_m: float, length_m: int) -> int:
    length = int(length_m)
    return int(chainage_m // length) * length


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


def _mean(values) -> float | None:
    numbers = [number for number in (_num(value) for value in values) if number is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _flag_ge(value, threshold) -> int:
    if value is None or threshold is None:
        return 0
    return 1 if float(value) >= float(threshold) else 0


def _flag_gt(value, threshold) -> int:
    if value is None or threshold is None:
        return 0
    return 1 if float(value) > float(threshold) else 0


def rollup_lanes(frame: pd.DataFrame, defect: str, length_m: int, ca_threshold: float) -> pd.DataFrame:
    """One CA row per lane per bin. Cracking percent is summed area over the chainage span."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    work = frame.dropna(subset=["start_chainage"]).copy()
    if work.empty:
        return pd.DataFrame()
    work["bin"] = work["start_chainage"].map(lambda value: bin_start(value, length_m))
    rows = []
    for (lane, start), group in work.groupby(["lane", "bin"], dropna=False, sort=True):
        end = int(group["end_chainage"].max())
        span = float(end - int(group["start_chainage"].min()))
        length_sum = float(pd.to_numeric(group["length_m"], errors="coerce").fillna(0).sum())
        metric = _mean(group["metric_value"])
        area = None
        if defect == "roughness" and {"lwp_iri", "rwp_iri"} <= set(group.columns):
            left, right = _mean(group["lwp_iri"]), _mean(group["rwp_iri"])
            if left is not None and right is not None:
                metric = bi_from_iri(lane_iri(left, right))
        elif defect == "rutting" and {"rut_left", "rut_right"} <= set(group.columns):
            left, right = _mean(group["rut_left"]), _mean(group["rut_right"])
            if left is not None and right is not None:
                metric = (left + right) / 2.0
        elif defect == "ravelling" and "rav_area_sqm" in group.columns:
            covered = 3.5 * length_sum
            total_area = float(pd.to_numeric(group["rav_area_sqm"], errors="coerce").fillna(0).sum())
            if covered > 0:
                metric = total_area / covered * 100.0
        elif defect == "cracking":
            total_area = float(pd.to_numeric(group["area_sq_m"], errors="coerce").fillna(0).sum())
            area = total_area
            metric = round(total_area / (3.5 * span) * 100.0, 6) if span > 0 else None
        breach = _flag_gt(metric, ca_threshold) if defect == "cracking" else _flag_ge(metric, ca_threshold)
        lane_length = span if defect == "cracking" else length_sum
        rows.append({
            "lane": lane,
            "side": side_of_lane(lane),
            "direction": direction_of_lane(lane),
            "bin": int(start),
            "start_chainage": int(group["start_chainage"].min()),
            "end_chainage": end,
            "length_m": lane_length,
            "metric_value": metric,
            "ca_breach": breach,
            "area_sq_m": area,
            "start_lat": group["start_lat"].dropna().iloc[0] if "start_lat" in group and group["start_lat"].notna().any() else None,
            "start_long": group["start_long"].dropna().iloc[0] if "start_long" in group and group["start_long"].notna().any() else None,
            "end_lat": group["end_lat"].dropna().iloc[-1] if "end_lat" in group and group["end_lat"].notna().any() else None,
            "end_long": group["end_long"].dropna().iloc[-1] if "end_long" in group and group["end_long"].notna().any() else None,
        })
    return pd.DataFrame(rows)


def _parent_rows(lane_rows: pd.DataFrame, upc: str, table: str, length_m: int, ca_threshold: float) -> list[dict]:
    if lane_rows is None or lane_rows.empty:
        return []
    rows = []
    for (side, start), group in lane_rows.groupby(["side", "bin"], dropna=False, sort=True):
        start = int(start)
        lo = int(group["start_chainage"].min())
        hi = int(group["end_chainage"].max())
        values = pd.to_numeric(group["metric_value"], errors="coerce")
        breaches = pd.to_numeric(group["ca_breach"], errors="coerce").fillna(0).astype(int)
        breach = int(breaches.max())
        metric = round(float(values.mean()), 6) if values.notna().any() else None
        pid = parent_id(upc, side, start, length_m)
        lanes = [str(lane) for lane in group["lane"]]
        rows.append({
            "id": f"{upc}_{table}_{side}_{start}",
            "collection_name": table,
            "level": "parent",
            "upc": upc,
            "lane": side,
            "side": side,
            "direction": "Increasing" if side == "LHS" else "Decreasing",
            "parent_id": pid,
            "start_chainage": lo,
            "end_chainage": hi,
            "length_m": float(hi - lo),
            "total_length": float(pd.to_numeric(group["length_m"], errors="coerce").fillna(0).sum()),
            "parent_start_chainage": start,
            "parent_end_chainage": start + length_m,
            "reporting_interval_m": length_m,
            "metric_value": metric,
            "breach_flag": breach,
            "threshold_name": "As per CA",
            "threshold_value": float(ca_threshold),
            "road_condition": "Bad" if breach else "Good",
            "total_children": int(len(group)),
            "affected_length": float(sum(float(length) for length, flag in zip(group["length_m"], breaches) if int(flag) == 1)),
            "display_defect_id": None,
            "defect_id": pid if breach else None,
            "measures": json.dumps({
                "side": side,
                "lanes": sorted(lanes),
                "lane_values": {
                    str(lane): None if pd.isna(value) else round(float(value), 6)
                    for lane, value in zip(group["lane"], values)
                },
                "lane_breach": {str(lane): int(flag) for lane, flag in zip(group["lane"], breaches)},
                "calculation": (
                    f"{side} {start}-{start + length_m}: value = average of {len(group)} lane {length_m}m values; "
                    f"breach if any lane breaches the CA threshold ({ca_threshold})"
                ),
            }),
        })
    return rows


def _child_rows(lane_rows: pd.DataFrame, upc: str, table: str, kind: str, parent_length: int, ca_threshold: float, irc_threshold: float, interval_m: int) -> list[dict]:
    if lane_rows is None or lane_rows.empty:
        return []
    rows = []
    for _, row in lane_rows.iterrows():
        metric = _num(row["metric_value"])
        if kind == "irc100":
            breach = _flag_gt(metric, irc_threshold)
            threshold_name, threshold_value = "As per IRC", float(irc_threshold)
        else:
            breach = int(row["ca_breach"])
            threshold_name, threshold_value = "As per CA", float(ca_threshold)
        start = int(row["bin"]) if kind != "10m" else int(row["start_chainage"])
        parent_bin = bin_start(min(row["start_chainage"], row["end_chainage"]), parent_length)
        pid = parent_id(upc, row["side"], parent_bin, parent_length)
        length = _num(row["length_m"]) or 0.0
        rows.append({
            "id": f"{upc}_{table}_{row['lane']}_{int(row['start_chainage'])}_{int(row['end_chainage'])}",
            "collection_name": table,
            "level": "child_as_per_ca" if kind == "ca" else ("child_100m_irc" if kind == "irc100" else "child_10m"),
            "upc": upc,
            "lane": row["lane"],
            "side": row["side"],
            "direction": row["direction"],
            "parent_id": pid,
            "start_chainage": int(row["start_chainage"]),
            "end_chainage": int(row["end_chainage"]),
            "length_m": length,
            "parent_start_chainage": parent_bin,
            "parent_end_chainage": parent_bin + parent_length,
            "reporting_interval_m": interval_m,
            "metric_value": metric,
            "breach_flag": breach,
            "threshold_name": threshold_name,
            "threshold_value": threshold_value,
            "road_condition": ("Poor" if breach else "Good") if kind == "irc100" else None,
            "affected_length": length if breach else 0.0,
            "display_defect_id": None,
        })
    return rows


def _child_10m(frame: pd.DataFrame, upc: str, table: str, parent_length: int, ca_threshold: float, irc_threshold: float) -> list[dict]:
    if frame is None or frame.empty:
        return []
    rows = []
    for _, row in frame.dropna(subset=["start_chainage"]).iterrows():
        metric = _num(row["metric_value"])
        ca_breach = int(row["ca_breach"]) if _num(row.get("ca_breach")) is not None else 0
        irc_breach = _flag_gt(metric, irc_threshold)
        breach = max(ca_breach, irc_breach)
        parent_bin = bin_start(min(row["start_chainage"], row["end_chainage"]), parent_length)
        side = row["side"] if isinstance(row.get("side"), str) else side_of_lane(row["lane"])
        length = _num(row.get("length_m")) or 0.0
        rows.append({
            "id": f"{upc}_{table}_{row['lane']}_{int(row['start_chainage'])}_{int(row['end_chainage'])}",
            "collection_name": table,
            "level": "child_10m",
            "upc": upc,
            "lane": row["lane"],
            "side": side,
            "direction": direction_of_lane(row["lane"]),
            "parent_id": parent_id(upc, side, parent_bin, parent_length),
            "start_chainage": int(row["start_chainage"]),
            "end_chainage": int(row["end_chainage"]),
            "length_m": length,
            "parent_start_chainage": parent_bin,
            "parent_end_chainage": parent_bin + parent_length,
            "reporting_interval_m": 10,
            "metric_value": metric,
            "breach_flag": breach,
            "threshold_name": "As per CA & IRC",
            "threshold_value": None,
            "ca_threshold_value": float(ca_threshold),
            "irc_threshold_value": float(irc_threshold),
            "ca_breach_flag": ca_breach,
            "irc_breach_flag": irc_breach,
            "affected_length": length if breach else 0.0,
            "display_defect_id": None,
        })
    return rows


def _pothole_rows(frame: pd.DataFrame, upc: str, threshold_name: str) -> list[dict]:
    if frame is None or frame.empty:
        return []
    rows = []
    for index, row in frame.reset_index(drop=True).iterrows():
        lane = normalize_lane(row.get("Lane"))
        start = _num(row.get("Start_Chainage"))
        end = _num(row.get("End_Chainage"))
        area = _num(row.get("Area_sq_m"))
        record_id = f"{upc}_{POTHOLE_TABLE}_{index + 1:06d}"
        rows.append({
            "id": record_id,
            "collection_name": POTHOLE_TABLE,
            "level": "parent",
            "upc": upc,
            "lane": lane,
            "side": side_of_lane(lane),
            "direction": direction_of_lane(lane),
            "parent_id": record_id,
            "start_chainage": None if start is None else int(start),
            "end_chainage": None if end is None else int(end),
            "length_m": None if start is None or end is None else max(int(end) - int(start), 0),
            "metric_name": "area_sq_m",
            "metric_value": area,
            "breach_flag": 1,
            "threshold_name": threshold_name,
            "threshold_value": 0.0,
            "image_name": None if pd.isna(row.get("Image_Name")) else row.get("Image_Name"),
            "display_defect_id": None,
        })
    return rows


def _sort_key(row: dict):
    return (
        row.get("side") is None,
        row.get("side") or "",
        row.get("lane") is None,
        row.get("lane") or "",
        row.get("start_chainage") is None,
        row.get("start_chainage") if row.get("start_chainage") is not None else 0,
        row.get("id") or "",
    )


def _stamp_top(rows: list[dict], seq: int, date_str: str) -> int:
    breach_rows = sorted((row for row in rows if int(row.get("breach_flag") or 0) == 1), key=_sort_key)
    for offset, row in enumerate(breach_rows, start=1):
        row["display_defect_id"] = f"D/{date_str}/N/{seq + offset:05d}"
    return seq + len(breach_rows)


def _stamp_children(children: list[dict], parents: list[dict], seq: int, date_str: str) -> int:
    lookup = {
        row["parent_id"]: row["display_defect_id"]
        for row in parents
        if row.get("display_defect_id")
    }
    linked: dict[str, list[dict]] = {}
    orphans = []
    for row in children:
        if int(row.get("breach_flag") or 0) != 1:
            continue
        parent_display = lookup.get(row.get("parent_id"))
        if parent_display:
            linked.setdefault(row["parent_id"], []).append(row)
        else:
            orphans.append(row)
    for group in linked.values():
        for offset, row in enumerate(sorted(group, key=_sort_key), start=1):
            row["display_defect_id"] = f"{lookup[row['parent_id']]}/{offset:04d}"
    return _stamp_top(orphans, seq, date_str)


def assign_display_ids(tables: dict[str, list[dict]], specs: dict, date_str: str, start_seq: int = 0) -> int:
    """Breach parents are numbered first. A breach child uses the parent's id, or its own if the parent is clean."""
    seq = start_seq
    order = list(_LINEAR) + ["pothole"]
    parent_name = {defect: specs[defect].parent.table for defect in _LINEAR}
    parent_name["pothole"] = POTHOLE_TABLE
    for defect in order:
        seq = _stamp_top(tables.get(parent_name[defect], []), seq, date_str)
    for defect in _LINEAR:
        parents = tables.get(parent_name[defect], [])
        for level in specs[defect].children:
            seq = _stamp_children(tables.get(level.table, []), parents, seq, date_str)
    return seq


def build_silver_tables(canonical: dict, potholes, upc: str, specs: dict, ca: dict, irc: dict, ca_interval_m: int, survey_end, pothole_threshold_name: str = "As per CA") -> dict[str, pd.DataFrame]:
    tables: dict[str, list[dict]] = {}
    for defect in _LINEAR:
        spec = specs[defect]
        parent_length = int(spec.parent.length_m)
        lanes_parent = rollup_lanes(canonical.get(defect), defect, parent_length, ca[defect])
        tables[spec.parent.table] = _parent_rows(lanes_parent, upc, spec.parent.table, parent_length, ca[defect])
        lanes_100 = rollup_lanes(canonical.get(defect), defect, 100, ca[defect]) if parent_length != 100 else lanes_parent
        lanes_ca = rollup_lanes(canonical.get(defect), defect, ca_interval_m, ca[defect])
        for level in spec.children:
            if level.kind == "ca":
                tables[level.table] = _child_rows(lanes_ca, upc, level.table, "ca", parent_length, ca[defect], irc[defect], ca_interval_m)
            elif level.kind == "irc100":
                tables[level.table] = _child_rows(lanes_100, upc, level.table, "irc100", parent_length, ca[defect], irc[defect], 100)
            elif level.kind == "10m":
                tables[level.table] = _child_10m(canonical.get(defect), upc, level.table, parent_length, ca[defect], irc[defect])
    tables[POTHOLE_TABLE] = _pothole_rows(potholes, upc, pothole_threshold_name)
    date_str = survey_end.strftime("%d%m%y") if hasattr(survey_end, "strftime") else "000000"
    assign_display_ids(tables, specs, date_str)
    return {name: pd.DataFrame(rows) for name, rows in tables.items()}


def build_hierarchy(ctx):
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
    correction = ctx.frames.get("correction") or {}
    ca_interval = int(correction.get("ca_interval_m") or intervals["child_100m"])
    survey_end = (ctx.frames.get("tracker") or {}).get("survey_end_date")
    threshold_name = "As per CA"
    tracker = ctx.frames.get("tracker") or {}
    override = tracker.get("threshold_label_override")
    if override:
        threshold_name = override
    ctx.frames["tables"] = build_silver_tables(
        ctx.frames["canonical"],
        ctx.frames["facts"].get("potholes"),
        ctx.upc,
        specs,
        ca,
        irc,
        ca_interval,
        survey_end,
        threshold_name,
    )
    summary = []
    for name, frame in ctx.frames["tables"].items():
        breaches = 0 if frame.empty or "breach_flag" not in frame.columns else int((frame["breach_flag"] == 1).sum())
        summary.append(f"{name}={len(frame)}/{breaches}")
    print("hierarchy: " + ", ".join(summary))
    return ctx
