"""Read API for the notebook table contract.

Column lists live in ``table_contract_data``. This module is what builders and
the writer call: column names, types, and a frame aligned to that order.
"""

from __future__ import annotations

import pandas as pd

from ris_silver.domain.table_contract_data import (
    COLUMNS,
    EXCEL_SOURCE,
    ONE_ROW_CA_IRC_COLUMNS,
    PUBLISHED_TABLES,
    TEN_METRE_TABLES,
)

_LANE_FIELDS = (
    "start_chainage",
    "end_chainage",
    "start_lat",
    "start_long",
    "end_lat",
    "end_long",
)
_CHAINAGE_FRONT = (
    "upc",
    "upc_code",
    "zone",
    "phase",
    "cycle",
    "chainage_start",
    "chainage_end",
    "upc_start_chainage",
    "upc_end_chainage",
    "lanes_present",
    "nh_number",
    "section_code",
    "carriageway",
)
_CHAINAGE_SIDE = (
    "lhs_start_chainage",
    "lhs_start_lat",
    "lhs_start_long",
    "lhs_pavement_type",
    "lhs_end_chainage",
    "lhs_end_lat",
    "lhs_end_long",
    "lhs_lanes",
    "rhs_start_chainage",
    "rhs_start_lat",
    "rhs_start_long",
    "rhs_pavement_type",
    "rhs_end_chainage",
    "rhs_end_lat",
    "rhs_end_long",
    "rhs_lanes",
)


def published_tables() -> tuple[str, ...]:
    return PUBLISHED_TABLES


def columns(table: str) -> list[str]:
    return [name for name, _type in _fields(table)]


def types(table: str) -> dict[str, str]:
    return {name: type_name for name, type_name in _fields(table)}


def _fields(table: str) -> tuple[tuple[str, str], ...]:
    try:
        return COLUMNS[table]
    except KeyError as exc:
        known = ", ".join(PUBLISHED_TABLES)
        raise KeyError(f"no column contract for {table!r}. Known tables: {known}") from exc


def chainage_columns(lanes: list[str] | tuple[str, ...] | None = None) -> list[str]:
    """Excel chainage shape. L1, L2, R1, and R2 are always present.

    Any other lane on the survey is inserted in lane order, six columns each.
    With no extra lanes this is the 54-column Excel list.
    """
    present = {"L1", "L2", "R1", "R2"}
    for lane in lanes or ():
        present.add(str(lane))
    ordered = sorted(present, key=_lane_key)
    lane_cols = [f"{lane.lower()}_{field}" for lane in ordered for field in _LANE_FIELDS]
    return list(_CHAINAGE_FRONT) + list(_CHAINAGE_SIDE) + lane_cols + ["created_at"]


def has_contract(table: str) -> bool:
    return table in COLUMNS


def align_frame(frame: pd.DataFrame | None, table: str) -> pd.DataFrame:
    """Return ``frame`` with exactly the contract columns, in contract order.

    A column the builder did not fill is null. A column that is not in the
    contract is dropped, so the written file cannot grow a private schema.
    """
    names = columns(table)
    source = pd.DataFrame() if frame is None else frame
    aligned = source.reindex(columns=names)
    return aligned


def _lane_key(lane: str):
    token = str(lane)
    rest = token[1:]
    return (token[:1], int(rest) if rest.isdigit() else 99)


__all__ = [
    "EXCEL_SOURCE",
    "ONE_ROW_CA_IRC_COLUMNS",
    "PUBLISHED_TABLES",
    "TEN_METRE_TABLES",
    "align_frame",
    "has_contract",
    "chainage_columns",
    "columns",
    "published_tables",
    "types",
]
