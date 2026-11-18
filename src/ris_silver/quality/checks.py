"""Read the published partition back and compare it with the frames that were built.

V1 counts, V2 side parents, V3 CA children, V5 10 m pairs, V6 potholes,
V7 links, V8 display ids, V9 chainage. IRC 100 m tables are not published.
WARN does not stop the run. FAIL does.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from ris_silver.domain.hierarchy import rollup_lanes
from ris_silver.domain.lanes import normalize_lane
from ris_silver.domain.spec import POTHOLE_TABLE, CHAINAGE_TABLE, linear_specs, top_table
from ris_silver.domain.table_contract import align_frame
from ris_silver.io.paths import silver_partition_dir, silver_parquet_path
from ris_silver.io.writer import _write_table_pair
from ris_silver.quality.report import build_report

CHECKS = (
    "V1 every table is written and the stored row count matches the built frame",
    "V2 one parent row per side per bin, value is the lane average, breach if any lane breaches",
    "V3 CA child uses the survey CA interval and the CA breach rule",
    "V5 10 m child, one As per CA row and one As per IRC row per piece, ids unique",
    "V6 one row per pothole and every display id is unique",
    "V7 every child parent_id exists, and the side follows the lane",
    "V8 breach rows have a display id, clean rows do not, and a child id extends its parent id",
    "V9 master_chainage has every lane, and a side's chainage runs forward",
)

_LINEAR = ("roughness", "rutting", "ravelling", "cracking")


class ValidationFailed(Exception):
    def __init__(self, results: list[dict]):
        self.results = results
        fails = [row for row in results if row["status"] == "FAIL"]
        lines = [
            f"{row['section']} | {row['check']} | {row['scope']}: {row['detail']}"
            for row in fails
        ]
        super().__init__(f"{len(fails)} validation checks failed\n" + "\n".join(lines))


def _rec(rows, section, check, scope, checked, failed, detail="", level="FAIL"):
    checked = int(checked)
    failed = int(failed)
    if checked == 0:
        status = "SKIP"
    elif failed == 0:
        status = "PASS"
    else:
        status = level
    rows.append({
        "section": section,
        "check": check,
        "scope": scope,
        "checked": checked,
        "failed": failed,
        "status": status,
        "detail": str(detail)[:500],
    })


def _num(values):
    return pd.to_numeric(pd.Series(values), errors="coerce").astype("float64").reset_index(drop=True)


def _close(left, right) -> np.ndarray:
    actual = _num(left).to_numpy()
    if np.ndim(right) == 0 or not hasattr(right, "__len__"):
        expected = np.full(len(actual), float(right))
    else:
        expected = _num(right).to_numpy()
    return np.isclose(actual, expected, rtol=1e-6, atol=1e-6, equal_nan=True)


def _ready(frame, *columns) -> bool:
    return frame is not None and not frame.empty and all(column in frame.columns for column in columns)


def _lane_key(lane: str):
    rest = lane[1:]
    return (lane[0], int(rest) if rest.isdigit() else 99)


def _read_published(ctx, names: list[str]) -> dict[str, pd.DataFrame]:
    frames = {}
    for name in names:
        path = silver_parquet_path(ctx, name)
        if path is not None and path.is_file():
            frames[name] = pd.read_parquet(path)
        else:
            frames[name] = pd.DataFrame()
    return frames


def _interval_checks(rows, section, table, frame, interval):
    if not _ready(frame, "start_chainage", "end_chainage", "reporting_interval_m", "lane"):
        _rec(rows, section, f"reporting_interval_m = {interval}", table, 0, 0)
        _rec(rows, section, f"row length <= {interval} m", table, 0, 0)
        _rec(rows, section, "one row per lane per interval bin", table, 0, 0)
        return
    length = (frame["end_chainage"] - frame["start_chainage"]).abs()
    _rec(rows, section, f"reporting_interval_m = {interval}", table, len(frame), int((_num(frame["reporting_interval_m"]) != interval).sum()))
    _rec(
        rows, section, f"row length <= {interval} m", table, len(frame), int((length > interval + 1e-6).sum()),
        f"max length {length.max():.0f} m",
    )
    bins = frame.assign(_b=frame["start_chainage"] // interval)
    _rec(rows, section, "one row per lane per interval bin", table, len(frame), int(bins.duplicated(["lane", "_b"]).sum()))


def _parent_checks(rows, defect, table, frame, lanes, length, threshold):
    if not _ready(frame, "side", "start_chainage", "end_chainage", "metric_value", "breach_flag", "threshold_value", "total_children"):
        for check in (
            f"one row per side per {length}m",
            "every side-bin of the lanes has a parent and vice versa",
            "value = average of the side lanes",
            "breach = any lane breaches (CA)",
            "total_children = number of lanes",
            f"CA threshold = {threshold}",
        ):
            _rec(rows, "V2 Parent", check, table, 0, 0)
        return
    parent = frame.copy()
    parent["_b"] = (np.minimum(parent["start_chainage"], parent["end_chainage"]) // length * length).astype("int64")
    _rec(rows, "V2 Parent", f"one row per side per {length}m", table, len(parent), int(parent.duplicated(["side", "_b"]).sum()))
    if lanes is None or lanes.empty:
        expected = pd.DataFrame(columns=["side", "_b", "v", "x", "n"])
    else:
        work = lanes.copy()
        work["_b"] = work["bin"].astype("int64")
        work["v"] = pd.to_numeric(work["metric_value"], errors="coerce")
        work["x"] = pd.to_numeric(work["ca_breach"], errors="coerce").fillna(0)
        expected = work.groupby(["side", "_b"], as_index=False).agg(v=("v", "mean"), x=("x", "max"), n=("lane", "size"))
    merged = parent.merge(expected, left_on=["side", "_b"], right_on=["side", "_b"], how="outer", indicator=True)
    _rec(rows, "V2 Parent", "every side-bin of the lanes has a parent and vice versa", table, len(merged), int((merged["_merge"] != "both").sum()))
    both = merged[merged["_merge"] == "both"].reset_index(drop=True)
    _rec(rows, "V2 Parent", "value = average of the side lanes", table, len(both), int((~_close(both["metric_value"], both["v"])).sum()) if len(both) else 0)
    _rec(rows, "V2 Parent", "breach = any lane breaches (CA)", table, len(both), int((_num(both["breach_flag"]) != _num(both["x"])).sum()) if len(both) else 0)
    _rec(rows, "V2 Parent", "total_children = number of lanes", table, len(both), int((_num(both["total_children"]) != _num(both["n"])).sum()) if len(both) else 0)
    _rec(rows, "V2 Parent", f"CA threshold = {threshold}", table, len(parent), int((~_close(parent["threshold_value"], threshold)).sum()))


def _ca_child(rows, defect, table, frame, threshold, interval, source):
    _rec(rows, "V3 CA child", f"CA threshold = {threshold}", table, len(frame) if _ready(frame, "threshold_value") else 0,
         int((~_close(frame["threshold_value"], threshold)).sum()) if _ready(frame, "threshold_value") else 0)
    if not _ready(frame, "metric_value", "breach_flag"):
        _rec(rows, "V3 CA child", "CA breach rule (metric vs CA threshold)", table, 0, 0)
    else:
        metric = _num(frame["metric_value"])
        expected = (metric > threshold).astype(int) if defect == "cracking" else (metric >= threshold).astype(int)
        _rec(rows, "V3 CA child", "CA breach rule (metric vs CA threshold)", table, len(frame), int((_num(frame["breach_flag"]) != expected).sum()))
    _interval_checks(rows, "V3 CA child", table, frame, interval)
    _rec(rows, "V3 CA child", f"interval source: {source}", table, 1, 0, f"{interval} m")


def _ten_metre(rows, table, frame, source, threshold):
    if source is None or source.empty or "start_chainage" not in source.columns:
        lane_rows = pd.DataFrame(columns=["lane", "start_chainage", "s_ca", "metric_value"])
    else:
        lane_rows = source.dropna(subset=["start_chainage"])[["lane", "start_chainage", "ca_breach", "metric_value"]].rename(columns={"ca_breach": "s_ca"}).copy()
        lane_rows["start_chainage"] = pd.to_numeric(lane_rows["start_chainage"], errors="coerce").astype("float64")
    if not _ready(frame, "lane", "start_chainage", "metric_value", "breach_flag", "threshold_name", "threshold_value"):
        for check in (
            "only As per CA / As per IRC rows",
            "one As per CA row per lane-wise 10m row",
            "one As per IRC row per lane-wise 10m row",
            "CA breach_flag = lane-wise CA row",
            f"IRC breach rule (metric > {threshold})",
            f"IRC threshold = {threshold}",
            "id unique",
        ):
            _rec(rows, "V5 10m", check, table, 0, 0)
        return
    child = frame.copy()
    child["start_chainage"] = pd.to_numeric(child["start_chainage"], errors="coerce").astype("float64")
    names = child["threshold_name"].isin(["As per CA", "As per IRC"])
    ca_rows = child[child["threshold_name"] == "As per CA"]
    irc_rows = child[child["threshold_name"] == "As per IRC"]
    _rec(rows, "V5 10m", "only As per CA / As per IRC rows", table, len(child), int((~names).sum()))
    _rec(
        rows, "V5 10m", "one As per CA row per lane-wise 10m row", table, len(lane_rows),
        abs(len(ca_rows) - len(lane_rows)), f"{len(ca_rows)} vs {len(lane_rows)}",
    )
    _rec(
        rows, "V5 10m", "one As per IRC row per lane-wise 10m row", table, len(lane_rows),
        abs(len(irc_rows) - len(lane_rows)), f"{len(irc_rows)} vs {len(lane_rows)}",
    )
    joined = ca_rows.merge(lane_rows, on=["lane", "start_chainage"], how="left")
    _rec(
        rows, "V5 10m", "CA breach_flag = lane-wise CA row", table, len(joined),
        int((_num(joined["breach_flag"]) != _num(joined["s_ca"])).sum()) if len(joined) else 0,
    )
    irc_expected = (_num(irc_rows["metric_value"]) > threshold).astype(int)
    _rec(
        rows, "V5 10m", f"IRC breach rule (metric > {threshold})", table, len(irc_rows),
        int((_num(irc_rows["breach_flag"]) != irc_expected).sum()) if len(irc_rows) else 0,
    )
    _rec(rows, "V5 10m", f"IRC threshold = {threshold}", table, len(irc_rows), int((~_close(irc_rows["threshold_value"], threshold)).sum()) if len(irc_rows) else 0)
    if "id" not in child.columns:
        _rec(rows, "V5 10m", "id unique", table, 0, 0)
    else:
        _rec(rows, "V5 10m", "id unique", table, len(child), int(child["id"].duplicated().sum()))


def _links_and_ids(rows, parent_name, parent, children: list[tuple[str, pd.DataFrame]], link_on: str = "parent_id"):
    if not _ready(parent, link_on):
        parent_ids = set()
        parent_display = {}
    else:
        parent_ids = set(parent[link_on].dropna())
        parent_display = parent.dropna(subset=[link_on]).drop_duplicates(link_on).set_index(link_on)["display_defect_id"].to_dict()
    if link_on == "id":
        if _ready(parent, "parent_id"):
            _rec(rows, "V7 Links", "top table (no parent) has parent_id NULL", parent_name, len(parent), int(parent["parent_id"].notna().sum()))
        else:
            _rec(rows, "V7 Links", "top table (no parent) has parent_id NULL", parent_name, 0, 0)
    for name, frame in [(parent_name, parent), *children]:
        if not _ready(frame, "breach_flag", "display_defect_id"):
            for check in (
                "breach rows have a display_defect_id",
                "non-breach rows have no display_defect_id",
                "display_defect_id unique in table",
            ):
                _rec(rows, "V8 IDs", check, name, 0, 0)
            if name != parent_name:
                _rec(rows, "V7 Links", "child parent_id exists in its LHS/RHS parent", name, 0, 0)
                _rec(rows, "V7 Links", "side follows the lane (L -> LHS, R -> RHS)", name, 0, 0)
                _rec(rows, "V8 IDs", "child ID = breaching parent ID + /nnnn", name, 0, 0)
            continue
        if name != parent_name and _ready(frame, "parent_id", "lane", "side"):
            missing = frame[~frame["parent_id"].isin(parent_ids)]
            _rec(rows, "V7 Links", "child parent_id exists in its LHS/RHS parent", name, len(frame), len(missing))
            upper = frame["lane"].astype(str).str.upper()
            expected = np.where(upper.str.startswith("L"), "LHS", np.where(upper.str.startswith("R"), "RHS", None))
            _rec(rows, "V7 Links", "side follows the lane (L -> LHS, R -> RHS)", name, len(frame), int((frame["side"].to_numpy() != expected).sum()))
        breach = pd.to_numeric(frame["breach_flag"], errors="coerce") == 1
        _rec(rows, "V8 IDs", "breach rows have a display_defect_id", name, int(breach.sum()), int((breach & frame["display_defect_id"].isna()).sum()))
        _rec(rows, "V8 IDs", "non-breach rows have no display_defect_id", name, int((~breach).sum()), int((~breach & frame["display_defect_id"].notna()).sum()))
        identifiers = frame["display_defect_id"].dropna()
        _rec(rows, "V8 IDs", "display_defect_id unique in table", name, len(identifiers), int(identifiers.duplicated().sum()))
        if name != parent_name and "parent_id" in frame.columns:
            parent_of = frame["parent_id"].map(parent_display)
            linked = breach & parent_of.notna()
            matched = sum(
                str(child).startswith(str(parent_id) + "/")
                for child, parent_id in zip(frame.loc[linked, "display_defect_id"], parent_of[linked])
            )
            _rec(rows, "V8 IDs", "child ID = breaching parent ID + /nnnn", name, int(linked.sum()), int(linked.sum() - matched))


def _chainage_checks(rows, frame, canonical):
    lanes = []
    for defect in _LINEAR:
        source = (canonical or {}).get(defect)
        if source is None or source.empty or "lane" not in source.columns:
            continue
        for value in source["lane"]:
            lane = normalize_lane(value)
            if lane:
                lanes.append(lane)
    present = sorted(set(lanes), key=_lane_key)
    columns = set() if frame is None else set(frame.columns)
    missing = [lane for lane in present if f"{lane.lower()}_start_lat" not in columns]
    _rec(rows, "V9 Chainage", "a lat/long column set for every lane", CHAINAGE_TABLE, len(present), len(missing), f"lanes {present}; missing {missing}")
    if not _ready(frame, "chainage_start"):
        _rec(rows, "V9 Chainage", "one row per 10m chainage", CHAINAGE_TABLE, 0, 0)
    else:
        _rec(rows, "V9 Chainage", "one row per 10m chainage", CHAINAGE_TABLE, len(frame), int(frame["chainage_start"].duplicated().sum()))
    for side in ("lhs", "rhs"):
        if frame is None or f"{side}_lanes" not in columns:
            _rec(rows, "V9 Chainage", f"{side.upper()} start/end lat-long filled where the side has lanes", CHAINAGE_TABLE, 0, 0, level="WARN")
            _rec(rows, "V9 Chainage", f"{side.upper()} start <= end chainage", CHAINAGE_TABLE, 0, 0)
            continue
        has = frame[f"{side}_lanes"].notna()
        missing_lat = has & (frame[f"{side}_start_lat"].isna() | frame[f"{side}_end_lat"].isna())
        _rec(
            rows, "V9 Chainage", f"{side.upper()} start/end lat-long filled where the side has lanes", CHAINAGE_TABLE,
            int(has.sum()), int(missing_lat.sum()), level="WARN",
        )
        subset = frame[has]
        failed = int((subset[f"{side}_start_chainage"] > subset[f"{side}_end_chainage"]).sum()) if len(subset) else 0
        _rec(rows, "V9 Chainage", f"{side.upper()} start <= end chainage", CHAINAGE_TABLE, len(subset), failed)


def run_checks(ctx, tables: dict | None = None, published: dict | None = None) -> list[dict]:
    """Compare published tables with the built frames. Pass `published` to check frames already in memory."""
    built = tables if tables is not None else (ctx.frames.get("tables") or {})
    stored = published if published is not None else _read_published(ctx, list(built))
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
    canonical = ctx.frames.get("canonical") or {}
    rows: list[dict] = []
    for name in list(built):
        stored_count = 0 if stored.get(name) is None else len(stored[name])
        built_count = 0 if built.get(name) is None else len(built[name])
        _rec(rows, "V1 Tables", "table written with rows", name, 1, int(stored_count == 0), f"{stored_count} rows")
        _rec(rows, "V1 Tables", "stored rows = built rows", name, built_count, abs(stored_count - built_count), f"stored {stored_count} / built {built_count}")
    for defect in _LINEAR:
        spec = specs[defect]
        interval = int(spec.ca_interval_m or ca_interval)
        children = []
        for level in spec.children:
            frame = stored.get(level.table, pd.DataFrame())
            children.append((level.table, frame))
            if level.kind == "ca":
                source = "fixed in TABLE_SPEC" if spec.ca_interval_m is not None else (
                    "D2 CA" if correction.get("ca_interval_m") else "default 100m"
                )
                _ca_child(rows, defect, level.table, frame, ca[defect], interval, source)
            elif level.kind == "10m":
                _ten_metre(rows, level.table, frame, canonical.get(defect), irc[defect])
        if spec.parent is not None:
            parent = stored.get(spec.parent.table, pd.DataFrame())
            lanes_parent = rollup_lanes(canonical.get(defect), defect, int(spec.parent.length_m), ca[defect])
            _parent_checks(rows, defect, spec.parent.table, parent, lanes_parent, int(spec.parent.length_m), ca[defect])
            _links_and_ids(rows, spec.parent.table, parent, children)
        else:
            top_name = top_table(spec)
            top = stored.get(top_name, pd.DataFrame())
            linked = [(name, frame) for name, frame in children if name != top_name]
            _links_and_ids(rows, top_name, top, linked, link_on="id")
    potholes = stored.get(POTHOLE_TABLE, pd.DataFrame())
    source = (ctx.frames.get("facts") or {}).get("potholes")
    source_count = 0 if source is None else len(source)
    _rec(rows, "V6 Potholes", "one row per pothole (defect records)", POTHOLE_TABLE, source_count, abs(len(potholes) - source_count), f"{len(potholes)} vs {source_count}")
    if not _ready(potholes, "display_defect_id"):
        _rec(rows, "V6 Potholes", "every pothole has a unique display_defect_id", POTHOLE_TABLE, 0, 0)
    else:
        identifiers = potholes["display_defect_id"]
        _rec(
            rows, "V6 Potholes", "every pothole has a unique display_defect_id", POTHOLE_TABLE, len(potholes),
            int(identifiers.isna().sum() + identifiers.dropna().duplicated().sum()),
        )
    _chainage_checks(rows, stored.get(CHAINAGE_TABLE), canonical)
    return rows


def validate(ctx):
    """Read the partition just written. FAIL stops the run. The result rows are stored beside the tables."""
    results = run_checks(ctx)
    ctx.frames["validation"] = results
    ctx.frames["report"] = build_report(ctx, results)
    directory = silver_partition_dir(ctx, "dlm_validation_results")
    if directory is not None:
        report = pd.DataFrame(results)
        report["upc_code"] = ctx.upc
        report["zone"] = ctx.zone
        report["phase"] = str(ctx.phase)
        report["cycle"] = str(ctx.cycle)
        report["validation_ts"] = pd.Timestamp.now()
        report = align_frame(report, "dlm_validation_results")
        _write_table_pair(directory, "dlm_validation_results", report)
    counts = Counter(row["status"] for row in results)
    print("validate: " + ", ".join(f"{status}={counts[status]}" for status in ("PASS", "WARN", "FAIL", "SKIP") if counts[status]))
    if counts["FAIL"]:
        raise ValidationFailed(results)
    return results
