"""Run manifest: tables, row counts, check results, stage timings."""

from __future__ import annotations


def build_report(ctx, checks: list[dict]) -> dict:
    return {
        "upc": ctx.upc,
        "phase": ctx.phase,
        "cycle": ctx.cycle,
        "zone": ctx.zone,
        "checks": checks,
    }
