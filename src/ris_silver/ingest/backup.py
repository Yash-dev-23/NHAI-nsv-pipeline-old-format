"""Lane-wise NSV backup frames, with the roughness and ravelling formulas applied."""

from __future__ import annotations

import pandas as pd

from ris_silver.domain.conditions import (
    crack_condition,
    ravelling_condition,
    roughness_condition,
    rutting_condition,
)
from ris_silver.domain.metrics import bi_from_iri, ravelling_percent
from ris_silver.ingest.files import load_backup_lane_parquets

_SUFFIX = {
    "cracking": "_Cracking.parquet",
    "roughness": "_Roughness_IRI.parquet",
    "rutting": "_Rutting.parquet",
    "ravelling": "_Raveling.parquet",
}


def load_raw_backup(backup_dir) -> dict[str, pd.DataFrame]:
    frames = {}
    for defect, suffix in _SUFFIX.items():
        frame, _files = load_backup_lane_parquets(backup_dir, suffix)
        frames[defect] = frame
    return frames


def _rename(frame: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    present = {old: new for old, new in mapping.items() if old in frame.columns}
    return frame.rename(columns=present)


def standardize_backup(raw: dict[str, pd.DataFrame], ca: dict, area_divisor: float = 35.0) -> dict[str, pd.DataFrame]:
    cracking = raw.get("cracking", pd.DataFrame())
    roughness = raw.get("roughness", pd.DataFrame())
    rutting = raw.get("rutting", pd.DataFrame())
    ravelling = raw.get("ravelling", pd.DataFrame())
    if not cracking.empty:
        cracking = _rename(cracking, {
            "LANE": "Lane",
            "Percent_Area": "Cracking",
            "cracking_image_name": "Image_Name",
            "cracking_image_url": "Image_URL",
            "Start_Latitude": "Start_Lat",
            "Start_Longitude": "Start_Lon",
            "End_Latitude": "End_Lat",
            "End_Longitude": "End_Lon",
            "survey_date_crack": "SurveyDate",
            "Area_Sum": "Area_sq_m",
        })
        if "Lane" not in cracking.columns and "Source_Lane_Folder" in cracking.columns:
            cracking["Lane"] = cracking["Source_Lane_Folder"]
        percent = pd.to_numeric(cracking["Cracking"], errors="coerce").fillna(0)
        cracking["Condition"] = percent.map(lambda value: crack_condition(value, ca["cracking_pct"]))
        cracking["Type_of_Defect"] = "Cracking"
    if not roughness.empty:
        roughness = _standardize_roughness(roughness, ca["roughness_bi"])
    if not rutting.empty:
        rutting = _rename(rutting, {
            "LANE": "Lane",
            "Rutting Average": "Rutting",
            "Start_Latitude": "Start_Lat",
            "Start_Longitude": "Start_Lon",
            "End_Latitude": "End_Lat",
            "End_Longitude": "End_Lon",
            "survey_date_rutting": "SurveyDate",
        })
        if "Lane" not in rutting.columns and "Source_Lane_Folder" in rutting.columns:
            rutting["Lane"] = rutting["Source_Lane_Folder"]
        rutting["Condition"] = pd.to_numeric(rutting["Rutting"], errors="coerce").map(
            lambda value: rutting_condition(value, ca["rutting_mm"])
        )
        rutting["Type_of_Defect"] = "Rutting"
    if not ravelling.empty:
        ravelling = _rename(ravelling, {
            "Raveling_Area_m2": "Ravelling_Area_sq_m",
            "Start_Latitude": "Start_Lat",
            "Start_Longitude": "Start_Lon",
            "End_Latitude": "End_Lat",
            "End_Longitude": "End_Lon",
            "survey_date_raveling": "SurveyDate",
        })
        area = pd.to_numeric(ravelling["Ravelling_Area_sq_m"], errors="coerce").fillna(0)
        percent = area.map(lambda value: ravelling_percent(value, area_divisor))
        ravelling["Ravelling"] = percent
        ravelling["Condition"] = percent.map(lambda value: ravelling_condition(value, ca["ravelling"]))
        ravelling["Type_of_Defect"] = "Ravelling"
    return {
        "cracking": cracking,
        "roughness": roughness,
        "rutting": rutting,
        "ravelling": ravelling,
    }


def _standardize_roughness(frame: pd.DataFrame, bi_threshold: float) -> pd.DataFrame:
    frame = _rename(frame, {
        "RoughnessIndex": "BI m/km",
        "LaneIri": "IRI",
        "Start_Latitude": "Start_Lat",
        "Start_Longitude": "Start_Lon",
        "End_Latitude": "End_Lat",
        "End_Longitude": "End_Lon",
        "ConditionOfRoadSurface": "Condition",
    })
    if "SurveyDate" not in frame.columns:
        frame["SurveyDate"] = pd.NaT
    if "IRI" not in frame.columns:
        frame["IRI"] = pd.NA
    if "BI m/km" not in frame.columns:
        frame["BI m/km"] = pd.NA
    if "LwpIri" in frame.columns and "RwpIri" in frame.columns:
        left = pd.to_numeric(frame["LwpIri"], errors="coerce")
        right = pd.to_numeric(frame["RwpIri"], errors="coerce")
        both = left.notna() & right.notna()
        derived_iri = (left + right) / 2.0
        frame["IRI_original"] = frame["IRI"]
        frame["BI_original"] = frame["BI m/km"]
        frame.loc[both, "IRI"] = derived_iri[both]
        frame.loc[both, "BI m/km"] = derived_iri[both].map(bi_from_iri)
    iri = pd.to_numeric(frame["IRI"], errors="coerce")
    bi = pd.to_numeric(frame["BI m/km"], errors="coerce")
    derived = [
        roughness_condition(i, b, bi_threshold)
        for i, b in zip(iri, bi)
    ]
    if "Condition" in frame.columns:
        frame["Condition"] = frame["Condition"].fillna(pd.Series(derived, index=frame.index))
    else:
        frame["Condition"] = derived
    frame["Type_of_Defect"] = "Roughness"
    frame["BI m/km"] = pd.to_numeric(frame["BI m/km"], errors="coerce")
    frame["IRI"] = pd.to_numeric(frame["IRI"], errors="coerce")
    missing_bi = frame["BI m/km"].isna()
    frame.loc[missing_bi, "BI m/km"] = frame.loc[missing_bi, "IRI"].map(
        lambda iri: bi_from_iri(iri) if pd.notna(iri) else None
    )
    return frame
