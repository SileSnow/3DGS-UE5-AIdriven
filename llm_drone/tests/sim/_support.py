"""仿真 Agent HTTP 测试夹具（临时端口 port=0 + 临时审计目录，不污染 logs/）。

注意：unittest discover 以 tests 为顶层目录时，本包被命名为 `sim`，
tests/sim/__init__.py 已把真实实现目录追加进 __path__。
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from safety.audit import AuditManager, safe_run_id
from safety.config import load_config
from sim.config import SimConfig
from sim.server import AgentApp, create_agent_server

LLM_DRONE = Path(__file__).resolve().parents[2]
SAMPLE_MISSION_PATH = LLM_DRONE / "spec" / "sample_mission.json"


def load_sample_mission() -> dict:
    with open(SAMPLE_MISSION_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


class SimFixture:
    """启动一个端口随机的真实 HTTP 仿真 Agent（后台 tick 线程）。"""

    def __init__(self, time_scale: float = 100.0, tick_wall_s: float = 0.02, run_id: str = "test"):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="llm_drone_sim_test_"))
        self.audit_dir = self.tmpdir / "audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.config = SimConfig(
            host="127.0.0.1",
            port=0,
            time_scale=float(time_scale),
            tick_wall_s=float(tick_wall_s),
        )
        self.safety = load_config()
        self.audit = AuditManager(self.audit_dir, run_id)
        self.app = AgentApp(config=self.config, safety_config=self.safety, audit=self.audit)
        self.handle = create_agent_server(
            "127.0.0.1", 0, self.config, self.safety, self.audit, app=self.app
        )
        self.handle.start()
        if not self.handle.wait_ready(10.0):
            raise RuntimeError("仿真 HTTP server 启动失败")
        self.base = self.handle.url
        self.command_seq = 0

    # -------------------------------------------------------------- 生命周期
    def close(self) -> None:
        try:
            self.handle.shutdown()
        finally:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    # -------------------------------------------------------------- HTTP
    def http(self, method: str, path: str, body=None):
        url = self.base + path
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30.0) as response:
                raw = response.read().decode("utf-8")
                return response.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return exc.code, {"raw": raw}

    def get(self, path: str) -> dict:
        status, payload = self.http("GET", path)
        assert status == 200, "GET %s -> HTTP %s: %s" % (path, status, payload)
        return payload

    def post(self, path: str, body) -> dict:
        status, payload = self.http("POST", path, body)
        assert status == 200, "POST %s -> HTTP %s: %s" % (path, status, payload)
        return payload

    # -------------------------------------------------------------- 命令
    def command(self, tool: str, args=None, confirm=None, command_id=None) -> dict:
        self.command_seq += 1
        payload = {
            "command_id": command_id or ("c-%04d" % self.command_seq),
            "tool": tool,
            "args": args or {},
        }
        if confirm is not None:
            payload["confirm"] = confirm
        return self.post("/v1/command", payload)

    def ok_command(self, tool: str, args=None, confirm=None, command_id=None) -> dict:
        response = self.command(tool, args, confirm, command_id=command_id)
        assert response.get("ok") is True, "命令失败: %s" % json.dumps(response, ensure_ascii=False)[:600]
        return response

    def reset(self, run_id: str = "test") -> dict:
        body = self.post("/v1/reset", {"run_id": run_id})
        assert body.get("ok") is True
        assert body.get("run_id") == run_id
        return body

    def sim_config(self, **overrides) -> dict:
        body = self.post("/v1/sim/config", overrides)
        assert body.get("ok") is True, body
        return body

    def telemetry(self) -> dict:
        return self.get("/v1/telemetry")

    # -------------------------------------------------------------- 等待
    def wait(self, predicate, timeout: float = 30.0, interval: float = 0.01, desc: str = "条件"):
        deadline = time.time() + float(timeout)
        last = None
        while time.time() < deadline:
            last = self.telemetry()
            if predicate(last):
                return last
            time.sleep(interval)
        raise AssertionError(
            "等待超时(%ss): %s; last=%s" % (timeout, desc, json.dumps(last, ensure_ascii=False)[:500])
        )

    def wait_state(self, *states: str, timeout: float = 30.0) -> dict:
        return self.wait(lambda t: t.get("state") in states, timeout=timeout, desc="state=%s" % (states,))

    def wait_mission(self, mission_id: str, states=("completed", "aborted", "failed"), timeout: float = 30.0) -> dict:
        deadline = time.time() + float(timeout)
        last = None
        while time.time() < deadline:
            body = self.get("/v1/missions/%s" % mission_id)
            last = body
            if body.get("ok") is True and body.get("state") in states:
                return body
            time.sleep(0.01)
        raise AssertionError(
            "等待 mission %s 结束超时; last=%s" % (mission_id, json.dumps(last, ensure_ascii=False)[:500])
        )

    # -------------------------------------------------------------- 常用流程
    def takeoff_and_hover(self, altitude_m: float = 40.0) -> dict:
        self.ok_command("takeoff", {"altitude_m": altitude_m}, confirm=True)
        return self.wait_state("hovering")

    def sample_mission(self) -> dict:
        return load_sample_mission()

    # -------------------------------------------------------------- 审计
    def audit_path(self, run_id: str) -> Path:
        return self.audit_dir / ("audit_%s.jsonl" % safe_run_id(run_id))

    def audit_events(self, run_id: str):
        """读取审计文件（容忍后台 tick 并发追加；坏行/半行跳过）。"""
        path = self.audit_path(run_id)
        events = []
        if not path.is_file():
            return events
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def wait_audit_event(self, run_id: str, event: str, predicate=None, timeout: float = 30.0) -> dict:
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            for record in self.audit_events(run_id):
                if record.get("event") == event and (predicate is None or predicate(record)):
                    return record
            time.sleep(0.02)
        raise AssertionError("等待审计事件 %r 超时" % event)
