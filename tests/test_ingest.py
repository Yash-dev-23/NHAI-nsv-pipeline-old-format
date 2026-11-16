import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ris_silver.app import PathsMissing, execute
from ris_silver.context import RunContext
from ris_silver.io.paths import silver_partition_dir
from ris_silver.io.writer import publish
from ris_silver.domain.cracking import apply_cracking_correction
from ris_silver.domain.frames import expand_to_10m
from ris_silver.domain.metrics import bi_from_iri


def _write_tracker(path: Path) -> None:
    width = 54
    header = [f"c{i}" for i in range(width)]
    row = [None] * width
    row[2] = 2
    row[3] = 1
    row[6] = "GJ"
    row[7] = "PIU-A"
    row[8] = "Contractor"
    row[9] = "AE"
    row[12] = "N/07024/01001/GJ"
    row[21] = "2024-01-01"
    row[22] = "2024-01-31"
    row[42] = "Bituminous"
    row[43] = 85
    row[46], row[47] = "CA", 100
    row[48], row[49] = "IRC", 100
    row[50], row[51] = "CA", 100
    row[52], row[53] = "CA", 1000
    title = ["Tracker"] + [None] * (width - 1)
    pd.DataFrame([title, header, row]).to_excel(path, index=False, header=False, sheet_name="Zone B")


def _bronze(root: Path) -> None:
    day = root / "Source=NSV/Zone=B/Phase=2/Cycle=1/UPC=N_07024_01001_GJ/year=2024/month=01/day=15"
    d1 = day / "Deliverable=Deliverable - 1"
    d2 = day / "Deliverable=Deliverable - 2"
    d3 = day / "Deliverable=Deliverable - 3"
    d4 = day / "Deliverable=Deliverable - 4"
    for folder in (d1, d2, d3, d4):
        folder.mkdir(parents=True)
    left = root / "Source=NSV_Backup/Zone=B/Phase=2/Cycle=1/UPC=N_07024_01001_GJ/year=2024/month=01/day=15/Lane=L-1"
    right = root / "Source=NSV_Backup/Zone=B/Phase=2/Cycle=1/UPC=N_07024_01001_GJ/year=2024/month=01/day=15/Lane=R-1"
    left.mkdir(parents=True)
    right.mkdir(parents=True)
    pd.DataFrame({
        "Concession Agreement Roughness BI Limitation": [2000],
        "Rutting Limitation": [8],
        "Cracking Limitation %": [5],
        "Ravelling Limitation %": [12],
    }).to_parquet(d2 / "Survey As per CA.parquet")
    pd.DataFrame({
        "Cracking Limit": [15],
        "Rutting Limit": [9],
        "Ravelling Limit %": [11],
    }).to_parquet(d2 / "Survey As per IRC.parquet")
    pd.DataFrame({
        "Start_Chainage": [0],
        "End_Chainage": [1000],
        "L1 crack 1000m": [4.0],
    }).to_parquet(d2 / "Crack Sheet As per CA.parquet")
    pd.DataFrame({
        "Start_Chainage": [1000],
        "End_Chainage": [1100],
        "L1 crack 100m": [10.0],
    }).to_parquet(d2 / "ZZ Crack As per IRC.parquet")
    pd.DataFrame({
        "chainage": [1.005],
        "lane": ["L1"],
        "area": [0.2],
        "severity": ["Medium"],
    }).to_parquet(d2 / "Report_Potholes.parquet")
    pd.DataFrame({
        "LwpIri": [1.0],
        "RwpIri": [3.0],
        "LaneIri": [9.0],
        "RoughnessIndex": [999.0],
        "Start_Chainage": [1000],
        "End_Chainage": [1010],
    }).to_parquet(left / "seg_Roughness_IRI.parquet")
    pd.DataFrame({
        "Percent_Area": [4.0],
        "Area_Sum": [1.4],
        "Start_Chainage": [1000],
        "End_Chainage": [1010],
        "cracking_image_name": ["crack.jpg"],
        "Start_Latitude": [23.5],
        "Start_Longitude": [72.5],
        "survey_date_crack": ["2024-01-20"],
    }).to_parquet(left / "seg_Cracking.parquet")
    pd.DataFrame({"Rutting Average": [6.0], "Start_Chainage": [1000], "End_Chainage": [1010]}).to_parquet(left / "seg_Rutting.parquet")
    pd.DataFrame({"Rutting Average": [3.0], "Start_Chainage": [2000], "End_Chainage": [2010]}).to_parquet(right / "seg_Rutting.parquet")
    pd.DataFrame({"Raveling_Area_m2": [7.0], "Start_Chainage": [1000], "End_Chainage": [1010]}).to_parquet(left / "seg_Raveling.parquet")
    pd.DataFrame({
        "from_ch_km": [1, 0],
        "from_ch_m": [250, 11250],
        "to_ch_km": [1, 11],
        "to_ch_m": [260, 250],
        "chainage": [1250, 11250],
        "lane_no": ["L-1", "R1"],
        "severity": ["High", "Low"],
        "area_sq_m": [0.4, 0.1],
        "type_of_defect": ["Pothole", "Pothole"],
        "latitude": [23.2, 23.3],
        "longitude": [72.2, 72.3],
    }).to_parquet(d4 / "potholes.parquet")
    pd.DataFrame({
        "Condition": ["Poor", None],
        "Start_Chainage": [1050, 2000],
        "Lane": ["L1", "L1"],
    }).to_parquet(d3 / "crack_visual.parquet")
    pd.DataFrame({
        "PavementType": ["Asphalt", "NA"],
        "Start_Chainage": [0, 100],
        "End_Chainage": [5000, 6000],
    }).to_parquet(d1 / "PavementType.parquet")
    pd.DataFrame({
        "Chainage": [1000, 2000],
        "NHNumber": ["NH0027", "NH151A"],
        "Direction": ["Increasing", "Decreasing"],
    }).to_parquet(d1 / "LRPMaster.parquet")


