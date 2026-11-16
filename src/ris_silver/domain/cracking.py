"""Cracking formulas that do not depend on how D2 files are joined."""

from __future__ import annotations


def correction_factor(d2_area: float, parquet_area: float, cap: float = 1.0) -> float | None:
    """Scale a 10 m backup area down to the D2-capped area. Never scales up."""
    if parquet_area is None or parquet_area <= 0 or d2_area is None:
        return None
    return min(float(d2_area) / float(parquet_area), float(cap))


def cracking_percent(area_m2: float, divisor_m2: float = 35.0) -> float:
    return float(area_m2) / float(divisor_m2) * 100.0


LANE_AREA_10M = 35.0
LANE_AREA_100M = 350.0
LANE_AREA_1000M = 3500.0


def find_column(columns, *must: str, exclude: tuple[str, ...] = ()) -> str | None:
    """First column whose lower-case name contains every must-word and none of exclude."""
    for column in columns:
        folded = str(column).lower()
        if all(word in folded for word in must) and not any(word in folded for word in exclude):
            return column
    return None


def row_interval_m(frame, chain_col: str) -> str:
    """'1000m' is tested before '100m' because the text 1000m contains 100m."""
    tags = " ".join(str(column) for column in frame.columns).lower()
    if "1000m" in tags:
        return "1000m"
    if "100m" in tags:
        return "100m"
    end = find_column(frame.columns, "end", "chainage")
    if end is None:
        return "1000m"
    import pandas as pd

    length = (pd.to_numeric(frame[end], errors="coerce") - frame[chain_col]).dropna().median()
    return "100m" if length <= 200 else "1000m"


def irc_interval_m(frame, chain_col: str) -> str:
    """A crack column tagged 100m forces 100m. 1000m also contains the text 100m, same as the notebook."""
    for column in frame.columns:
        folded = str(column).lower()
        if "crack" in folded and "100m" in folded:
            return "100m"
    return row_interval_m(frame, chain_col)


def apply_cracking_correction(frame, sources: dict, crack_threshold: float):
    """Scale each 10 m area down to the D2 bin. Factor is min(D2 area / parquet area, 1).

    Finest source wins: D2 IRC at 100 m, else D2 CA at 100 m, else D2 CA at 1000 m.
    D2 crack cells are percents. Area = percent / 100 × (bin length × 3.5).
    """
    import numpy as np
    import pandas as pd

    from ris_silver.domain.conditions import crack_condition

    if sources.get("ca_frame") is None:
        raise ValueError("No D2 CA file with a start-chainage column")
    ca_interval = sources["ca_interval"]
    irc_frame = sources.get("irc_frame")
    irc_interval = sources.get("irc_interval")
    if irc_frame is not None and irc_interval == "100m":
        calib_src, calib_m, calib, chain_col = "IRC", 100, irc_frame, sources["irc_chain"]
    else:
        calib_src, calib_m = "CA", (100 if ca_interval == "100m" else 1000)
        calib, chain_col = sources["ca_frame"], sources["ca_chain"]

    corrected = frame.copy() if frame is not None else pd.DataFrame()
    report = {
        "ca_interval_m": 100 if ca_interval == "100m" else 1000,
        "irc_interval_m": None if not irc_interval else (100 if irc_interval == "100m" else 1000),
        "calib_source": calib_src,
        "calib_m": calib_m,
        "rows_changed": 0,
        "lanes": {},
    }
    if corrected.empty or "Lane" not in corrected.columns:
        report["checks"] = []
        return corrected, report

    calib = calib.copy()
    calib["_cbin"] = (calib[chain_col] // calib_m * calib_m).astype(int)
    lane_area = calib_m * 3.5
    lanes = sorted(corrected["Lane"].dropna().unique())
    chainage = corrected[["Start_Chainage", "End_Chainage"]].min(axis=1) if "End_Chainage" in corrected.columns else corrected["Start_Chainage"]
    changed = 0
    for lane in lanes:
        column = find_column(calib.columns, str(lane).lower(), "crack", exclude=("limit",))
        if column is None:
            report["lanes"][str(lane)] = "unchanged"
            continue
        mask = corrected["Lane"] == lane
        d2_area = (
            pd.to_numeric(calib[column], errors="coerce").fillna(0).groupby(calib["_cbin"]).mean() / 100.0 * lane_area
        )
        bins = (chainage[mask] // calib_m * calib_m).astype(int)
        area = pd.to_numeric(corrected.loc[mask, "Area_sq_m"], errors="coerce")
        parquet_total = area.groupby(bins).transform("sum")
        d2_value = bins.map(d2_area)
        factor = np.where(d2_value.notna() & (parquet_total > 0), np.minimum(d2_value / parquet_total, 1.0), 1.0)
        new_area = pd.Series(area.to_numpy(dtype=float) * factor, index=area.index)
        changed += int(((area - new_area).abs() > 0.001).sum())
        corrected.loc[area.index, "Area_sq_m"] = new_area
        corrected.loc[area.index, "Cracking"] = new_area / LANE_AREA_10M * 100.0
        report["lanes"][str(lane)] = {"d2_bins": int(d2_area.shape[0]), "rows": int(mask.sum())}
    if "Cracking" in corrected.columns:
        percent = pd.to_numeric(corrected["Cracking"], errors="coerce").fillna(0)
        corrected["Condition"] = percent.map(lambda value: crack_condition(value, crack_threshold))
    report["rows_changed"] = changed
    report["checks"] = _calibration_checks(corrected, lanes, sources)
    return corrected, report


def _calibration_checks(frame, lanes, sources) -> list[dict]:
    """Same bin comparison the notebook prints. It does not change the rows."""
    import pandas as pd

    checks = []
    chainage = frame[["Start_Chainage", "End_Chainage"]].min(axis=1) if "End_Chainage" in frame.columns else frame["Start_Chainage"]
    for level, lane_area in ((100, LANE_AREA_100M), (1000, LANE_AREA_1000M)):
        if level == 100:
            if sources.get("irc_frame") is not None and sources.get("irc_interval") == "100m":
                verify, chain_col, label = sources["irc_frame"], sources["irc_chain"], "IRC"
            elif sources.get("ca_interval") == "100m":
                verify, chain_col, label = sources["ca_frame"], sources["ca_chain"], "CA"
            else:
                continue
        else:
            verify, chain_col, label = sources["ca_frame"], sources["ca_chain"], "CA"
        bins = (verify[chain_col] // level * level).astype(int)
        for lane in lanes:
            column = find_column(verify.columns, str(lane).lower(), "crack", exclude=("limit",))
            if not column:
                continue
            d2_percent = pd.to_numeric(verify[column], errors="coerce").groupby(bins).mean()
            mask = frame["Lane"] == lane
            db_percent = frame.loc[mask, "Area_sq_m"].groupby((chainage[mask] // level * level).astype(int)).sum() / lane_area * 100.0
            diff = (db_percent - d2_percent).abs().dropna()
            checks.append({
                "level_m": level,
                "d2": label,
                "lane": str(lane),
                "bins": int(len(diff)),
                "mean_abs_diff_pct": None if diff.empty else round(float(diff.mean()), 4),
            })
    return checks


def severity(width_mm, medium_mm: float = 3.0, high_mm: float = 6.0) -> str | None:
    """Width under medium is the label None. Missing width stays missing."""
    if width_mm is None:
        return None
    width = float(width_mm)
    if width < medium_mm:
        return "None"
    if width < high_mm:
        return "Medium"
    return "High"
