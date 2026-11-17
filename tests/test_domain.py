import time
import unittest

import pandas as pd

from ris_silver.domain.breach import breaches, irc_thresholds
from ris_silver.domain.chainage import build_master_chainage
from ris_silver.domain.conditions import crack_condition, roughness_condition
from ris_silver.domain.metrics import bi_from_iri, lane_iri
from ris_silver.domain.cracking import correction_factor, cracking_percent, severity
from ris_silver.domain.hierarchy import bin_start, parent_id
from ris_silver.domain.lanes import direction_of_lane, normalize_lane, side_of_lane
from ris_silver.domain.pci import build_pci, pci_score, scale_index
from ris_silver.domain.ratings import ca_rating, crack_irc_visual, nh_at, standardize_nh_number, worst_ca_rating
from ris_silver.domain.spec import output_tables, linear_specs


class LaneTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_lane("Lane R-1"), "R1")
        self.assertEqual(normalize_lane("L.3"), "L3")
        self.assertIsNone(normalize_lane(None))

    def test_side_and_direction(self):
        self.assertEqual(side_of_lane("L2"), "LHS")
        self.assertEqual(side_of_lane("r1"), "RHS")
        self.assertEqual(direction_of_lane("L1"), "Increasing")
        self.assertEqual(direction_of_lane("R1"), "Decreasing")


class BreachTests(unittest.TestCase):
    def test_strictly_greater(self):
        self.assertFalse(breaches(2400, 2400))
        self.assertTrue(breaches(2400.1, 2400))
        self.assertFalse(breaches(None, 10))

    def test_irc_map(self):
        cuts = irc_thresholds(
            {
                "roughness_mm_per_km": 2400,
                "rutting_mm": 10,
                "cracking_percent": 30,
                "ravelling_percent": 10,
            }
        )
        self.assertEqual(cuts["cracking"], 30.0)


class HierarchyTests(unittest.TestCase):
    def test_parent_id_and_bin(self):
        self.assertEqual(bin_start(1050, 1000), 1000)
        self.assertEqual(parent_id("N_1", "LHS", 1000, 1000), "N_1_LHS_1000_2000")


class CrackingTests(unittest.TestCase):
    def test_factor_never_scales_up(self):
        self.assertEqual(correction_factor(50, 100), 0.5)
        self.assertEqual(correction_factor(120, 100), 1.0)
        self.assertIsNone(correction_factor(10, 0))

    def test_percent_and_severity(self):
        self.assertEqual(cracking_percent(35), 100.0)
        self.assertEqual(severity(2.9), "None")
        self.assertEqual(severity(3), "Medium")
        self.assertEqual(severity(6), "High")
        self.assertIsNone(severity(None))


class PciTests(unittest.TestCase):
    def test_score(self):
        weights = {
            "cracking": 0.12,
            "ravelling": 0.10,
            "pothole": 0.16,
            "patching": 0.08,
            "rutting": 0.14,
            "roughness": 0.40,
        }
        indexes = {name: 0.0 for name in weights}
        self.assertEqual(pci_score(indexes, weights), 100.0)
        indexes["roughness"] = scale_index(50, 50)
        self.assertEqual(pci_score(indexes, weights), 60.0)

    def test_one_segment_uses_the_observed_max(self):
        rough = pd.DataFrame({"lane": ["L1"], "start_chainage": [1000], "iri_value": [2.0]})
        empty = pd.DataFrame()
        pci = build_pci(
            {"roughness": rough, "rutting": empty, "ravelling": empty, "cracking": empty},
            None,
            None,
        )
        self.assertEqual(float(pci["10m"].iloc[0]["pci"]), 60.0)
        self.assertEqual(float(pci["1km"].iloc[0]["pci"]), 60.0)

    def test_patching_is_weighted_and_empty_slices_score_100(self):
        patch = pd.DataFrame({"lane": ["L1", "L1"], "start_chainage": [0, 20], "patching_area": [5.0, 0.0]})
        pci = build_pci({}, None, patch)
        by_chain = dict(zip(pci["10m"]["start_chainage"], pci["10m"]["pci"]))
        self.assertEqual(float(by_chain[0]), 92.0)
        self.assertEqual(float(by_chain[10]), 100.0)
        self.assertEqual(float(by_chain[20]), 100.0)


