"""Output columns for one published table.

The list is the Nov 18 notebook contract in ``domain.table_contract``. A run
does not need the Databricks workbook or the Excel query mounted.
"""

from __future__ import annotations

from ris_silver.domain.table_contract import columns


def output_columns(table: str) -> list[str]:
    return columns(table)
