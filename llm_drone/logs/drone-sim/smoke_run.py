"""独立 smoke：真实启动 `python -m sim.server` 后走完 spec 正向链路。

不 import sim/safety（黑盒 urllib），验证：
health -> reset -> preflight -> takeoff -> goto_waypoints(sample_mission 16 点) ->
mission completed(16 photos) -> return_to_home -> land；审计 JSONL 逐行可解析；c2w 正交。

用法（在 dji_ue5_3dgs/llm_drone 下）：
    python logs/drone-sim/smoke_run.py
输出：stdout JSON 摘要 + 真实 server 审计文件 logs/drone-sim/audit_smoke_<ts>.jsonl
"""

from __future__ import annotations

import json
import math
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

LLM_DRONE = Path(__file__).resolve().parents[2]
SPEC_MISSION = LLM_DRONE / "spec" / "sample_mission.json"
LOG_DIR = LLM_DRONE / "logs" / "drone-sim"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Client:
    def __init__(self, base: str, timeout: float = 30.0):
        self.base = base
        self.timeout = timeout

    def http(self, method: str, path: str, body=None):
        url = self.base + path
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return response.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            return exc.code, {"raw": raw}

    def get(self, path: str) -> dict:
        return self.http("GET", path)[1]

    def post(self, path: str, body) -> dict:
        return self.http("POST", path, body)[1]

    def command(self, command_id: str, tool: str, args=None, confirm=None) -> dict:
        payload = {"command_id": command_id, "tool": tool, "args": args or {}}
        if confirm is not None:
            payload["confirm"] = confirm
        return self.post("/v1/command", payload)

    def wait(self, predicate, timeout: float, desc: str):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.get("/v1/telemetry")
            if predicate(last):
                return last
            time.sleep(0.1)
        raise TimeoutError("等待 %s 超时: %s" % (desc, json.dumps(last, ensure_ascii=False)[:400]))


