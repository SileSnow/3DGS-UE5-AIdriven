"""安全策略配置（阈值 / 圆形围栏 / 禁飞区 / 能量估算参数）。

默认值 **严格** 按 llm_drone/spec/PROTOCOL.md 第 8 与 8.1 节：
  最大相对高度 120 m / 最大水平速度 15 m/s / 圆形围栏 圆心 (39.9042,116.4074) 半径 300 m
  禁飞区 polygon（见 DEFAULT_NO_FLY_POLYGON）/ 起飞最低电量 30% / 返航保留 20%
  GPS fix>=3 且 satellites>=10 / 遥控必须连接 / real 模式 Phase1 禁止
阈值可被 llm_drone/safety/config.json 覆盖（默认值必须保持上表，对抗测试用默认值）。
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .geo import ORIGIN_WGS84

SAFETY_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SAFETY_DIR / "config.json"
ENV_CONFIG_PATH = "LLM_DRONE_SAFETY_CONFIG"

#: PROTOCOL.md §8.1 默认禁飞区多边形（逐字一致）
DEFAULT_NO_FLY_POLYGON: List[Dict[str, float]] = [
    {"lat": 39.9046, "lon": 116.4078},
    {"lat": 39.9050, "lon": 116.4078},
    {"lat": 39.9050, "lon": 116.4082},
    {"lat": 39.9046, "lon": 116.4082},
]

DEFAULT_NO_FLY_ZONES = [
    {
        "name": "default_no_fly",
        "alt_range_m": [0, 120],
        "polygon": DEFAULT_NO_FLY_POLYGON,
    }
]

#: 能量估算参数（与仿真电量模型 PROTOCOL.md §10 一致）
DEFAULT_ENERGY = {
    "idle_pct_per_s": 0.01,
    "climb_pct_per_s": 0.15,
    "descend_pct_per_s": 0.15,
    "cruise_pct_per_s": 0.05,
    "hover_pct_per_s": 0.04,
    "climb_speed_mps": 3.0,
    "descend_speed_mps": 3.0,
    "rth_speed_mps": 10.0,
    "hover_before_action_s": 0.5,
}

DEFAULT_REQUIRE_CONFIRM_TOOLS = ("takeoff", "goto_waypoints", "orbit")


@dataclass
class SafetyConfig:
    """确定性安全策略配置（不可变用法：加载后只读）。"""

    max_alt_m: float = 120.0
    max_speed_mps: float = 15.0
    min_takeoff_battery_pct: float = 30.0
    rth_reserve_pct: float = 20.0
    force_rth_pct: float = 20.0
    gps_min_fix: int = 3
    gps_min_satellites: int = 10
    require_rc: bool = True
    require_confirm_tools: List[str] = field(
        default_factory=lambda: list(DEFAULT_REQUIRE_CONFIRM_TOOLS)
    )
    allow_real_mode: bool = False
    origin: Dict[str, float] = field(default_factory=lambda: dict(ORIGIN_WGS84))
    geofence: Dict[str, Any] = field(
        default_factory=lambda: {
            "type": "circle",
            "center": {"lat": 39.9042, "lon": 116.4074},
            "radius_m": 300.0,
        }
    )
    no_fly_zones: List[Dict[str, Any]] = field(
        default_factory=lambda: copy.deepcopy(DEFAULT_NO_FLY_ZONES)
    )
    energy: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ENERGY))

    # -------------------------------------------------------------- 序列化
    def to_dict(self) -> dict:
        return {
            "max_alt_m": self.max_alt_m,
            "max_speed_mps": self.max_speed_mps,
            "min_takeoff_battery_pct": self.min_takeoff_battery_pct,
            "rth_reserve_pct": self.rth_reserve_pct,
            "force_rth_pct": self.force_rth_pct,
            "gps_min_fix": self.gps_min_fix,
            "gps_min_satellites": self.gps_min_satellites,
            "require_rc": self.require_rc,
            "require_confirm_tools": list(self.require_confirm_tools),
            "allow_real_mode": self.allow_real_mode,
            "origin": dict(self.origin),
            "geofence": copy.deepcopy(self.geofence),
            "no_fly_zones": copy.deepcopy(self.no_fly_zones),
            "energy": dict(self.energy),
        }

    # -------------------------------------------------------------- 校验
    def validate(self) -> "SafetyConfig":
        """检查配置自身合法性，非法则 ValueError。"""
        if not (0 < float(self.max_alt_m) <= 1000):
            raise ValueError("max_alt_m 必须在 (0, 1000] 米内")
        if not (0 < float(self.max_speed_mps) <= 100):
            raise ValueError("max_speed_mps 必须在 (0, 100] m/s 内")
        for key in ("min_takeoff_battery_pct", "rth_reserve_pct", "force_rth_pct"):
            value = float(getattr(self, key))
            if not (0.0 <= value <= 100.0):
                raise ValueError("%s 必须在 [0,100] 内" % key)
        fence = self.geofence or {}
        if fence.get("type") != "circle":
            raise ValueError("geofence.type 仅支持 circle（PROTOCOL.md §8 默认值）")
        center = fence.get("center") or {}
        if "lat" not in center or "lon" not in center:
            raise ValueError("geofence.center 缺 lat/lon")
        if float(fence.get("radius_m", 0)) <= 0:
            raise ValueError("geofence.radius_m 必须 > 0")
        for nfz in self.no_fly_zones:
            if not isinstance(nfz, dict) or "polygon" not in nfz:
                raise ValueError("no_fly_zones 每项必须含 polygon")
            if len(nfz["polygon"]) < 3:
                raise ValueError("no_fly_zones polygon 至少 3 个顶点")
            alt_range = nfz.get("alt_range_m") or [0, self.max_alt_m]
            if len(alt_range) != 2 or float(alt_range[0]) > float(alt_range[1]):
                raise ValueError("no_fly_zones alt_range_m 非法")
        return self

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "SafetyConfig":
        cfg = cls()
        if not data:
            return cfg.validate()
        known = set(cfg.to_dict().keys())
        unknown = set(data.keys()) - known - {"version", "description", "note"}
        if unknown:
            raise ValueError("safety config 未知字段: %s" % sorted(unknown))
        for key in known:
            if key in data:
                setattr(cfg, key, data[key])
        cfg.require_confirm_tools = list(cfg.require_confirm_tools)
        # 合并 energy 默认值（允许只覆盖部分键）
        energy = dict(DEFAULT_ENERGY)
        energy.update(cfg.energy or {})
        cfg.energy = energy
        return cfg.validate()


def default_config() -> SafetyConfig:
    """返回 PROTOCOL.md 默认配置（不读文件）。"""
    return SafetyConfig().validate()


def config_path_from_env() -> Optional[Path]:
    env = os.environ.get(ENV_CONFIG_PATH)
    if env:
        return Path(env)
    return None


def load_config(path: Optional[Any] = None) -> SafetyConfig:
    """加载安全配置：显式 path > 环境变量 > safety/config.json > 代码默认值。"""
    candidate = Path(path) if path is not None else config_path_from_env()
    if candidate is None and DEFAULT_CONFIG_PATH.is_file():
        candidate = DEFAULT_CONFIG_PATH
    if candidate is None:
        return default_config()
    if not Path(candidate).is_file():
        if path is not None:
            raise FileNotFoundError("safety config 不存在: %s" % candidate)
        return default_config()
    with open(candidate, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return SafetyConfig.from_dict(data)


# ---------------------------------------------------------------------------
# 兼容层（仅保留旧 CONTRACT 版测试/工具使用的名字；新代码请直接用 SafetyConfig）
# ---------------------------------------------------------------------------
from dataclasses import dataclass as _dataclass  # noqa: E402


@_dataclass
class Fence:
    """圆形/多边形地理围栏（旧接口名字兼容）。"""

    id: str = "fence"
    name: str = "fence"
    type: str = "circle"
    center: Optional[dict] = None
    radius_m: float = 0.0
    vertices: list = None
    max_alt_m: float = 120.0


@_dataclass
class NFZ:
    """禁飞区（旧接口名字兼容）。"""

    id: str = "nfz"
    name: str = "nfz"
    polygon: list = None
    alt_range_m: list = None


def load_safety_config(config_path: Optional[Any] = None, overrides: Optional[dict] = None, **_ignored: Any) -> SafetyConfig:
    """兼容旧接口：加载安全配置并可选覆盖阈值。"""
    cfg = load_config(path=config_path)
    if overrides:
        data = cfg.to_dict()
        data.update(overrides)
        cfg = SafetyConfig.from_dict(data)
    return cfg


def _with_overrides(self: SafetyConfig, **overrides: Any) -> SafetyConfig:
    """返回覆盖部分字段后的新配置（不可变用法）。"""
    data = self.to_dict()
    data.update(overrides)
    return SafetyConfig.from_dict(data)


SafetyConfig.with_overrides = _with_overrides  # type: ignore[attr-defined]

