"""测试辅助：隔离的临时输出目录 + 进程内仿真器/服务器构造器。"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

LLM_DRONE = Path(__file__).resolve().parents[1]
if str(LLM_DRONE) not in sys.path:
    sys.path.insert(0, str(LLM_DRONE))

from safety.audit import AuditLogger  # noqa: E402
from safety.config import Fence, NFZ, SafetyConfig, load_safety_config  # noqa: E402
from safety.geo import ORIGIN_WGS84, local_to_wgs84  # noqa: E402
from safety.validator import SafetyValidator, nominal_state  # noqa: E402
from sim.config import SimConfig  # noqa: E402
from sim.simulator import DroneSimulator  # noqa: E402

ORIGIN = dict(ORIGIN_WGS84)


class TempWorkspace:
    """每个测试一个临时目录，退出时自动清理。"""

    def __init__(self, prefix="llm_drone_test_"):
        self.path = Path(tempfile.mkdtemp(prefix=prefix))
        self.output_dir = self.path / "output"
        self.audit_path = self.path / "audit" / "audit.jsonl"

    def cleanup(self):
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()
        return False


def make_safety(**overrides):
    """加载默认安全配置（真实 data/ 围栏+禁飞区），可选覆盖阈值。"""
    cfg = load_safety_config()
    if overrides:
        cfg = cfg.with_overrides(**overrides)
    return cfg


def make_audit(ws: TempWorkspace):
    return AuditLogger(ws.audit_path)


def make_sim(ws: TempWorkspace, safety=None, audit=None, **sim_overrides):
    """构造进程内仿真器（输出/审计都指向临时目录，确定性无风）。"""
    safety = safety or make_safety()
    audit = audit or make_audit(ws)
    overrides = {
        "mode": "sim",
        "time_scale": 1.0,
        "tick_hz": 100.0,
        "wind_mps": {"east": 0.0, "north": 0.0},
        "output_dir": str(ws.output_dir),
        "audit_path": str(ws.audit_path),
        "initial_battery_pct": 100.0,
    }
    overrides.update(sim_overrides)
    cfg = SimConfig(**overrides)
    sim = DroneSimulator(safety_config=safety, sim_config=cfg, audit=audit)
    return sim


def advance_until(sim, predicate, max_sim_s=600.0, step=0.1, desc="条件"):
    """推进仿真直到 predicate() 为真；超时抛 AssertionError 并附状态。"""
    elapsed = 0.0
    while elapsed <= max_sim_s:
        if predicate():
            return elapsed
        sim.advance(step)
        elapsed += step
    raise AssertionError(
        f"等待{desc}超时（{max_sim_s}s），state={sim.state} mission={sim.mission and sim.mission['mission_id']} "
        f"up={sim.up_m:.2f} battery={sim.battery_pct:.1f}"
    )


def takeoff(sim, altitude=40.0, max_sim_s=120.0):
    result = sim.cmd_takeoff(altitude)
    advance_until(sim, lambda: sim.state == "hovering", max_sim_s=max_sim_s, desc="起飞完成")
    return result


def make_waypoints(*triples, speed=6.0):
    """(east_m, north_m, alt_rel_m) -> goto_waypoints 参数（相对项目原点）。"""
    wps = []
    for east, north, alt in triples:
        p = local_to_wgs84(east, north, 0.0)
        wps.append({"lat": p["lat"], "lon": p["lon"], "alt_rel_m": float(alt), "speed_mps": speed})
    return wps


def airborne_state(alt_rel_m=40.0, battery=100.0, **overrides):
    st = nominal_state(
        airborne=True,
        vehicle_state="hovering",
        alt_rel_m=float(alt_rel_m),
        battery_pct=float(battery),
    )
    st.update(overrides)
    return st


def ground_state(**overrides):
    st = nominal_state()
    st.update(overrides)
    return st


def square_polygon(half_m=100.0, origin=None):
    """以项目原点为中心、半边长 half_m 的方形围栏顶点（lat/lon 列表）。"""
    origin = origin or ORIGIN
    pts = []
    for east, north in [(-half_m, -half_m), (half_m, -half_m), (half_m, half_m), (-half_m, half_m)]:
        p = local_to_wgs84(east, north, 0.0, origin=origin)
        pts.append({"lat": p["lat"], "lon": p["lon"]})
    return pts


def make_polygon_fence(half_m=100.0, fence_id="poly_fence"):
    return Fence(
        id=fence_id,
        name="测试多边形围栏",
        type="polygon",
        vertices=square_polygon(half_m),
        max_alt_m=120.0,
    )


def start_http_server(ws: TempWorkspace, safety=None, time_scale=60.0, start_tick=True, verbose=False):
    """启动端口随机的 Drone Agent（真实 HTTP），返回 (handle, client)。"""
    from sim.drone_agent import create_server
    from tests.helpers_http import HttpClient

    safety = safety or make_safety()
    audit = make_audit(ws)
    cfg = SimConfig(
        mode="sim",
        time_scale=time_scale,
        tick_hz=100.0,
        wind_mps={"east": 0.0, "north": 0.0},
        output_dir=str(ws.output_dir),
        audit_path=str(ws.audit_path),
        start_before=0.0,
    )
    handle = create_server(port=0, sim_config=cfg, safety_config=safety, audit=audit,
                           verbose=verbose, start_tick=start_tick)
    handle.start()
    handle.wait_ready(timeout=10.0)
    client = HttpClient(handle.url)
    return handle, client


def read_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
