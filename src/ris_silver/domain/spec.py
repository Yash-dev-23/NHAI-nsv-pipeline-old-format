"""Output tables written for one UPC. Names follow the notebook TABLE_SPEC."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    table: str
    kind: str  # parent | ca | 10m
    length_m: int | None


@dataclass(frozen=True)
class DefectSpec:
    name: str
    parent: Level | None
    children: tuple[Level, ...]
    ca_interval_m: int | None = None


def linear_specs(parent_m: int, child_100m: int, child_10m: int) -> dict[str, DefectSpec]:
    """Roughness and rutting have an LHS/RHS parent. Cracking and ravelling do not.

    The CA interval is the survey D2 interval, except ravelling, which is fixed at 100 m.
    """

    def child(table: str, kind: str, length: int | None) -> Level:
        return Level(table, kind, length)

    return {
        "roughness": DefectSpec(
            "roughness",
            Level("master_roughness_parent", "parent", parent_m),
            (
                child("master_roughness_child_10m", "10m", child_10m),
                child("master_roughness_as_per_ca", "ca", None),
            ),
        ),
        "rutting": DefectSpec(
            "rutting",
            Level("master_rutting_parent", "parent", parent_m),
            (
                child("master_rutting_child_10m", "10m", child_10m),
                child("master_rutting_as_per_ca", "ca", None),
            ),
        ),
        "cracking": DefectSpec(
            "cracking",
            None,
            (
                child("master_cracking_10m", "10m", child_10m),
                child("master_cracking_as_per_ca", "ca", None),
            ),
        ),
        "ravelling": DefectSpec(
            "ravelling",
            None,
            (
                child("master_ravelling_10m", "10m", child_10m),
                child("master_ravelling", "ca", child_100m),
            ),
            ca_interval_m=child_100m,
        ),
    }


POTHOLE_TABLE = "master_pothole"
CHAINAGE_TABLE = "master_chainage"


def top_table(spec: DefectSpec) -> str:
    """Table that receives the top-level display ids."""
    if spec.parent is not None:
        return spec.parent.table
    for level in spec.children:
        if level.kind == "ca":
            return level.table
    raise ValueError(f"{spec.name} has no top table")


def output_tables(specs: dict[str, DefectSpec]) -> list[str]:
    names: list[str] = []
    for spec in specs.values():
        if spec.parent is not None:
            names.append(spec.parent.table)
        names.extend(level.table for level in spec.children)
    names.append(POTHOLE_TABLE)
    names.append(CHAINAGE_TABLE)
    return names
