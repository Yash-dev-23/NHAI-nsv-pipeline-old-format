import csv
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ris_silver.context import RunContext
from ris_silver.io.batch_summary import append_batch_summary_row
from ris_silver.io.writer import publish


class BatchSummaryTests(unittest.TestCase):
    def test_append_batch_summary_row_creates_row_and_preserves_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = Path(tmpdir) / "logs" / "batch_summary.csv"

            append_batch_summary_row(
                summary,
                zone="B",
                phase="2",
                cycle="1",
                upc="N_07024_01001_GJ",
                status="PASS",
                table_count=12,
                output_path="silver_tables/zone=B/phase=2/cycle=1/N_07024_01001_GJ/run_date=2026-11-17",
                notes="survey processed",
            )

            append_batch_summary_row(
                summary,
                zone="B",
                phase="2",
                cycle="1",
                upc="N_07024_01002_GJ",
                status="WARN",
                table_count=8,
                output_path="silver_tables/zone=B/phase=2/cycle=1/N_07024_01002_GJ/run_date=2026-11-17",
                notes="review required",
            )

            with summary.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["upc"], "N_07024_01001_GJ")
            self.assertEqual(rows[0]["status"], "PASS")
            self.assertNotIn("issue_code", rows[0])
            self.assertEqual(rows[1]["status"], "WARN")
            self.assertEqual(rows[1]["notes"], "review required")

    def test_publish_keeps_historical_run_and_latest_alias(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = RunContext(
                zone="B",
                phase="2",
                cycle="1",
                upc="N_07024_01001_GJ",
                config_dir=Path(tmpdir),
                pipeline={},
                irc={},
                bronze_root="/tmp/bronze",
                silver_root=str(Path(tmpdir) / "silver"),
                tracker_path="/tmp/tracker.xlsx",
                image_root="/tmp/images",
                run_date="2026-11-17",
            )

            publish(ctx, {"master_roughness": pd.DataFrame({"id": [1, 2]})})

            run_dir = Path(tmpdir) / "silver" / "zone=B" / "phase=2" / "cycle=1" / "N-07024-01001-GJ" / "run_date=2026-11-17"
            latest_dir = Path(tmpdir) / "silver" / "zone=B" / "phase=2" / "cycle=1" / "N-07024-01001-GJ" / "latest"

            self.assertTrue((run_dir / "master_roughness" / "master_roughness.parquet").exists())
            self.assertTrue((latest_dir / "master_roughness" / "master_roughness.parquet").exists())


if __name__ == "__main__":
    unittest.main()
