import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scene_agent.server import make_server

ORIGIN = {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}
ELEMENTS = [
    {"object_id": "bldg_003", "display_name": "3号楼", "class": "building",
     "transform": {"frame": "UE_LHS_Zup_cm", "location_cm": [12000.0, -3400.0, 0.0]},
     "geometry": {"kind": "mesh"}},
    {"object_id": "ground", "display_name": "地面", "class": "ground",
     "transform": {"frame": "UE_LHS_Zup_cm", "location_cm": [0.0, 0.0, 0.0]},
     "geometry": {"kind": "mesh"}},
]


class HTTPTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="scene_agent_http_")
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.root, ignore_errors=True)

    def post(self, path, body):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_health(self):
        status, body = self.get("/v1/scene/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_http_flow(self):
        status, imp = self.post("/v1/scene/import", {
            "scene_id": "s", "origin_wgs84": ORIGIN,
            "license": {"type": "self", "holder": "t", "evidence_path": "LICENSE"},
            "elements": ELEMENTS, "run_id": "r-import", "command_id": "c-import"})
        self.assertEqual(status, 200)
        self.assertTrue(imp["ok"], imp)

        status, loaded = self.post("/v1/scene/load", {"scene_id": "s"})
        self.assertEqual(loaded["scene_version"], 0)

        status, plan = self.post("/v1/scene/edit/plan", {
            "scene_id": "s", "utterance": "把3号楼往东移5米"})
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["preview_diff"]["summary"]["modified"], 1)

        status, commit = self.post("/v1/scene/edit/commit", {
            "scene_ref": plan["intent"]["scene_ref"], "intent_id": plan["intent_id"],
            "expected_version": 0, "confirm": True, "run_id": "r2", "command_id": "c2"})
        self.assertTrue(commit["ok"], commit)
        self.assertEqual(commit["new_version"], 1)

        status, verify = self.post("/v1/scene/verify", {"scene_id": "s"})
        self.assertTrue(verify["ok"], verify)

    def test_http_business_error_is_200(self):
        status, imp = self.post("/v1/scene/import", {
            "scene_id": "s", "origin_wgs84": ORIGIN, "elements": ELEMENTS,
            "run_id": "r", "command_id": "c"})
        self.assertTrue(imp["ok"], imp)
        status, plan = self.post("/v1/scene/edit/plan", {
            "scene_id": "s", "utterance": "把3号楼往东移5米"})
        status, out = self.post("/v1/scene/edit/commit", {
            "scene_ref": plan["intent"]["scene_ref"], "intent_id": plan["intent_id"],
            "expected_version": 0, "run_id": "r3", "command_id": "c3"})
        self.assertEqual(status, 200)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "E_CONFIRM_REQUIRED")

    def test_unknown_path(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/v1/scene/nope", {})
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
