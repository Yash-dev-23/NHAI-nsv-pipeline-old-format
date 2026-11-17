from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

SUMMARY_COLUMNS = [
    "run_timestamp",
    "batch_id",
    "status",
    "zone",
    "phase",
    "cycle",
    "upc",
    "table_count",
    "record_count",
    "output_path",
    "notes",
]


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_summary_file(path: str | Path) -> Path:
    summary_path = Path(path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    if not summary_path.exists():
        with summary_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=SUMMARY_COLUMNS)
            writer.writeheader()
    return summary_path


def append_batch_summary_row(
    summary_path: str | Path,
    *,
    zone: str,
    phase: str,
    cycle: str,
    upc: str,
    status: str = "PASS",
    table_count: int = 0,
    record_count: int = 0,
    output_path: str = "",
    notes: str = "",
    batch_id: str | None = None,
    run_timestamp: str | None = None,
) -> dict[str, str | int]:
    summary_file = ensure_summary_file(summary_path)
    row = {
        "run_timestamp": run_timestamp or _timestamp_now(),
        "batch_id": batch_id or f"batch-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "status": status,
        "zone": zone,
        "phase": phase,
        "cycle": cycle,
        "upc": upc,
        "table_count": int(table_count),
        "record_count": int(record_count),
        "output_path": output_path,
        "notes": notes,
    }
    with summary_file.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SUMMARY_COLUMNS)
        writer.writerow(row)
    return row


def discover_upcs(root: str | Path, upc_filter: str | None = None) -> list[str]:
    root_path = Path(root)
    if not root_path.exists():
        return []
    found: set[str] = set()
    for directory in sorted(root_path.rglob("UPC=*")):
        name = directory.name
        if name.startswith("UPC="):
            upc = name.split("=", 1)[1]
            if upc_filter and upc_filter not in upc:
                continue
            found.add(upc)
    return sorted(found)


def append_batch_summary_for_root(
    root: str | Path,
    summary_path: str | Path,
    *,
    zone: str,
    phase: str,
    cycle: str,
    upc_filter: str | None = None,
    status: str = "QUEUED",
    notes: str = "batch queued",
) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for upc in discover_upcs(root, upc_filter):
        output_path = f"silver_tables/zone={zone}/phase={phase}/cycle={cycle}/{upc}/run_date={datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        rows.append(
            append_batch_summary_row(
                summary_path,
                zone=zone,
                phase=phase,
                cycle=cycle,
                upc=upc,
                status=status,
                table_count=0,
                record_count=0,
                output_path=output_path,
                notes=notes,
            )
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append a batch row to the project summary CSV.")
    parser.add_argument("--root", default="bronze", help="Bronze root to scan for UPC folders")
    parser.add_argument("--summary", default="logs/batch_summary.csv", help="CSV file to append rows to")
    parser.add_argument("--zone", default="B")
    parser.add_argument("--phase", default="2")
    parser.add_argument("--cycle", default="1")
    parser.add_argument("--upc", default="", help="Optional UPC filter")
    parser.add_argument("--status", default="QUEUED")
    parser.add_argument("--notes", default="batch queued")
    args = parser.parse_args(argv)

    rows = append_batch_summary_for_root(
        args.root,
        args.summary,
        zone=args.zone,
        phase=args.phase,
        cycle=args.cycle,
        upc_filter=args.upc or None,
        status=args.status,
        notes=args.notes,
    )
    print(f"Appended {len(rows)} rows to {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
