"""Parquet and Excel reads. Callers pass a concrete path."""

from __future__ import annotations


def read_parquet(path: str):
    import pandas as pd

    return pd.read_parquet(path)


def read_excel(path: str, sheet: str | None = None, header: int = 0):
    import pandas as pd

    return pd.read_excel(path, sheet_name=sheet, header=header)
