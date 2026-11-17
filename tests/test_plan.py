import os
import unittest

from ris_silver.app import PathsMissing, execute, format_plan, load_run


class PlanTests(unittest.TestCase):
    def test_plan_lists_tables_and_waits_for_paths(self):
        ctx = load_run("B", "2", "1", "N_07024_01001_GJ")
        text = format_plan(ctx)
        self.assertIn("master_roughness", text)
        self.assertIn("ready    validate", text)
        self.assertNotIn("pending", text)
        self.assertTrue(ctx.bronze_root)
        self.assertTrue(ctx.tracker_path)
        with self.assertRaises(ValueError):
            execute(ctx)

    def test_env_derived_paths_are_used(self):
        original = {
            key: os.environ.get(key)
            for key in ("PROJECT_ROOT", "BRONZE_S3_ROOT", "SILVER_S3_ROOT", "TRACKER_S3", "IMAGE_ROOT")
        }
        try:
            os.environ["PROJECT_ROOT"] = "/tmp/project-root"
            os.environ["BRONZE_S3_ROOT"] = "s3://nhai-dhms-uat/databricks-nsv-downloads/final_bronze_output"
            os.environ["SILVER_S3_ROOT"] = "s3://dhms-new-stgae/DHMS/NSV/Silver"
            os.environ["TRACKER_S3"] = "s3://dhms-new-stgae/DHMS/NSV/NSV_Activity_Tracker_ZoneWise_Standardized_17072026.xlsx"
            os.environ["IMAGE_ROOT"] = "s3://dhms-new-stgae/DHMS/NSV/images"
            ctx = load_run("B", "2", "1", "N_07024_01001_GJ")
            self.assertEqual(ctx.bronze_root, "s3://nhai-dhms-uat/databricks-nsv-downloads/final_bronze_output")
            self.assertEqual(ctx.silver_root, "s3://dhms-new-stgae/DHMS/NSV/Silver")
            self.assertEqual(ctx.tracker_path, "s3://dhms-new-stgae/DHMS/NSV/NSV_Activity_Tracker_ZoneWise_Standardized_17072026.xlsx")
            self.assertEqual(ctx.image_root, "s3://dhms-new-stgae/DHMS/NSV/images")
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
