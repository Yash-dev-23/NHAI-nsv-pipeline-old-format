import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PATH_HELPER = REPO_ROOT / "scripts" / "runtime_paths.sh"


class RuntimeS3PathTests(unittest.TestCase):
    def test_two_upcs_use_their_own_runtime_partition_paths(self):
        def resolve(upc: str) -> dict[str, str]:
            script = r'''source "$1"
OUTPUT_ROOT="$2"
SILVER_S3_ROOT="$2"
ZONE="$3"
PHASE="$4"
CYCLE="$5"
UPC="$6"
LOG_NAME="${UPC}_run.log"
resolve_runtime_s3_paths
printf '%s\n' "$SILVER_UPC_ROOT" "$SILVER_DATA_OUTPUT_DIR" "$UPC_LOG_S3" "$RUN_LOG_S3"
'''
            result = subprocess.run(
                [
                    "bash", "-c", script, "runtime-path-test",
                    str(PATH_HELPER), "s3://dhms-new-stgae/DHMS/NSV/Silver",
                    "A", "1", "1", upc,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            root, data, upc_log, run_log = result.stdout.splitlines()
            return {"root": root, "data": data, "upc_log": upc_log, "run_log": run_log}

        first = resolve("N_03009_01002_HR")
        second = resolve("N_03009_01003_HR")
        self.assertEqual(
            first["root"],
            "s3://dhms-new-stgae/DHMS/NSV/Silver/zone=A/phase=1/cycle=1/N-03009-01002-HR",
        )
        self.assertEqual(
            second["root"],
            "s3://dhms-new-stgae/DHMS/NSV/Silver/zone=A/phase=1/cycle=1/N-03009-01003-HR",
        )
        self.assertNotEqual(first["root"], second["root"])
        self.assertEqual(first["data"], first["root"] + "/dlm_kpi_new")
        self.assertEqual(second["data"], second["root"] + "/dlm_kpi_new")
        self.assertTrue(first["upc_log"].startswith(first["root"] + "/"))
        self.assertTrue(second["upc_log"].startswith(second["root"] + "/"))
        self.assertEqual(first["run_log"], first["root"] + "/run.log")
        self.assertEqual(second["run_log"], second["root"] + "/run.log")


if __name__ == "__main__":
    unittest.main()
