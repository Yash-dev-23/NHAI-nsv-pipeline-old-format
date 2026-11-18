"""master_chainage: one row per 10 m bin that has lane data, plus the LHS and RHS extent of that bin.

Source is the lane-wise 10 m rows of the four linear defects. A bin with no defect is left out.
"""

from __future__ import annotations

import math

import pandas as pd

from ris_silver.domain.lanes import normalize_lane
from ris_silver.domain.ratings import (
    pavement_for_span,
    prepare_carriageway,
    prepare_lrms,
    prepare_pavement,
    road_context,
)
from ris_silver.domain.spec import CHAINAGE_TABLE
from ris_silver.domain.table_contract import chainage_columns

_DEFECTS = ("roughness", "rutting", "ravelling", "cracking")
_GPS = ("start_lat", "start_long", "end_lat", "end_long")
_TEXT = ("pavement_type", "nh_number", "section_code", "carriageway")
_GRID = 10


def _lane_key(lane: str):
    rest = lane[1:]
    return (lane[0], int(rest) if rest.isdigit() else 99)


def _missing(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except TypeError:
        return False


def _first(values):
    for value in values:
        if not _missing(value):
            return value
    return None


def _num(value):
    if _missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def _pieces(canonical: dict, lrms, pavement, carriageway) -> pd.DataFrame:
    rows = []
    seq = 0
    for defect in _DEFECTS:
        frame = (canonical or {}).get(defect)
        if frame is None or frame.empty:
            continue
        for _, row in frame.iterrows():
            start = _num(row.get("start_chainage"))
            end = _num(row.get("end_chainage"))
            if start is None and end is None:
                continue
            if start is None:
                start = end
            if end is None:
                end = start
            if end < start:
                start, end = end, start
            lane = normalize_lane(row.get("lane"))
            if lane is None:
                continue
            context = road_context(lrms, pavement, carriageway, start, lane, row.get("direction"))
            context["pavement_type"] = pavement_for_span(pavement, start, end, lane, row.get("direction"))
            rows.append({
                "seq": seq,
                "lane": lane,
                "s": start,
                "e": end,
                "chainage_start": int(start // _GRID) * _GRID,
                **{name: _num(row.get(name)) for name in _GPS},
                **context,
            })
            seq += 1
    return pd.DataFrame(rows)


def _lane_bins(pieces: pd.DataFrame) -> pd.DataFrame:
    """One row per lane per 10 m bin. Chainage is the min start and the max end. Text and GPS keep the first value."""
    grouped = []
    for (lane, chainage), group in pieces.groupby(["lane", "chainage_start"], sort=False):
        ordered = group.sort_values("seq")
        grouped.append({
            "lane": lane,
            "chainage_start": int(chainage),
            "s": float(ordered["s"].min()),
            "e": float(ordered["e"].max()),
            **{name: _first(ordered[name]) for name in (*_GPS, *_TEXT)},
        })
    return pd.DataFrame(grouped)


def _side_block(bins: pd.DataFrame, chainage: int, prefix: str) -> dict:
    group = bins[bins["chainage_start"] == chainage]
    if group.empty:
        return {
            f"{prefix}_start_chainage": None,
            f"{prefix}_start_lat": None,
            f"{prefix}_start_long": None,
            f"{prefix}_pavement_type": None,
            f"{prefix}_end_chainage": None,
            f"{prefix}_end_lat": None,
            f"{prefix}_end_long": None,
            f"{prefix}_lanes": None,
        }
    ordered = group.assign(_key=group["lane"].map(_lane_key)).sort_values("_key")
    start = ordered.loc[ordered["s"].idxmin()]
    end = ordered.loc[ordered["e"].idxmax()]
    lanes = ",".join(sorted(ordered["lane"].unique(), key=_lane_key))
    return {
        f"{prefix}_start_chainage": float(start["s"]),
        f"{prefix}_start_lat": start["start_lat"],
        f"{prefix}_start_long": start["start_long"],
        f"{prefix}_pavement_type": start["pavement_type"],
        f"{prefix}_end_chainage": float(end["e"]),
        f"{prefix}_end_lat": end["end_lat"],
        f"{prefix}_end_long": end["end_long"],
        f"{prefix}_lanes": lanes,
    }


def build_master_chainage(canonical: dict, d1: dict, upc: str, zone: str, phase: str, cycle: str) -> pd.DataFrame:
    d1 = d1 or {}
    lrms = prepare_lrms(d1.get("lrms"))
    pavement = prepare_pavement(d1.get("pavement"))
    carriageway = prepare_carriageway(d1.get("carriageway"))
    pieces = _pieces(canonical, lrms, pavement, carriageway)
    if pieces.empty:
        return pd.DataFrame(columns=chainage_columns())
    bins = _lane_bins(pieces)
    surveyed = sorted(bins["lane"].unique(), key=_lane_key)
    lanes = _lanes_from(chainage_columns(surveyed))
    meta = bins.sort_values(["chainage_start", "lane"]).groupby("chainage_start", sort=True).first()
    upc_start = float(bins["s"].min())
    upc_end = float(bins["e"].max())
    stamp = pd.Timestamp.now()
    records = []
    for chainage in sorted(bins["chainage_start"].unique()):
        here = bins[bins["chainage_start"] == chainage]
        present = []
        record = {
            "upc": upc.replace("_", "/"),
            "upc_code": upc,
            "zone": zone,
            "phase": str(phase),
            "cycle": int(cycle),
            "chainage_start": int(chainage),
            "chainage_end": int(chainage) + _GRID,
            "upc_start_chainage": upc_start,
            "upc_end_chainage": upc_end,
        }
        for lane in lanes:
            prefix = lane.lower()
            hit = here[here["lane"] == lane]
            filled = not hit.empty
            if filled:
                present.append(lane)
            source = hit.iloc[0] if filled else None
            record[f"{prefix}_start_chainage"] = None if source is None else float(source["s"])
            record[f"{prefix}_end_chainage"] = None if source is None else float(source["e"])
            for name in _GPS:
                record[f"{prefix}_{name}"] = None if source is None else source[name]
        for side, mask_name in (("lhs", "L"), ("rhs", "R")):
            block = bins[bins["lane"].str.startswith(mask_name)]
            record.update(_side_block(block, chainage, side))
        info = meta.loc[chainage]
        record["nh_number"] = None if _missing(info["nh_number"]) else info["nh_number"]
        record["section_code"] = None if _missing(info["section_code"]) else info["section_code"]
        record["carriageway"] = None if _missing(info["carriageway"]) else info["carriageway"]
        record["lanes_present"] = ",".join(present)
        record["created_at"] = stamp
        records.append(record)
    return pd.DataFrame(records).reindex(columns=chainage_columns(surveyed))


def _lanes_from(names: list[str]) -> list[str]:
    lanes = []
    for name in names:
        head, _, _tail = name.partition("_")
        if len(head) > 1 and head[0] in "lr" and head[1].isdigit() and name.endswith("_start_chainage"):
            lane = head.upper()
            if lane not in lanes:
                lanes.append(lane)
    return lanes


def build_chainage(ctx):
    facts = ctx.frames.get("facts") or {}
    table = build_master_chainage(
        ctx.frames.get("canonical") or {},
        facts.get("d1") or {},
        ctx.upc,
        ctx.zone,
        ctx.phase,
        ctx.cycle,
    )
    ctx.frames.setdefault("tables", {})
    ctx.frames["tables"][CHAINAGE_TABLE] = table
    if table.empty:
        print("master_chainage: 0 rows")
    else:
        print(
            f"master_chainage: {len(table)} rows | "
            f"UPC chainage {table['upc_start_chainage'].iloc[0]:.0f}-{table['upc_end_chainage'].iloc[0]:.0f}"
        )
    return ctx