class IngestTests(unittest.TestCase):
    def test_reference_and_facts_from_a_fake_bronze_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tracker(root / "tracker.xlsx")
            _bronze(root / "bronze")
            images = root / "images"
            images.mkdir()
            (images / "survey_L1_1_000000.jpg").write_bytes(b"img")
            silver = root / "silver"
            other = silver / "master_roughness" / "upc=OTHER" / "phase=2" / "cycle=1"
            other.mkdir(parents=True)
            pd.DataFrame({"upc_code": ["OTHER"]}).to_parquet(other / "part-000.parquet", index=False)
            kept_cycle = silver / "master_roughness" / "upc=N_07024_01001_GJ" / "phase=2" / "cycle=9"
            kept_cycle.mkdir(parents=True)
            pd.DataFrame({"cycle": [9]}).to_parquet(kept_cycle / "part-000.parquet", index=False)
            stale = silver / "master_roughness" / "upc=N_07024_01001_GJ" / "phase=2" / "cycle=1"
            stale.mkdir(parents=True)
            (stale / "old.parquet").write_bytes(b"stale")
            ctx = RunContext(
                zone="B",
                phase="2",
                cycle="1",
                upc="N_07024_01001_GJ",
                config_dir=root,
                pipeline={
                    "cracking": {"area_divisor_m2": 35},
                    "intervals": {"parent_m": 1000, "child_100m": 100, "child_10m": 10},
                },
                irc={
                    "roughness_mm_per_km": 2400,
                    "rutting_mm": 10,
                    "cracking_percent": 30,
                    "ravelling_percent": 10,
                },
                bronze_root=str(root / "bronze"),
                silver_root=str(silver),
                tracker_path=str(root / "tracker.xlsx"),
                image_root=str(images),
            )
            execute(ctx)
            self.assertNotIn("FAIL", {row["status"] for row in ctx.frames["validation"]})
            self.assertTrue((silver / "dlm_validation_results" / "upc=N_07024_01001_GJ" / "phase=2" / "cycle=1" / "part-000.parquet").is_file())

            tracker = ctx.frames["tracker"]
            self.assertEqual(tracker["state"], "GJ")
            self.assertEqual(tracker["threshold_label_override"], "As per CA")
            self.assertEqual(tracker["raw_defect_standards"]["rutting"]["standard"], "IRC")
            self.assertEqual(tracker["defect_standards"]["rutting"]["standard"], "CA")
            self.assertEqual(str(tracker["survey_start_date"]), "2024-01-01")
            ca = ctx.frames["thresholds"]["ca"]
            self.assertEqual(ca["roughness_bi"], 2000)
            self.assertEqual(ca["cracking_pct"], 5)
            self.assertEqual(ctx.frames["thresholds"]["irc_file"]["cracking_pct"], 15)

            facts = ctx.frames["facts"]
            self.assertEqual(facts["lanes"], ["L1", "R1"])
            rough = facts["roughness"].iloc[0]
            self.assertEqual(rough["IRI"], 2.0)
            self.assertAlmostEqual(rough["BI m/km"], bi_from_iri(2))
            self.assertEqual(rough["IRI_original"], 9.0)
            self.assertEqual(ctx.frames["correction"]["calib_source"], "IRC")
            self.assertEqual(ctx.frames["correction"]["calib_m"], 100)
            self.assertEqual(ctx.frames["correction"]["ca_interval_m"], 1000)
            self.assertEqual(ctx.frames["correction"]["rows_changed"], 0)
            self.assertAlmostEqual(facts["cracking"].iloc[0]["Cracking"], 4.0)
            self.assertEqual(facts["cracking"].iloc[0]["Condition"], "Very Good (<5%)")
            canonical = ctx.frames["canonical"]
            self.assertAlmostEqual(canonical["roughness"].iloc[0]["metric_value"], bi_from_iri(2))
            self.assertEqual(canonical["roughness"].iloc[0]["side"], "LHS")
            self.assertEqual(canonical["cracking"].iloc[0]["ca_breach"], 0)
            self.assertEqual(canonical["ravelling"].iloc[0]["ca_breach"], 1)
            self.assertEqual(len(canonical["rutting"]), 2)
            tables = ctx.frames["tables"]
            rough_parent = tables["master_roughness"].iloc[0]
            self.assertEqual(rough_parent["side"], "LHS")
            self.assertEqual(rough_parent["breach_flag"], 0)
            self.assertEqual(rough_parent["parent_id"], "N_07024_01001_GJ_LHS_1000_2000")
            self.assertEqual(int(rough_parent["start_chainage"]), 1000)
            self.assertEqual(int(rough_parent["end_chainage"]), 1010)
            self.assertAlmostEqual(rough_parent["metric_value"], round(bi_from_iri(2), 6))
            ravel = tables["master_ravelling_ca"].iloc[0]
            self.assertEqual(ravel["breach_flag"], 1)
            self.assertEqual(ravel["road_condition"], "Bad")
            self.assertEqual(ravel["display_defect_id"], "D/310124/N/00001")
            ravel_child = tables["master_ravelling_irc"].iloc[0]
            self.assertEqual(ravel_child["breach_flag"], 1)
            self.assertEqual(ravel_child["threshold_value"], 10.0)
            self.assertEqual(ravel_child["display_defect_id"], "D/310124/N/00001/0001")
            self.assertEqual(tables["master_potholes"]["display_defect_id"].tolist(), ["D/310124/N/00002", "D/310124/N/00003"])
            self.assertAlmostEqual(float(rough_parent["pci"]), 96.4615)
            self.assertEqual(rough_parent["rating_ca"], "Good (<1600mm/km)")
            self.assertTrue(pd.isna(rough_parent["rating_irc"]))
            self.assertEqual(rough_parent["nh_number"], "NH-27")
            self.assertEqual(rough_parent["road_condition"], "Good")
            ten = tables["child_10m_roughness"].iloc[0]
            self.assertEqual(float(ten["pci"]), 24.0)
            self.assertEqual(ten["rating_irc"], "Good")
            self.assertAlmostEqual(float(ravel["pci"]), 92.4)
            self.assertEqual(ravel["rating_ca"], "Poor (>=12%)")
            crack_parent = tables["master_cracking_ca"].iloc[0]
            self.assertEqual(crack_parent["rating_ca"], "Good")
            self.assertEqual(crack_parent["rating_irc"], "Very Good (<5%)")
            self.assertEqual(crack_parent["severity"], "None")
            self.assertEqual(crack_parent["road_condition"], "Good")
            crack_irc = tables["master_cracking_irc"].iloc[0]
            self.assertEqual(crack_irc["road_condition"], "Very Good (<5%)")
            crack_10 = tables["child_10m_cracking"].iloc[0]
            self.assertEqual(crack_10["road_condition"], "Good")
            self.assertEqual(crack_10["rating_irc"], "Very Good (<5%)")
            self.assertEqual(tables["master_potholes"]["rating_ca"].tolist(), ["High", "Low"])
            self.assertEqual(float(tables["master_potholes"].iloc[0]["pci"]), 84.0)
            rhs = tables["master_rutting"].loc[tables["master_rutting"]["side"] == "RHS"].iloc[0]
            self.assertEqual(rhs["nh_number"], "NH-151A")
            chainage = tables["master_chainage"].sort_values("chainage_start").reset_index(drop=True)
            self.assertEqual(chainage["chainage_start"].tolist(), [1000, 2000])
            left = chainage.iloc[0]
            self.assertEqual(int(left["chainage_end"]), 1010)
            self.assertEqual(float(left["l1_start_chainage"]), 1000.0)
            self.assertEqual(float(left["l1_end_chainage"]), 1010.0)
            self.assertAlmostEqual(left["l1_start_lat"], 23.5)
            self.assertAlmostEqual(left["l1_start_long"], 72.5)
            self.assertTrue(pd.isna(left["r1_start_chainage"]))
            self.assertEqual(float(left["lhs_start_chainage"]), 1000.0)
            self.assertEqual(left["lhs_lanes"], "L1")
            self.assertEqual(left["lhs_pavement_type"], "Asphalt")
            self.assertEqual(left["lanes_present"], "L1")
            self.assertEqual(left["nh_number"], "NH-27")
            self.assertEqual(left["upc"], "N/07024/01001/GJ")
            self.assertEqual(float(left["upc_end_chainage"]), 2010.0)
            right = chainage.iloc[1]
            self.assertEqual(right["lanes_present"], "R1")
            self.assertEqual(right["rhs_lanes"], "R1")
            self.assertEqual(right["nh_number"], "NH-151A")
            self.assertEqual(right["rhs_pavement_type"], "Asphalt")
            self.assertEqual(int(right["cycle"]), 1)
            written = silver_partition_dir(ctx, "master_roughness")
            self.assertFalse((written / "old.parquet").exists())
            stored = pd.read_parquet(written / "part-000.parquet")
            self.assertEqual(len(stored), len(tables["master_roughness"]))
            self.assertEqual(stored["upc"].iloc[0], "N_07024_01001_GJ")
            stored_chainage = pd.read_parquet(silver_partition_dir(ctx, "master_chainage") / "part-000.parquet")
            self.assertEqual(stored_chainage["chainage_start"].tolist(), [1000, 2000])
            for name in tables:
                self.assertTrue((silver_partition_dir(ctx, name) / "part-000.parquet").is_file())
            self.assertEqual(pd.read_parquet(other / "part-000.parquet")["upc_code"].iloc[0], "OTHER")
            self.assertEqual(int(pd.read_parquet(kept_cycle / "part-000.parquet")["cycle"].iloc[0]), 9)
            self.assertEqual(facts["ravelling"].iloc[0]["Ravelling"], 20.0)
            self.assertEqual(facts["pothole_source"], "D4")
            starts = sorted(facts["potholes"]["Start_Chainage"].tolist())
            self.assertEqual(starts, [1250, 11250])
            self.assertEqual(facts["potholes"].iloc[0]["Lane"], "L1")
            self.assertEqual(list(facts["d1"]["pavement"]["PavementType"]), ["Asphalt"])
            visual = facts["d3"]["Cracking"]
            self.assertEqual(len(visual), 1)
            self.assertEqual(int(visual.iloc[0]["bin_100m"]), 1000)

            ctx.pipeline["force_d2_potholes"] = True
            execute(ctx)
            self.assertNotIn("FAIL", {row["status"] for row in ctx.frames["validation"]})
            fallback = ctx.frames["facts"]["potholes"]
            self.assertEqual(ctx.frames["facts"]["pothole_source"], "D2")
            self.assertEqual(int(fallback.iloc[0]["Start_Chainage"]), 1005)
            self.assertEqual(fallback.iloc[0]["Image_Name"], "survey_L1_1_000000.jpg")
            self.assertEqual(fallback.iloc[0]["Image_Source"], "segment_frame_image_file")
            self.assertAlmostEqual(float(fallback.iloc[0]["Latitude"]), 23.5)


