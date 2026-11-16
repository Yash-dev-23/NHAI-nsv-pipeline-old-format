"""Condition labels from the CA thresholds of this survey."""

from __future__ import annotations

import math


def _num(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def crack_condition(value, threshold):
    value = _num(value)
    if value is None:
        return None
    limit = float(threshold)
    fair, poor, very_poor = round(limit * 2), round(limit * 4), round(limit * 6)
    if value < limit:
        return f"Very Good (<{limit:.0f}%)"
    if value <= fair:
        return f"Good ({limit:.0f}-{fair}%)"
    if value <= poor:
        return f"Fair ({fair}-{poor}%)"
    if value <= very_poor:
        return f"Poor ({poor}-{very_poor}%)"
    return f"Very Poor (>{very_poor}%)"


def roughness_condition(iri_value, bi_value, threshold):
    iri = _num(iri_value)
    bi = _num(bi_value)
    probe = bi if bi is not None else (iri * 1000 if iri is not None else None)
    if probe is None:
        return None
    limit = float(threshold)
    fair_lower = round(limit * 0.8)
    if probe < fair_lower:
        return f"Good (<{fair_lower}mm/km)"
    if probe <= limit:
        return f"Fair ({fair_lower}-{limit:.0f}mm/km)"
    return f"Poor (>{limit:.0f}mm/km)"


def rutting_condition(value, threshold):
    value = _num(value)
    if value is None:
        return None
    limit = float(threshold)
    fair_lower = round(limit * 0.5)
    if value < fair_lower:
        return f"Good (<{fair_lower}mm)"
    if value <= limit:
        return f"Fair ({fair_lower}-{limit:.0f}mm)"
    return f"Poor (>{limit:.0f}mm)"


def ravelling_condition(value, threshold):
    value = _num(value)
    if value is None:
        return None
    limit = float(threshold)
    half = round(limit * 0.5)
    if value == 0:
        return "Very Good (0)"
    if value <= half:
        return f"Good (1-{half}%)"
    if value < limit:
        return f"Fair ({half}-{limit:.0f}%)"
    return f"Poor (>={limit:.0f}%)"
