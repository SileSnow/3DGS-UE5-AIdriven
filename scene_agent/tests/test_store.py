import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scene_agent import errors as E
from scene_agent import ops as scene_ops
from scene_agent.store import SceneStore

ORIGIN = {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}
LICENSE = {"type": "self_captured", "holder": "test", "evidence_path": "LICENSE"}

ELEMENTS = [
    {"object_id": "bldg_003", "display_name": "3号楼", "aliases": ["三号楼"],
     "class": "building",
     "transform": {"frame": "UE_LHS_Zup_cm", "location_cm": [12000.0, -3400.0, 0.0]},
     "geometry": {"kind": "mesh",
                  "bounds_local_cm": {"min": [-500, -300, 0], "max": [500, 300, 1200]}},
     "tags": ["editable"]},
    {"object_id": "ground", "display_name": "地面", "class": "ground",
     "transform": {"frame": "UE_LHS_Zup_cm", "location_cm": [0.0, 0.0, 0.0]},
     "geometry": {"kind": "mesh"}},
    {"object_id": "tank_01", "display_name": "1号罐", "class": "tank",
     "transform": {"frame": "UE_LHS_Zup_cm", "location_cm": [3000.0, 2000.0, 0.0]},
     "geometry": {"kind": "mesh"}},
]


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="scene_agent_test_")
        self.store = SceneStore(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def import_scene(self, **overrides):
        body = {"scene_id": "s", "origin_wgs84": ORIGIN, "license": LICENSE,
                "elements": json.loads(json.dumps(ELEMENTS)),
                "run_id": "r-import", "command_id": "c-import"}
        body.update(overrides)
        return self.store.import_scene(body)

    def plan(self, ops=None, utterance=None):
        body = {"scene_id": "s"}
        if ops is not None:
            body["ops"] = ops
        if utterance is not None:
            body["utterance"] = utterance
        return self.store.scene_plan(body)

    def commit(self, plan, expected=0, **overrides):
        body = {"scene_ref": plan["intent"]["scene_ref"], "intent_id": plan["intent_id"],
                "expected_version": expected, "confirm": True,
                "run_id": "r-commit", "command_id": "c-commit"}
        body.update(overrides)
        return self.store.scene_commit(body)

    def move_ops(self, delta=None):
        return [{"op": "translate", "targets": [{"object_id": "bldg_003"}],
                 "params": {"delta": delta or [500, 0, 0], "frame": "UE_LHS_Zup_cm",
                            "delta_semantics": "world_axis"}}]

    def test_import_and_load(self):
        resp = self.import_scene()
        self.assertEqual(resp["scene_version"], 0)
        self.assertEqual(resp["n_elements"], 3)
        self.assertEqual(resp["license_status"], "declared")
        self.assertFalse(resp["readonly"])
        loaded = self.store.scene_load({"scene_id": "s"})
        self.assertEqual(loaded["scene_version"], 0)
        self.assertEqual(len(loaded["manifest_sha256"]), 64)

    def test_plan_and_commit_move(self):
        self.import_scene()
        plan = self.plan(utterance="把3号楼往东移5米")
        self.assertEqual(plan["preview_diff"]["summary"]["modified"], 1)
        out = self.commit(plan)
        self.assertEqual(out["new_version"], 1)
        self.assertEqual(out["readback"], "pass")
        scene = self.store._load_scene("s", 1)
        bldg = next(e for e in scene["elements"] if e["object_id"] == "bldg_003")
        self.assertEqual(bldg["transform"]["location_cm"], [12500.0, -3400.0, 0.0])
        verify = self.store.scene_verify({"scene_id": "s"})
        self.assertTrue(verify["ok"])

    def test_confirm_required(self):
        self.import_scene()
        plan = self.plan(ops=self.move_ops())
        with self.assertRaises(E.SceneError) as ctx:
            self.commit(plan, confirm=False)
        self.assertEqual(ctx.exception.code, E.CONFIRM_REQUIRED)

    def test_version_conflict(self):
        self.import_scene()
        plan = self.plan(ops=self.move_ops())
        with self.assertRaises(E.SceneError) as ctx:
            self.commit(plan, expected=1)
        self.assertEqual(ctx.exception.code, E.VERSION_CONFLICT)

    def test_license_draft_blocks_commit(self):
        self.import_scene(license={})
        plan = self.plan(ops=self.move_ops())
        with self.assertRaises(E.SceneError) as ctx:
            self.commit(plan)
        self.assertEqual(ctx.exception.code, E.LICENSE_UNDECLARED)

    def test_splat_not_editable(self):
        elements = json.loads(json.dumps(ELEMENTS))
        elements.append({"object_id": "splat_main", "display_name": "背景",
                         "class": "other",
                         "transform": {"frame": "UE_LHS_Zup_cm", "location_cm": [0, 0, 0]},
                         "geometry": {"kind": "splat_ref", "asset_id": "splat_main"}})
        self.import_scene(elements=elements)
        ops = [{"op": "translate", "targets": [{"object_id": "splat_main"}],
                "params": {"delta": [0, 0, 100], "frame": "UE_LHS_Zup_cm"}}]
        with self.assertRaises(E.SceneError) as ctx:
            self.plan(ops=ops)
        self.assertEqual(ctx.exception.code, E.ASSET_NOT_EDITABLE)

    def test_locked_element(self):
        elements = json.loads(json.dumps(ELEMENTS))
        elements[0]["locked"] = True
        self.import_scene(elements=elements)
        with self.assertRaises(E.SceneError) as ctx:
            self.plan(ops=self.move_ops())
        self.assertEqual(ctx.exception.code, E.OBJECT_LOCKED)

    def test_noop(self):
        self.import_scene()
        with self.assertRaises(E.SceneError) as ctx:
            self.plan(ops=self.move_ops([0, 0, 0]))
        self.assertEqual(ctx.exception.code, E.NOOP)

    def test_bounds_violation(self):
        self.import_scene(bounds_cm={"min": [-1000, -1000, 0], "max": [1000, 1000, 1000]})
        with self.assertRaises(E.SceneError) as ctx:
            self.plan(ops=self.move_ops([500, 0, 0]))
        self.assertEqual(ctx.exception.code, E.BOUNDS_VIOLATION)

    def test_ambiguous_name(self):
        elements = json.loads(json.dumps(ELEMENTS))
        elements.append({"object_id": "pump_a", "display_name": "泵", "class": "pumpjack",
                         "transform": {"frame": "UE_LHS_Zup_cm", "location_cm": [0, 0, 0]},
                         "geometry": {"kind": "mesh"}})
        elements.append({"object_id": "pump_b", "display_name": "泵", "class": "pumpjack",
                         "transform": {"frame": "UE_LHS_Zup_cm", "location_cm": [100, 0, 0]},
                         "geometry": {"kind": "mesh"}})
        self.import_scene(elements=elements)
        with self.assertRaises(E.SceneError) as ctx:
            self.plan(ops=[{"op": "translate", "targets": [{"name": "泵"}],
                            "params": {"delta": [0, 0, 100], "frame": "UE_LHS_Zup_cm"}}])
        self.assertEqual(ctx.exception.code, E.AMBIGUOUS_TARGET)

    def test_undo_restores_parent_bytes(self):
        self.import_scene()
        out = self.commit(self.plan(ops=self.move_ops()))
        self.assertEqual(out["new_version"], 1)
        undo = self.store.scene_undo({"scene_id": "s", "of_version": 1,
                                      "expected_version": 1, "confirm": True,
                                      "run_id": "r-undo", "command_id": "c-undo"})
        self.assertEqual(undo["new_version"], 2)
        versions = self.store.scene_versions({"scene_id": "s"})["versions"]
        by_v = {v["version"]: v for v in versions}
        self.assertEqual(by_v[2]["scene_json_sha256"], by_v[0]["scene_json_sha256"])

    def test_undo_with_wgs84_anchor(self):
        elements = json.loads(json.dumps(ELEMENTS))
        elements[0]["wgs84_anchor"] = scene_ops.ue_to_wgs84(
            elements[0]["transform"]["location_cm"], ORIGIN)
        self.import_scene(elements=elements)
        self.commit(self.plan(ops=self.move_ops()))
        undo = self.store.scene_undo({"scene_id": "s", "of_version": 1,
                                      "expected_version": 1, "confirm": True,
                                      "run_id": "r-undo-anchor", "command_id": "c-undo-anchor"})
        self.assertEqual(undo["new_version"], 2)
        versions = self.store.scene_versions({"scene_id": "s"})["versions"]
        by_v = {v["version"]: v for v in versions}
        self.assertEqual(by_v[2]["scene_json_sha256"], by_v[0]["scene_json_sha256"])

    def test_rollback_creates_new_version(self):
        self.import_scene()
        self.commit(self.plan(ops=self.move_ops()))
        rb = self.store.scene_rollback({"scene_id": "s", "to_version": 0,
                                        "expected_version": 1, "confirm": True,
                                        "run_id": "r-rb", "command_id": "c-rb"})
        self.assertEqual(rb["new_version"], 2)
        self.assertTrue(rb["sha256_equals_target"])
        versions = self.store.scene_versions({"scene_id": "s"})["versions"]
        by_v = {v["version"]: v for v in versions}
        self.assertEqual(by_v[2]["scene_json_sha256"], by_v[0]["scene_json_sha256"])

    def test_checkpoint_save_open(self):
        self.import_scene()
        cp = self.store.checkpoint_save({"scene_id": "s", "version": 0,
                                         "label": "base", "run_id": "r-cp"})
        self.commit(self.plan(ops=self.move_ops()))
        opened = self.store.checkpoint_open({"scene_id": "s",
                                             "checkpoint_id": cp["checkpoint_id"],
                                             "expected_version": 1, "confirm": True,
                                             "run_id": "r-cpo", "command_id": "c-cpo"})
        self.assertEqual(opened["new_version"], 2)
        self.assertTrue(opened["sha256_equals_checkpoint"])

    def test_query_and_get(self):
        self.import_scene()
        q = self.store.scene_query({"scene_id": "s", "filter": {"name_contains": "楼"}})
        self.assertEqual(q["n_total"], 1)
        q2 = self.store.scene_query({"scene_id": "s", "filter": {"class": ["tank"]}})
        self.assertEqual(q2["n_total"], 1)
        page = self.store.scene_query({"scene_id": "s", "limit": 1})
        self.assertEqual(len(page["elements"]), 1)
        self.assertEqual(page["cursor"], "1")
        got = self.store.scene_get({"scene_id": "s", "object_id": "bldg_003"})
        self.assertEqual(got["element"]["derived"]["bounds_world_cm"]["min"][0], 11500.0)

    def test_idempotent_command(self):
        self.import_scene()
        plan = self.plan(ops=self.move_ops())
        first = self.commit(plan)
        second = self.commit(plan)
        self.assertEqual(first["new_version"], second["new_version"])
        self.assertEqual(self.store.scene_load({"scene_id": "s"})["scene_version"], 1)

    def test_run_id_required(self):
        self.import_scene()
        plan = self.plan(ops=self.move_ops())
        with self.assertRaises(E.SceneError) as ctx:
            self.commit(plan, run_id="")
        self.assertEqual(ctx.exception.code, E.RUN_ID_REQUIRED)

    def test_versions_orphan(self):
        self.import_scene()
        self.store._version_dir("s", 99).mkdir(parents=True)
        out = self.store.scene_versions({"scene_id": "s"})
        self.assertEqual(out["orphans"], [99])


if __name__ == "__main__":
    unittest.main()