class CorrectionTests(unittest.TestCase):
    def test_scales_down_to_the_d2_bin_and_leaves_other_lanes(self):
        cracking = pd.DataFrame({
            "Lane": ["L1", "L1", "R1"],
            "Start_Chainage": [1000, 1010, 1000],
            "End_Chainage": [1010, 1020, 1010],
            "Area_sq_m": [20.0, 20.0, 5.0],
            "Cracking": [0.0, 0.0, 0.0],
        })
        sources = {
            "ca_frame": pd.DataFrame({"Start_Chainage": [0], "End_Chainage": [1000], "L1 crack 1000m": [1.0]}),
            "ca_chain": "Start_Chainage",
            "ca_interval": "1000m",
            "irc_frame": pd.DataFrame({"Start_Chainage": [1000], "L1 crack 100m": [10.0]}),
            "irc_chain": "Start_Chainage",
            "irc_interval": "100m",
        }
        corrected, report = apply_cracking_correction(cracking, sources, 5)
        self.assertEqual(report["calib_source"], "IRC")
        left = corrected[corrected["Lane"] == "L1"]["Area_sq_m"].tolist()
        self.assertEqual(left, [17.5, 17.5])
        self.assertEqual(corrected[corrected["Lane"] == "L1"]["Cracking"].tolist(), [50.0, 50.0])
        self.assertEqual(corrected[corrected["Lane"] == "R1"]["Area_sq_m"].iloc[0], 5.0)
        check = next(item for item in report["checks"] if item["level_m"] == 100 and item["lane"] == "L1")
        self.assertEqual(check["mean_abs_diff_pct"], 0.0)

    def test_does_not_scale_area_up(self):
        cracking = pd.DataFrame({
            "Lane": ["L1", "L1"],
            "Start_Chainage": [1000, 1010],
            "End_Chainage": [1010, 1020],
            "Area_sq_m": [10.0, 10.0],
            "Cracking": [0.0, 0.0],
        })
        sources = {
            "ca_frame": pd.DataFrame({"Start_Chainage": [0], "L1 crack 1000m": [1.0]}),
            "ca_chain": "Start_Chainage",
            "ca_interval": "1000m",
            "irc_frame": pd.DataFrame({"Start_Chainage": [1000], "L1 crack 100m": [10.0]}),
            "irc_chain": "Start_Chainage",
            "irc_interval": "100m",
        }
        corrected, report = apply_cracking_correction(cracking, sources, 5)
        self.assertEqual(report["rows_changed"], 0)
        self.assertEqual(corrected["Area_sq_m"].tolist(), [10.0, 10.0])

    def test_missing_ca_sheet_is_an_error(self):
        with self.assertRaises(ValueError):
            apply_cracking_correction(pd.DataFrame({"Lane": ["L1"]}), {"ca_frame": None}, 5)


