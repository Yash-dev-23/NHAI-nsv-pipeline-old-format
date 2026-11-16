"""Lane text from the survey, and the side used by the parent row."""

from __future__ import annotations

import re

_SPLIT = re.compile(r"[\s\-_\.]+")


def normalize_lane(value) -> str | None:
    """'R-1' / 'Lane L2' / 'L.3' -> 'R1' / 'L2' / 'L3'."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    lane = _SPLIT.sub("", text.upper().replace("LANE", ""))
    return lane or None


def side_of_lane(value) -> str | None:
    """L lanes are LHS. R lanes are RHS."""
    lane = normalize_lane(value)
    if lane is None:
        return None
    if lane.startswith("L"):
        return "LHS"
    if lane.startswith("R"):
        return "RHS"
    return None


def direction_of_lane(value) -> str | None:
    """Numbered L lanes travel Increasing. Numbered R lanes travel Decreasing."""
    lane = normalize_lane(value)
    if lane is None:
        return None
    if re.fullmatch(r"L\d+", lane):
        return "Increasing"
    if re.fullmatch(r"R\d+", lane):
        return "Decreasing"
    return None


def normalize_direction(value) -> str | None:
    """D1 text 'Inc' / 'Dec' becomes Increasing / Decreasing. Other text is kept."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    if text.lower().startswith("inc"):
        return "Increasing"
    if text.lower().startswith("dec"):
        return "Decreasing"
    return text
