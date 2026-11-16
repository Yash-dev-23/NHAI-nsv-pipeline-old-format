import unittest

from ris_silver.app import PathsMissing, execute, format_plan, load_run


class PlanTests(unittest.TestCase):
    def test_plan_lists_tables_and_waits_for_paths(self):
        ctx = load_run("B", "2", "1", "N_07024_01001_GJ")
        text = format_plan(ctx)
        self.assertIn("master_roughness", text)
        self.assertIn("ready    validate", text)
        self.assertNotIn("pending", text)
        self.assertEqual(ctx.bronze_root, "")
        with self.assertRaises(PathsMissing):
            execute(ctx)


if __name__ == "__main__":
    unittest.main()