def is_orthonormal(c2w, tol: float = 1e-6) -> bool:
    if not isinstance(c2w, list) or len(c2w) != 16:
        return False
    rotation = [
        [c2w[0], c2w[1], c2w[2]],
        [c2w[4], c2w[5], c2w[6]],
        [c2w[8], c2w[9], c2w[10]],
    ]
    for i in range(3):
        for j in range(3):
            dot = sum(rotation[i][k] * rotation[j][k] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > tol:
                return False
    determinant = (
        rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    return abs(determinant - 1.0) <= tol


def main() -> int:
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_id = "smoke_%s" % ts
    port = free_port()
    base = "http://127.0.0.1:%d" % port
    cmd = [
        sys.executable,
        "-m",
        "sim.server",
        "--port",
        str(port),
        "--time-scale",
        "20",
        "--audit-dir",
        str(LOG_DIR),
    ]
    print("[smoke] start:", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        cwd=str(LLM_DRONE),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    result = {"run_id": run_id, "port": port, "command": " ".join(cmd), "steps": [], "ok": False}
    client = Client(base)
    try:
        deadline = time.time() + 40.0
        health = None
        while time.time() < deadline:
            try:
                status, payload = client.http("GET", "/v1/health")
                if status == 200 and payload.get("ok"):
                    health = payload
                    break
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.05)
        if health is None:
            raise RuntimeError("server 未就绪")
        result["steps"].append({"step": "health", "ok": True, "health": health})
        result["health"] = health

        reset = client.post("/v1/reset", {"run_id": run_id})
        result["steps"].append({"step": "reset", "ok": reset.get("ok"), "run_id": reset.get("run_id")})
        telemetry = client.get("/v1/telemetry")
        result["steps"].append(
            {
                "step": "telemetry_initial",
                "ok": telemetry.get("state") == "idle",
                "state": telemetry.get("state"),
                "battery_pct": telemetry.get("battery_pct"),
            }
        )

        preflight = client.command("c-0001", "preflight_check")
        result["steps"].append(
            {"step": "preflight_check", "ok": preflight.get("can_fly") is True, "can_fly": preflight.get("can_fly")}
        )

        takeoff = client.command("c-0002", "takeoff", {"altitude_m": 40.0}, confirm=True)
        result["steps"].append({"step": "takeoff", "ok": takeoff.get("ok") is True, "state": takeoff.get("state")})
        hover = client.wait(lambda item: item.get("state") == "hovering", 30.0, "hovering")
        result["steps"].append(
            {"step": "hovering", "ok": True, "alt_rel_m": hover.get("alt_rel_m"), "battery_pct": hover.get("battery_pct")}
        )

        mission = json.loads(SPEC_MISSION.read_text(encoding="utf-8"))
        goto = client.command(
            "c-0003",
            "goto_waypoints",
            {"mission": mission, "photo_interval_s": 1},
            confirm=True,
        )
        result["steps"].append(
            {"step": "goto_waypoints", "ok": goto.get("ok") is True, "mission_id": goto.get("mission_id"), "state": goto.get("state")}
        )
        mission_id = goto.get("mission_id")
        record = None
        deadline = time.time() + 90.0
        while time.time() < deadline:
            record = client.get("/v1/missions/%s" % mission_id)
            if record.get("state") in ("completed", "aborted", "failed"):
                break
            time.sleep(0.1)
        photos = record.get("photos") or []
        orthonormal = all(is_orthonormal(photo.get("c2w")) for photo in photos)
        result["steps"].append(
            {
                "step": "mission_completed",
                "ok": record.get("state") == "completed",
                "state": record.get("state"),
                "progress_pct": record.get("progress_pct"),
                "n_photos": len(photos),
                "n_photos_expected": 16,
                "stats": record.get("stats"),
                "c2w_orthonormal": orthonormal,
                "photo_files": [photo.get("file") for photo in photos[:3]],
            }
        )
        result["mission_record"] = record

        rth = client.command("c-0004", "return_to_home")
        result["steps"].append({"step": "return_to_home", "ok": rth.get("ok") is True, "state": rth.get("state")})
        idle = client.wait(lambda item: item.get("state") == "idle", 40.0, "idle(after rth)")
        result["steps"].append(
            {
                "step": "landed_idle",
                "ok": True,
                "state": idle.get("state"),
                "lat": idle.get("lat"),
                "lon": idle.get("lon"),
                "alt_rel_m": idle.get("alt_rel_m"),
            }
        )

        land_ground = client.command("c-0005", "land", {})
        result["steps"].append(
            {
                "step": "land_on_ground_rejected",
                "ok": land_ground.get("ok") is False
                and (land_ground.get("error") or {}).get("code") == "E_STATE",
                "error_code": (land_ground.get("error") or {}).get("code"),
            }
        )

        audit_api = client.get("/v1/audit?since_seq=0")
        audit_path = LOG_DIR / ("audit_%s.jsonl" % run_id)
        lines = audit_path.read_text(encoding="utf-8").splitlines()
        parsed = [json.loads(line) for line in lines if line.strip()]
        seqs = [event.get("seq") for event in parsed]
        required_fields = all(
            isinstance(event.get("ts"), str)
            and isinstance(event.get("seq"), int)
            and event.get("run_id") == run_id
            and isinstance(event.get("event"), str)
            for event in parsed
        )
        event_names = sorted({event["event"] for event in parsed})
        result["audit"] = {
            "path": str(audit_path),
            "lines": len(parsed),
            "last_seq": parsed[-1]["seq"] if parsed else 0,
            "seq_from_1_increasing": seqs == list(range(1, len(seqs) + 1)),
            "required_fields": required_fields,
            "api_last_seq": audit_api.get("last_seq"),
            "event_names": event_names,
            "has_command_rejected": "command_rejected" in event_names,
            "photocaptured_events": sum(1 for event in parsed if event["event"] == "photo_captured"),
            "mission_completed_events": sum(1 for event in parsed if event["event"] == "mission_completed"),
        }
        result["ok"] = all(step.get("ok") for step in result["steps"]) and result["audit"]["seq_from_1_increasing"]
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
        result["ok"] = False
    finally:
        proc.terminate()
        try:
            output = proc.communicate(timeout=10)[0]
        except subprocess.TimeoutExpired:
            proc.kill()
            output = proc.communicate()[0]
        result["server_output"] = (output or "")[-2500:]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
