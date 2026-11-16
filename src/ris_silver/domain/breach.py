"""Breach is value strictly above the threshold, for both CA and IRC."""

from __future__ import annotations


def breaches(value, threshold) -> bool:
    if value is None or threshold is None:
        return False
    return float(value) > float(threshold)


def irc_thresholds(irc: dict) -> dict[str, float]:
    return {
        "roughness": float(irc["roughness_mm_per_km"]),
        "rutting": float(irc["rutting_mm"]),
        "cracking": float(irc["cracking_percent"]),
        "ravelling": float(irc["ravelling_percent"]),
    }
