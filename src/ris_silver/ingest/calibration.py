"""D2 crack sheets used to cap the backup 10 m area. First matching file that has a start chainage."""

from __future__ import annotations

from pathlib import Path

from ris_silver.domain.cracking import apply_cracking_correction, find_column, irc_interval_m, row_interval_m
from ris_silver.io.reader import read_parquet


def _load_sheet(folder: Path, token: str):
    if not folder.is_dir():
        return None
    names = sorted(path.name for path in folder.iterdir() if path.name.endswith(".parquet") and token in path.name)
    for name in names:
        frame = read_parquet(str(folder / name))
        chain = find_column(frame.columns, "start", "chainage")
        if not chain:
            continue
        frame = frame.copy()
        import pandas as pd

        frame[chain] = pd.to_numeric(frame[chain], errors="coerce")
        frame = frame.dropna(subset=[chain])
        return frame, chain, name
    return None


def load_crack_sources(d2_dir) -> dict:
    folder = Path(d2_dir) if d2_dir else Path()
    ca = _load_sheet(folder, "CA")
    irc = _load_sheet(folder, "IRC")
    sources = {
        "ca_frame": None,
        "ca_chain": None,
        "ca_file": None,
        "ca_interval": None,
        "irc_frame": None,
        "irc_chain": None,
        "irc_file": None,
        "irc_interval": None,
    }
    if ca:
        frame, chain, name = ca
        sources.update(ca_frame=frame, ca_chain=chain, ca_file=name, ca_interval=row_interval_m(frame, chain))
    if irc:
        frame, chain, name = irc
        sources.update(
            irc_frame=frame,
            irc_chain=chain,
            irc_file=name,
            irc_interval=irc_interval_m(frame, chain),
        )
    return sources


def run_correction(ctx):
    """Replace facts['cracking'] with the D2-calibrated areas and percents."""
    layout = ctx.frames.get("layout") or {}
    sources = load_crack_sources(layout.get("d2"))
    threshold = float(ctx.frames["thresholds"]["ca"]["cracking_pct"])
    corrected, report = apply_cracking_correction(ctx.frames["facts"]["cracking"], sources, threshold)
    ctx.frames["facts"]["cracking"] = corrected
    ctx.frames["correction"] = report
    print(
        "correction: "
        f"D2 {report['calib_source']} @{report['calib_m']}m "
        f"ca_interval={report['ca_interval_m']}m "
        f"rows_changed={report['rows_changed']}"
    )
    return ctx