class HierarchyTests(unittest.TestCase):
    def test_parent_averages_lanes_and_breaches_if_any_lane_does(self):
        from datetime import date

        from ris_silver.domain.hierarchy import build_silver_tables
        from ris_silver.domain.spec import linear_specs

        canonical = {
            "roughness": pd.DataFrame([
                {"lane": "L1", "side": "LHS", "start_chainage": 1000, "end_chainage": 1010, "length_m": 10,
                 "metric_value": 100.0, "ca_breach": 0, "lwp_iri": None, "rwp_iri": None},
                {"lane": "L2", "side": "LHS", "start_chainage": 1000, "end_chainage": 1010, "length_m": 10,
                 "metric_value": 3000.0, "ca_breach": 1, "lwp_iri": None, "rwp_iri": None},
            ]),
            "rutting": pd.DataFrame(),
            "ravelling": pd.DataFrame(),
            "cracking": pd.DataFrame(),
        }
        tables = build_silver_tables(
            canonical, pd.DataFrame(), "UPC", linear_specs(1000, 100, 10),
            {"roughness": 2000.0, "rutting": 8.0, "ravelling": 12.0, "cracking": 5.0},
            {"roughness": 2400.0, "rutting": 10.0, "cracking": 30.0, "ravelling": 10.0},
            1000, date(2024, 1, 31),
        )
        parent = tables["master_roughness"].iloc[0]
        self.assertEqual(parent["metric_value"], 1550.0)
        self.assertEqual(parent["breach_flag"], 1)
        self.assertEqual(parent["total_children"], 2)
        self.assertEqual(parent["display_defect_id"], "D/310124/N/00001")
        ca_child = tables["child_roughness_as_per_ca"]
        self.assertEqual(ca_child.loc[ca_child["lane"] == "L2", "display_defect_id"].iloc[0], "D/310124/N/00001/0001")
        irc_child = tables["child_100m_roughness"]
        self.assertEqual(set(irc_child["breach_flag"]), {0, 1})
        self.assertEqual(irc_child.loc[irc_child["lane"] == "L2", "breach_flag"].iloc[0], 1)
        self.assertEqual(irc_child.loc[irc_child["lane"] == "L1", "breach_flag"].iloc[0], 0)