class RatingTests(unittest.TestCase):
    def test_nh_number(self):
        self.assertEqual(standardize_nh_number("NH0027"), "NH-27")
        self.assertEqual(standardize_nh_number("NH151A"), "NH-151A")
        self.assertEqual(standardize_nh_number("NH 8a"), "NH-8A")
        self.assertEqual(standardize_nh_number("27"), "NH-27")
        self.assertEqual(standardize_nh_number("XYZ"), "XYZ")
        self.assertIsNone(standardize_nh_number(None))

    def test_nh_stays_on_its_direction(self):
        lrms = pd.DataFrame({
            "chainage": [1000, 5000],
            "nh_number": ["NH-27", "NH-48"],
            "direction": ["Increasing", "Decreasing"],
        })
        empty = pd.DataFrame(columns=["start_chainage", "end_chainage", "nh_number", "direction"])
        self.assertEqual(nh_at(lrms, empty, 1200, "L1", None), "NH-27")
        self.assertEqual(nh_at(lrms, empty, 1200, "R1", None), "NH-48")

    def test_nh_lookup_stays_fast_for_large_direction_groups(self):
        lrms = pd.DataFrame({
            "chainage": list(range(0, 20000, 10)),
            "nh_number": ["NH-27"] * 2000,
            "direction": ["Increasing"] * 2000,
        })
        pavement = pd.DataFrame(columns=["start_chainage", "end_chainage", "nh_number", "direction"])
        start = time.perf_counter()
        for chainage in range(0, 20000, 10):
            self.assertEqual(nh_at(lrms, pavement, chainage, "L1", "Increasing"), "NH-27")
        self.assertLess(time.perf_counter() - start, 1.0)

    def test_parent_rating_is_the_worst_lane(self):
        self.assertEqual(worst_ca_rating([1000, 3000], "roughness", 2000), "Poor (>2000mm/km)")
        self.assertEqual(ca_rating("roughness", 1550, 2000), "Good (<1600mm/km)")
        self.assertEqual(crack_irc_visual(4), "Very Good (<5%)")
        self.assertEqual(crack_irc_visual(30), "Very Poor (>30%)")
        self.assertEqual(ca_rating("cracking", 5, 5), "Good")
        self.assertEqual(ca_rating("cracking", 5.1, 5), "Poor")


class MetricTests(unittest.TestCase):
    def test_roughness_and_crack_labels(self):
        self.assertEqual(lane_iri(1, 3), 2)
        self.assertEqual(bi_from_iri(2), 630.0 * (2 ** 1.12))
        self.assertNotEqual(bi_from_iri(-1), bi_from_iri(-1))
        self.assertEqual(crack_condition(4, 5), "Very Good (<5%)")
        self.assertTrue(roughness_condition(2, 1368, 2000).startswith("Good"))


class ChainageTests(unittest.TestCase):
    def test_extent_uses_the_lowest_start_and_the_highest_end(self):
        rough = pd.DataFrame([
            {"lane": "L2", "start_chainage": 1000, "end_chainage": 1020, "start_lat": 2.0, "end_lat": 8.0, "direction": "Increasing"},
            {"lane": "L1", "start_chainage": 1005, "end_chainage": 1030, "start_lat": 1.0, "end_lat": 9.0, "direction": "Increasing"},
            {"lane": "R1", "start_chainage": 2000, "end_chainage": 2010, "start_lat": 3.0, "direction": "Decreasing"},
        ])
        table = build_master_chainage({"roughness": rough}, {}, "N_1", "B", "2", "1")
        self.assertEqual(table["chainage_start"].tolist(), [1000, 2000])
        first = table.iloc[0]
        self.assertEqual(int(first["chainage_end"]), 1010)
        self.assertEqual(float(first["lhs_start_chainage"]), 1000.0)
        self.assertEqual(float(first["lhs_start_lat"]), 2.0)
        self.assertEqual(float(first["lhs_end_chainage"]), 1030.0)
        self.assertEqual(float(first["lhs_end_lat"]), 9.0)
        self.assertEqual(first["lhs_lanes"], "L1,L2")
        self.assertEqual(first["lanes_present"], "L1,L2")
        self.assertEqual(float(first["l1_start_chainage"]), 1005.0)
        self.assertEqual(float(first["l2_end_chainage"]), 1020.0)
        self.assertTrue(pd.isna(first["r1_start_chainage"]))
        self.assertEqual(table.iloc[1]["lanes_present"], "R1")
        self.assertEqual(float(table["upc_start_chainage"].iloc[0]), 1000.0)
        self.assertEqual(float(table["upc_end_chainage"].iloc[0]), 2010.0)
        self.assertEqual(table["upc"].iloc[0], "N/1")


