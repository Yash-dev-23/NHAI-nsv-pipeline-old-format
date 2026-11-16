"""load_reference and load_facts. Both write into RunContext.frames."""

from __future__ import annotations

from pathlib import Path

from ris_silver.ingest.backup import load_raw_backup, standardize_backup
from ris_silver.ingest.deliverables import load_d1, load_d3
from ris_silver.ingest.potholes import load_d2_potholes, load_d4_potholes, resolve_potholes
from ris_silver.ingest.thresholds import load_thresholds
from ris_silver.ingest.tracker import load_tracker
from ris_silver.io.layout import resolve_bronze


def load_reference(ctx):
    layout = resolve_bronze(ctx.bronze_root, ctx.zone, ctx.phase, ctx.cycle, ctx.upc)
    ctx.frames["layout"] = {name: str(path) for name, path in layout.items()}
    ctx.frames["tracker"] = load_tracker(
        ctx.tracker_path, ctx.zone, ctx.phase, ctx.cycle, ctx.upc, layout["d2"]
    )
    ctx.frames["thresholds"] = load_thresholds(layout["d2"])
    ca = ctx.frames["thresholds"]["ca"]
    print(
        "reference: "
        f"CA bi={ca['roughness_bi']} crack={ca['cracking_pct']} "
        f"rut={ca['rutting_mm']} ravel={ca['ravelling']} "
        f"override={ctx.frames['tracker'].get('threshold_label_override')}"
    )
    return ctx


def load_facts(ctx):
    if "layout" not in ctx.frames or "thresholds" not in ctx.frames:
        raise RuntimeError("load_reference must run before load_facts")
    layout = {name: Path(path) for name, path in ctx.frames["layout"].items()}
    divisor = float(ctx.pipeline.get("cracking", {}).get("area_divisor_m2", 35.0))
    standardized = standardize_backup(load_raw_backup(layout["backup"]), ctx.frames["thresholds"]["ca"], divisor)
    d4 = load_d4_potholes(layout["d4"])
    d2, d2_name = load_d2_potholes(layout["d2"])
    tracker = ctx.frames.get("tracker") or {}
    potholes, source = resolve_potholes(
        d4,
        d2,
        standardized["cracking"],
        ctx.image_root,
        tracker.get("survey_end_date"),
        force_d2=bool(ctx.pipeline.get("force_d2_potholes", False)),
    )
    d3 = load_d3(layout["d3"])
    lanes = set()
    for frame in standardized.values():
        if frame is not None and not frame.empty and "Lane" in frame.columns:
            lanes.update(lane for lane in frame["Lane"].dropna().unique())
    ctx.frames["facts"] = {
        **standardized,
        "potholes": potholes,
        "pothole_source": source,
        "d2_pothole_file": d2_name,
        "d3": d3,
        "d1": load_d1(layout["d1"]),
        "lanes": sorted(lanes),
    }
    print(
        "facts: "
        f"lanes={sorted(lanes)} "
        f"roughness={len(standardized['roughness'])} "
        f"cracking={len(standardized['cracking'])} "
        f"rutting={len(standardized['rutting'])} "
        f"ravelling={len(standardized['ravelling'])} "
        f"potholes={len(potholes)} ({source}) "
        f"d3={list(d3)}"
    )
    return ctx
