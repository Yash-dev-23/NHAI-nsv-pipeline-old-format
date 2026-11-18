import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ris_silver.context import RunContext
from ris_silver.io.paths import silver_latest_partition_dir, silver_partition_dir
from ris_silver.io.writer import publish


class ConsolidatedPublishTests(unittest.TestCase):
    def _context(self, root: Path, *, cycle: str, value: int) -> RunContext:
        ctx = RunContext(
            zone="A", phase="2", cycle=cycle, upc="N-02001-19004-DL",
            config_dir=root, pipeline={}, irc={}, silver_root=str(root),
        )
        ctx.frames["tracker"] = {
            "survey_start_date": "2026-01-01",
            "survey_end_date": "2026-01-10",
        }
        ctx.frames["tables"] = {
            "child_100m_roughness": pd.DataFrame({"value": [value]})
        }
        return ctx

    def test_latest_is_flat_consolidated_and_cycle_upsert_preserves_other_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cycle_one = self._context(root, cycle="1", value=10)
            publish(cycle_one)

            cycle_two = self._context(root, cycle="2", value=20)
            publish(cycle_two)

            latest = silver_latest_partition_dir(cycle_two, "child_100m_roughness")
            self.assertEqual(latest, root / "latest")
            parquet_file = latest / "child_100m_roughness.parquet"
            csv_file = latest / "child_100m_roughness.csv"
            self.assertTrue(parquet_file.is_file())
            self.assertTrue(csv_file.is_file())

            stored = pd.read_parquet(parquet_file).sort_values("cycle")
            self.assertEqual(stored["cycle"].tolist(), ["1", "2"])
            self.assertEqual(stored["value"].tolist(), [10, 20])
            self.assertEqual(set(stored["upc_code"]), {"N-02001-19004-DL"})
            self.assertEqual(set(stored["zone"]), {"A"})
            self.assertEqual(set(stored["survey_start_date"]), {"2026-01-01"})
            self.assertEqual(set(stored["survey_end_date"]), {"2026-01-10"})

            cycle_one.frames["tables"] = {
                "child_100m_roughness": pd.DataFrame({"value": [11]})
            }
            publish(cycle_one)
            updated = pd.read_parquet(parquet_file).sort_values("cycle")
            self.assertEqual(updated["cycle"].tolist(), ["1", "2"])
            self.assertEqual(updated["value"].tolist(), [11, 20])

            per_upc = silver_partition_dir(cycle_two, "child_100m_roughness")
            self.assertTrue((per_upc / "child_100m_roughness.csv").is_file())
            self.assertTrue((per_upc / "child_100m_roughness.parquet").is_file())


if __name__ == "__main__":
    unittest.main()