class ValidationTests(unittest.TestCase):
    def test_a_wrong_parent_average_fails(self):
        from datetime import date
        from pathlib import Path

        from ris_silver.context import RunContext
        from ris_silver.domain.hierarchy import build_silver_tables
        from ris_silver.quality.checks import run_checks

        canonical = {
            "roughness": pd.DataFrame([{
                "lane": "L1", "side": "LHS", "start_chainage": 1000, "end_chainage": 1010,
                "length_m": 10, "metric_value": 100.0, "ca_breach": 0,
            }]),
            "rutting": pd.DataFrame(),
            "ravelling": pd.DataFrame(),
            "cracking": pd.DataFrame(),
        }
        potholes = pd.DataFrame({"Lane": ["L1"], "Start_Chainage": [1500], "End_Chainage": [1500], "Area_sq_m": [0.4]})
        tables = build_silver_tables(
            canonical, potholes, "U1", linear_specs(1000, 100, 10),
            {"roughness": 2000.0, "rutting": 8.0, "ravelling": 12.0, "cracking": 5.0},
            {"roughness": 2400.0, "rutting": 10.0, "cracking": 30.0, "ravelling": 10.0},
            1000, date(2024, 1, 31),
        )
        tables["master_chainage"] = build_master_chainage(canonical, {}, "U1", "B", "2", "1")
        ctx = RunContext(
            zone="B", phase="2", cycle="1", upc="U1", config_dir=Path("."),
            pipeline={"intervals": {"parent_m": 1000, "child_100m": 100, "child_10m": 10}},
            irc={"roughness_mm_per_km": 2400, "rutting_mm": 10, "cracking_percent": 30, "ravelling_percent": 10},
        )
        ctx.frames["canonical"] = canonical
        ctx.frames["thresholds"] = {"ca": {"roughness_bi": 2000, "rutting_mm": 8, "ravelling": 12, "cracking_pct": 5}}
        ctx.frames["correction"] = {"ca_interval_m": 1000}
        ctx.frames["facts"] = {"potholes": potholes}

        def average(results):
            return next(
                row for row in results
                if row["section"] == "V2 Parent" and row["scope"] == "master_roughness" and row["check"] == "value = average of the side lanes"
            )

        clean = run_checks(ctx, tables, {name: frame.copy() for name, frame in tables.items()})
        self.assertEqual(average(clean)["status"], "PASS")
        tampered = {name: frame.copy() for name, frame in tables.items()}
        tampered["master_roughness"].loc[tampered["master_roughness"].index[0], "metric_value"] = 999
        dirty = run_checks(ctx, tables, tampered)
        self.assertEqual(average(dirty)["status"], "FAIL")
        self.assertEqual(average(dirty)["failed"], 1)


class SpecTests(unittest.TestCase):
    def test_tables(self):
        specs = linear_specs(1000, 100, 10)
        tables = output_tables(specs)
        self.assertIn("master_roughness", tables)
        self.assertIn("child_10m_cracking", tables)
        self.assertIn("master_potholes", tables)
        self.assertIn("master_chainage", tables)
        self.assertEqual(specs["ravelling"].parent.length_m, 100)
        self.assertEqual(specs["rutting"].parent.length_m, 1000)


if __name__ == "__main__":
    unittest.main()
