"""Versioned output columns.

The Databricks workbook is the current column list. On EC2 the contract
lives in this module so a run does not need that workbook mounted.
"""

from __future__ import annotations


def output_columns(table: str) -> list[str]:
    raise NotImplementedError(f"column contract for {table} is ported with the first table builder")