class PublishTests(unittest.TestCase):
    def test_empty_silver_root_is_refused(self):
        ctx = RunContext(
            zone="B", phase="2", cycle="1", upc="U1",
            config_dir=Path("."), pipeline={}, irc={},
        )
        with self.assertRaises(PathsMissing):
            publish(ctx)

    def test_second_run_replaces_this_partition_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = RunContext(
                zone="B", phase="2", cycle="1", upc="U1",
                config_dir=root, pipeline={}, irc={},
                silver_root=str(root),
            )
            other = root / "master_roughness" / "upc=OTHER" / "phase=2" / "cycle=1"
            other.mkdir(parents=True)
            pd.DataFrame({"upc": ["OTHER"]}).to_parquet(other / "part-000.parquet", index=False)
            ctx.frames["tables"] = {"master_roughness": pd.DataFrame({"upc": ["U1", "U1"], "n": [1, 2]})}
            publish(ctx)
            ctx.frames["tables"] = {"master_roughness": pd.DataFrame({"upc": ["U1"], "n": [9]})}
            publish(ctx)
            partition = silver_partition_dir(ctx, "master_roughness")
            stored = pd.read_parquet(partition / "part-000.parquet")
            self.assertEqual(stored["n"].tolist(), [9])
            self.assertEqual(pd.read_parquet(other / "part-000.parquet")["upc"].iloc[0], "OTHER")
            self.assertFalse(Path(str(partition) + ".previous").exists())
            self.assertFalse(Path(str(partition) + ".staging").exists())


class GridTests(unittest.TestCase):
    def test_long_segment_is_copied_onto_the_10m_grid(self):
        pieces = expand_to_10m([{"start_chainage": 1005, "end_chainage": 1015, "metric_value": 3}])
        self.assertEqual([piece["start_chainage"] for piece in pieces], [1005, 1010])
        self.assertEqual([piece["end_chainage"] for piece in pieces], [1010, 1020])
        self.assertEqual(pieces[1]["metric_value"], 3)


if __name__ == "__main__":
    unittest.main()
