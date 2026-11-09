"""仿真配置（PROTOCOL.md 第 10 节默认值）。

默认：time_scale=20（每 100ms 墙钟推进 dt=0.1*time_scale 仿真秒）、home=(39.9042,116.4074,43.0)、
爬升/下降 3 m/s、RTH 10 m/s、电量率 idle .01 / 爬升下降 .15 / 巡航 .05 / 悬停 .04 %/s、
到达半径 0.5 m、动作前悬停 0.5 s、初始电量 100%、GPS fix=3/sats=24、RC 连接、mode=sim。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from safety.geo import ORIGIN_WGS84

SIM_VERSION = "1.0.0"

DEFAULT_CAMERA = {
    "model": "DJI Mini 4 Pro (simulated)",
    "width": 1600,
    "height": 1200,
    "fx": 1148.343,
    "fy": 1148.343,
    "cx": 800.0,
    "cy": 600.0,
    "fov_horizontal_deg": 69.726,
    "fov_vertical_deg": 55.18,
    "sensor_mm": {"width": 9.6, "height": 7.2, "diagonal": 12.0},
}

DEFAULT_BATTERY_RATES = {
    "idle_pct_per_s": 0.01,
    "climb_pct_per_s": 0.15,
    "descend_pct_per_s": 0.15,
    "cruise_pct_per_s": 0.05,
    "hover_pct_per_s": 0.04,
}

DEFAULT_STATE = "idle"


@dataclass
class SimConfig:
    """仿真运行参数（server CLI 可覆盖）。"""

    host: str = "127.0.0.1"
    port: int = 8765
    backend: str = "sim"
    version: str = SIM_VERSION

    time_scale: float = 20.0
    tick_wall_s: float = 0.1  # PROTOCOL.md §10：主循环每 100 ms 推进

    home_lat: float = ORIGIN_WGS84["lat"]
    home_lon: float = ORIGIN_WGS84["lon"]
    home_alt: float = ORIGIN_WGS84["alt"]

    climb_speed_mps: float = 3.0
    descend_speed_mps: float = 3.0
    rth_speed_mps: float = 10.0
    default_speed_mps: float = 5.0

    arrival_radius_m: float = 0.5
    hover_before_action_s: float = 0.5
    photo_interval_s: float = 1.0

    initial_battery_pct: float = 100.0
    initial_mode: str = "sim"
    initial_gps_fix: int = 3
    initial_gps_satellites: int = 24
    initial_rc_connected: bool = True

    camera: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_CAMERA))
    battery_rates: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_BATTERY_RATES))

    audit_dir: Optional[str] = None
    run_id: str = "default"
    echo_audit: bool = False
    max_idempotency_cache: int = 100
    max_photo_records: int = 2000

    # --- 兼容旧 CONTRACT 接口字段（新代码不读取，仅保证旧构造调用不报错）---
    mode: Optional[str] = None
    tick_hz: Optional[float] = None
    wind_mps: Optional[dict] = None
    output_dir: Optional[str] = None
    audit_path: Optional[str] = None
    inject_enabled: bool = True
    start_before: float = 0.0

    def __post_init__(self) -> None:
        if self.mode in ("sim", "dry_run", "real"):
            self.initial_mode = str(self.mode)
        if self.tick_hz:
            self.tick_wall_s = max(0.001, 1.0 / float(self.tick_hz))

    # -------------------------------------------------------------- 派生
    @property
    def origin(self) -> dict:
        return {"lat": self.home_lat, "lon": self.home_lon, "alt": self.home_alt}

    @property
    def home(self) -> dict:
        return {"lat": self.home_lat, "lon": self.home_lon, "alt_abs_m": self.home_alt}

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "backend": self.backend,
            "version": self.version,
            "time_scale": self.time_scale,
            "tick_wall_s": self.tick_wall_s,
            "home": self.home,
            "climb_speed_mps": self.climb_speed_mps,
            "descend_speed_mps": self.descend_speed_mps,
            "rth_speed_mps": self.rth_speed_mps,
            "initial_battery_pct": self.initial_battery_pct,
            "initial_mode": self.initial_mode,
            "camera": dict(self.camera),
            "battery_rates": dict(self.battery_rates),
        }


def parse_args(argv: Optional[List[str]] = None) -> SimConfig:
    """解析 `python -m sim.server` 命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="python -m sim.server",
        description="Phase-1 无人机仿真 Agent（stdlib HTTP 服务，PROTOCOL.md v1.0）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8765, help="监听端口（默认 8765，0=临时端口）")
    parser.add_argument("--time-scale", type=float, default=20.0, help="仿真时间倍率（默认 20）")
    parser.add_argument("--tick-wall-s", type=float, default=0.1, help="主循环墙钟 tick（默认 0.1s，测试可调小）")
    parser.add_argument("--home-lat", type=float, default=ORIGIN_WGS84["lat"])
    parser.add_argument("--home-lon", type=float, default=ORIGIN_WGS84["lon"])
    parser.add_argument("--home-alt", type=float, default=ORIGIN_WGS84["alt"])
    parser.add_argument("--audit-dir", default=None, help="审计目录（默认 llm_drone/logs/drone-sim）")
    parser.add_argument("--run-id", default="default", help="审计文件名 run_id（默认 default）")
    parser.add_argument("--safety-config", default=None, help="安全配置 JSON 路径（默认 safety/config.json）")
    parser.add_argument("--echo-audit", action="store_true", help="审计同时输出到 stderr（调试用）")
    args = parser.parse_args(argv)
    return SimConfig(
        host=args.host,
        port=args.port,
        time_scale=float(args.time_scale),
        tick_wall_s=float(args.tick_wall_s),
        home_lat=float(args.home_lat),
        home_lon=float(args.home_lon),
        home_alt=float(args.home_alt),
        audit_dir=args.audit_dir,
        run_id=args.run_id,
        echo_audit=bool(args.echo_audit),
    )
