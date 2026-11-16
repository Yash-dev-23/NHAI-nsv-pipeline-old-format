"""Find the NSV and backup folders of one UPC. Roots stay outside this module."""

from __future__ import annotations

from pathlib import Path


def find_latest_date_partition(base: Path) -> Path | None:
    """Latest year=/month=/day= directory under base. Names sort newest last."""
    if not base.is_dir():
        return None
    years = sorted((p for p in base.iterdir() if p.is_dir() and p.name.startswith("year=")), key=lambda p: p.name)
    for year in reversed(years):
        months = sorted((p for p in year.iterdir() if p.is_dir() and p.name.startswith("month=")), key=lambda p: p.name)
        for month in reversed(months):
            days = sorted((p for p in month.iterdir() if p.is_dir() and p.name.startswith("day=")), key=lambda p: p.name)
            if days:
                return days[-1]
    return None


def find_deliverable_parent(base: Path) -> Path:
    """Directory whose children are Deliverable=... folders. Searches one level deeper when needed."""
    if not base.is_dir():
        return base
    children = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name)
    if any(child.name.startswith("Deliverable=") for child in children):
        return base
    for child in children:
        found = find_deliverable_parent(child)
        if found != child:
            return found
        if any(grand.name.startswith("Deliverable=") for grand in child.iterdir() if grand.is_dir()):
            return child
    return base


def find_lane_parent(base: Path) -> Path | None:
    """Directory whose children are Lane=... folders."""
    if not base.is_dir():
        return None
    children = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name)
    if any(child.name.startswith("Lane=") for child in children):
        return base
    for child in children:
        found = find_lane_parent(child)
        if found:
            return found
    return None


def resolve_bronze(bronze_root: str, zone: str, phase: str, cycle: str, upc: str) -> dict[str, Path]:
    root = Path(bronze_root)
    nsv = root / "Source=NSV" / f"Zone={zone}" / f"Phase={phase}" / f"Cycle={cycle}" / f"UPC={upc}"
    nsv_date = find_latest_date_partition(nsv)
    deliverable = find_deliverable_parent(nsv_date or nsv)
    backup_root = root / "Source=NSV_Backup" / f"Zone={zone}" / f"Phase={phase}" / f"Cycle={cycle}" / f"UPC={upc}"
    backup_date = find_latest_date_partition(backup_root)
    if backup_date:
        backup = find_lane_parent(backup_date) or backup_date
    else:
        backup = backup_root
    return {
        "deliverable": deliverable,
        "d1": deliverable / "Deliverable=Deliverable - 1",
        "d2": deliverable / "Deliverable=Deliverable - 2",
        "d3": deliverable / "Deliverable=Deliverable - 3",
        "d4": deliverable / "Deliverable=Deliverable - 4",
        "backup": backup,
    }
