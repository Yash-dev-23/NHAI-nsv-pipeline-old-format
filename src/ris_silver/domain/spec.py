"""Output tables written for one UPC. Linear defects share one hierarchy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    table: str
    kind: str  # parent | ca | irc100 | 10m
    length_m: int | None


@dataclass(frozen=True)
class DefectSpec:
    name: str
    parent: Level
    children: tuple[Level, ...]


def linear_specs(parent_m: int, child_100m: int, child_10m: int) -> dict[str, DefectSpec]:
    """CA child length is the 100 m fallback. The survey interval from D2 replaces it at load time."""

    def child(table: str, kind: str, length: int) -> Level:
        return Level(table, kind, length)

    return {
        "roughness": DefectSpec(
            "roughness",
            Level("master_roughness", "parent", parent_m),
            (
                child("child_roughness_as_per_ca", "ca", child_100m),
                child("child_10m_roughness", "10m", child_10m),
                child("child_100m_roughness", "irc100", child_100m),
            ),
        ),
        "rutting": DefectSpec(
            "rutting",
            Level("master_rutting", "parent", parent_m),
            (
                child("child_rutting_as_per_ca", "ca", child_100m),
                child("child_10m_rutting", "10m", child_10m),
                child("child_100m_rutting", "irc100", child_100m),
            ),
        ),
        "ravelling": DefectSpec(
            "ravelling",
            Level("master_ravelling_ca", "parent", child_100m),
            (child("master_ravelling_irc", "irc100", child_100m),),
        ),
        "cracking": DefectSpec(
            "cracking",
            Level("master_cracking_ca", "parent", child_100m),
            (
                child("master_cracking_irc", "irc100", child_100m),
                child("child_10m_cracking", "10m", child_10m),
            ),
        ),
    }


POTHOLE_TABLE = "master_potholes"
CHAINAGE_TABLE = "master_chainage"


def output_tables(specs: dict[str, DefectSpec]) -> list[str]:
    names: list[str] = []
    for spec in specs.values():
        names.append(spec.parent.table)
        names.extend(level.table for level in spec.children)
    names.append(POTHOLE_TABLE)
    names.append(CHAINAGE_TABLE)
    return names
