"""Pick a source column whose name contains every keyword."""

from __future__ import annotations


def pick(columns, *keywords) -> str | None:
    for column in columns:
        folded = str(column).lower().replace("\n", " ")
        if all(keyword.lower() in folded for keyword in keywords):
            return column
    return None
