"""Survey formulas that do not depend on file layout."""

from __future__ import annotations


def lane_iri(left_wheel, right_wheel) -> float:
    """IRC:SP:16 lane IRI is the mean of the two wheel paths."""
    return (float(left_wheel) + float(right_wheel)) / 2.0


def bi_from_iri(iri) -> float:
    """Roughness BI (mm/km) = 630 × IRI^1.12."""
    return 630.0 * (float(iri) ** 1.12)


def ravelling_percent(area_m2, divisor_m2: float = 35.0) -> float:
    return float(area_m2) * 100.0 / float(divisor_m2)
