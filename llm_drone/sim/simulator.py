"""无人机仿真飞行模型 + 任务执行器（纯标准库，PROTOCOL.md 第 10 节）。

- 运动学：局部 ENU 米（原点 = 项目原点/home），水平速度取 waypoint.speed_mps，
  爬升/下降 3 m/s；到点悬停 0.5s 再执行 action（stop_and_turn 简化）。
- 电量：idle 0.01%/s、爬升/下降 0.15%/s、任务巡航 0.05%/s、悬停 0.04%/s；
  空中电量 < 20% -> 强制 RTH（审计 event=force_rth, decision=force_rth）。
- 状态机（telemetry.state，PROTOCOL.md §5）：
  idle | taking_off | hovering | mission | returning | landing | aborted | failsafe
- 任务执行器：§6 Mission JSON（waypoints 顺序）-> §7.1 mission record + §7.2 c2w 照片记录。
"""

from __future__ import annotations

import copy
import math
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from safety import geo
from safety.audit import NullAuditLogger, now_iso
from safety.config import SafetyConfig, load_config
from safety.schemas import normalize_mission

from .config import SimConfig

TZ_BEIJING = timezone(timedelta(hours=8))

#: 飞行器状态（PROTOCOL.md §5）
STATES = (
    "idle",
    "taking_off",
    "hovering",
    "mission",
    "returning",
    "landing",
    "aborted",
    "failsafe",
)

AIRBORNE_STATES = frozenset(
    {"taking_off", "hovering", "mission", "returning", "landing", "aborted", "failsafe"}
)

#: 任务记录状态（PROTOCOL.md §7.1）
MISSION_STATES = ("pending", "executing", "paused", "completed", "aborted", "failed")


class SimulatorError(Exception):
    """执行期业务错误（由 HTTP 层转成 {ok:false,error:{code,message,details}}）。"""

    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})

    def to_dict(self) -> dict:
        payload = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class MissionRuntime:
    """一次 goto_waypoints 任务的运行时状态 + §7.1 记录。"""

    def __init__(
        self,
        mission_id: str,
        plan_id: Optional[str],
        mission_type: str,
        mission_def: dict,
        photo_interval_s: float = 1.0,
        take_photos: bool = True,
    ):
        self.mission_id = str(mission_id)
        self.plan_id = plan_id
        self.mission_type = str(mission_type or "grid")
        self.mission = mission_def
        self.photo_interval_s = float(photo_interval_s)
        self.take_photos = bool(take_photos)
        self.created_at = now_iso()
        self.started_at = self.created_at
        self.ended_at: Optional[str] = None
        self.state = "executing"
        self.error: Optional[dict] = None
        self.photos: List[dict] = []
        self.index = 0
        self.phase = "travel"  # travel -> hover -> action -> advance -> ... -> done
        self.hover_remaining = 0.0
        self.next_photo_time = 0.0
        self.last_photo_sim_time = -1.0e9
        self.distance_m = 0.0
        self.sim_elapsed = 0.0

    # -------------------------------------------------------------- 派生
    @property
    def n_waypoints(self) -> int:
        return len(self.mission.get("waypoints") or [])

    @property
    def progress_pct(self) -> float:
        if self.state == "completed":
            return 100.0
        if self.n_waypoints == 0:
            return 0.0
        return round(100.0 * self.index / self.n_waypoints, 1)

    def to_record(self) -> dict:
        return {
            "ok": True,
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "state": self.state,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "progress_pct": self.progress_pct,
            "photos": copy.deepcopy(self.photos),
            "error": copy.deepcopy(self.error),
            "stats": {
                "distance_m": round(self.distance_m, 3),
                "duration_s": round(self.sim_elapsed, 2),
                "n_photos": len(self.photos),
            },
        }

    def error_payload(self, code: str, message: str) -> dict:
        return {"code": str(code), "message": str(message)}


class DroneSimulator:
    """确定性无人机仿真器：命令方法改状态，advance(dt) 推进时间。"""

    def __init__(
        self,
        config: Optional[SimConfig] = None,
        safety_config: Optional[SafetyConfig] = None,
        audit: Any = None,
    ):
        self.config = config or SimConfig()
        self.safety = safety_config or load_config()
        self.audit = audit if audit is not None else NullAuditLogger()
        self.missions: "OrderedDict[str, MissionRuntime]" = OrderedDict()
        self.mission_seq = 0
        self.capture_photos: List[dict] = []
        self.capture_seq = 0
        self.photo_burst: Optional[dict] = None
        self.reset(log=False)

    # ================================================================ 状态
    def reset(self, log: bool = True) -> None:
        """恢复到 PROTOCOL.md §10 默认初始状态。"""
        self.config_home = self.config.home
        self.mode = self.config.initial_mode
        self.state = "idle"
        self.lat = float(self.config.home_lat)
        self.lon = float(self.config.home_lon)
        self.alt_abs_m = float(self.config.home_alt)
        self.alt_rel_m = 0.0
        self.heading_deg = 0.0
        self.speed_mps = 0.0
        self.vertical_speed_mps = 0.0
        self.battery_pct = float(self.config.initial_battery_pct)
        self.gimbal = {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}
        self.gps = {
            "fix": int(self.config.initial_gps_fix),
            "satellites": int(self.config.initial_gps_satellites),
        }
        self.rc = {
            "connected": bool(self.config.initial_rc_connected),
            "signal": "good" if self.config.initial_rc_connected else "lost",
        }
        self.sim_time_s = 0.0
        self.mission: Optional[MissionRuntime] = None
        self.target_alt_rel = 0.0
        self.video_recording = False
        self.photo_burst = None
        self.capture_photos = []
        self.missions.clear()
        self.mission_seq = 0
        self.capture_seq = 0
        if log:
            self.audit.log("sim_reset", state="idle", battery_pct=self.battery_pct)

    # -------------------------------------------------------------- 属性
    @property
    def home(self) -> dict:
        return {
            "lat": self.config.home_lat,
            "lon": self.config.home_lon,
            "alt_abs_m": self.config.home_alt,
        }

    @property
    def origin(self) -> dict:
        return self.config.origin

    @property
    def airborne(self) -> bool:
        return self.state in AIRBORNE_STATES

    @property
    def up_m(self) -> float:
        """兼容旧测试辅助：相对 home 的高度（米）。"""
        return self.alt_rel_m

    @property
    def active_mission(self) -> Optional[MissionRuntime]:
        if self.mission is not None and self.mission.state == "executing":
            return self.mission
        return None

    @property
    def active_mission_id(self) -> Optional[str]:
        mission = self.active_mission
        return mission.mission_id if mission is not None else None

    # -------------------------------------------------------------- 遥测
    def snapshot(self) -> dict:
        """PROTOCOL.md §5 telemetry snapshot。"""
        return {
            "ts": now_iso(),
            "sim_time_s": round(self.sim_time_s, 3),
            "state": self.state,
            "lat": round(self.lat, 7),
            "lon": round(self.lon, 7),
            "alt_rel_m": round(self.alt_rel_m, 3),
            "alt_abs_m": round(self.alt_abs_m, 3),
            "speed_mps": round(self.speed_mps, 3),
            "vertical_speed_mps": round(self.vertical_speed_mps, 3),
            "battery_pct": round(self.battery_pct, 2),
            "gimbal": {
                "pitch": round(self.gimbal["pitch"], 2),
                "yaw": round(self.gimbal["yaw"], 2),
                "roll": round(self.gimbal["roll"], 2),
            },
            "gps": {"fix": int(self.gps["fix"]), "satellites": int(self.gps["satellites"])},
            "rc": {"connected": bool(self.rc["connected"]), "signal": self.rc["signal"]},
            "mode": self.mode,
            "mission_id": self.active_mission_id,
            "home": {
                "lat": round(self.home["lat"], 7),
                "lon": round(self.home["lon"], 7),
                "alt_abs_m": round(self.home["alt_abs_m"], 3),
            },
        }

    def preflight(self) -> dict:
        from safety.validator import preflight_checks

        return preflight_checks(self.snapshot(), self.safety)

    # -------------------------------------------------------------- 注入/配置
    def apply_sim_config(self, overrides: dict) -> dict:
        """POST /v1/sim/config：故障注入（battery_pct/gps_fix/gps_satellites/rc_connected/time_scale）。"""
        applied: Dict[str, Any] = {}
        if "battery_pct" in overrides:
            self.battery_pct = max(0.0, min(100.0, float(overrides["battery_pct"])))
            applied["battery_pct"] = round(self.battery_pct, 2)
        if "gps_fix" in overrides:
            self.gps["fix"] = int(overrides["gps_fix"])
            applied["gps_fix"] = self.gps["fix"]
        if "gps_satellites" in overrides:
            self.gps["satellites"] = int(overrides["gps_satellites"])
            applied["gps_satellites"] = self.gps["satellites"]
        if "rc_connected" in overrides:
            self.rc["connected"] = bool(overrides["rc_connected"])
            self.rc["signal"] = "good" if self.rc["connected"] else "lost"
            applied["rc_connected"] = self.rc["connected"]
        if "time_scale" in overrides:
            self.config.time_scale = float(overrides["time_scale"])
            applied["time_scale"] = self.config.time_scale
        self.audit.log("sim_config", **applied)
        return applied

    # ================================================================ 命令
    def cmd_takeoff(self, args: dict) -> dict:
        altitude = float(args["altitude_m"])
        self.target_alt_rel = altitude
        self.state = "taking_off"
        self.vertical_speed_mps = float(self.config.climb_speed_mps)
        self.audit.log("takeoff_started", altitude_m=altitude, state="taking_off")
        return {"altitude_m": altitude}

    def cmd_goto_waypoints(self, args: dict) -> dict:
        mission_def = normalize_mission(args["mission"], origin=self.origin)
        requested_id = mission_def.get("mission_id")
        if requested_id:
            mission_id = str(requested_id)
            if mission_id in self.missions:
                suffix = 2
                while ("%s-r%d" % (mission_id, suffix)) in self.missions:
                    suffix += 1
                mission_id = "%s-r%d" % (mission_id, suffix)
        else:
            self.mission_seq += 1
            mission_id = "m-%04d" % self.mission_seq
        interval = float(args.get("photo_interval_s", self.config.photo_interval_s))
        take_photos = bool(args.get("take_photos", True))
        mission = MissionRuntime(
            mission_id=mission_id,
            plan_id=mission_def.get("plan_id"),
            mission_type=mission_def.get("type", "grid"),
            mission_def=mission_def,
            photo_interval_s=interval,
            take_photos=take_photos,
        )
        self.missions[mission_id] = mission
        self.mission = mission
        self.state = "mission"
        self.photo_burst = None
        self.audit.log(
            "mission_started",
            mission_id=mission_id,
            plan_id=mission_def.get("plan_id"),
            n_waypoints=mission.n_waypoints,
            photo_interval_s=interval,
        )
        return {
            "mission_id": mission_id,
            "plan_id": mission_def.get("plan_id"),
            "mission": mission.to_record(),
        }

    def cmd_set_gimbal(self, args: dict) -> dict:
        self.gimbal["pitch"] = float(args["pitch_deg"])
        if "yaw_deg" in args and args["yaw_deg"] is not None:
            self.gimbal["yaw"] = float(args["yaw_deg"])
        self.audit.log(
            "gimbal_set",
            pitch_deg=self.gimbal["pitch"],
            yaw_deg=self.gimbal["yaw"],
        )
        return {"gimbal": dict(self.gimbal)}

    def cmd_capture_photo(self, args: dict) -> dict:
        count = int(args.get("count", 1))
        interval = float(args.get("interval_s", 1.0))
        photos = [self._record_photo(source="capture")]
        warnings: List[str] = []
        if count > 1 and interval > 0:
            self.photo_burst = {
                "remaining": count - 1,
                "interval": interval,
                "next_t": self.sim_time_s + interval,
            }
            warnings.append("capture_photo: 其余 %d 张将按 interval_s=%.2f 由仿真主循环补齐" % (count - 1, interval))
        elif count > 1:
            for _ in range(count - 1):
                photos.append(self._record_photo(source="capture"))
        return {"photos": photos, "count": count, "warnings": warnings}

    def cmd_start_video(self, args: Optional[dict] = None) -> dict:
        self.video_recording = True
        self.audit.log("video_started", mission_id=self.active_mission_id)
        return {"recording": True}

    def cmd_stop_video(self, args: Optional[dict] = None) -> dict:
        self.video_recording = False
        self.audit.log("video_stopped", mission_id=self.active_mission_id)
        return {"recording": False}

    def cmd_return_to_home(self, args: Optional[dict] = None) -> dict:
        mission = self.active_mission
        if mission is not None:
            mission.state = "aborted"
            mission.error = mission.error_payload("RETURN_TO_HOME", "返航中止当前任务")
            mission.ended_at = now_iso()
            self.mission = None
            self.audit.log("mission_aborted", mission_id=mission.mission_id, reason="return_to_home")
        self.state = "returning"
        self.photo_burst = None
        self.audit.log("rth_started", reason="command")
        return {"rth": True}

    def cmd_land(self, args: Optional[dict] = None) -> dict:
        self.state = "landing"
        self.photo_burst = None
        self.audit.log("landing_started")
        return {"landing": True}

    def cmd_abort(self, args: dict) -> dict:
        reason = str(args.get("reason", "")).strip()
        result: Dict[str, Any] = {"reason": reason}
        mission = self.active_mission
        if mission is not None:
            mission.state = "aborted"
            mission.error = mission.error_payload("ABORTED", reason)
            mission.ended_at = now_iso()
            self.mission = None
            result["mission_id"] = mission.mission_id
            result["mission_state"] = "aborted"
            self.audit.log("mission_aborted", mission_id=mission.mission_id, reason=reason)
        if self.airborne:
            self.state = "hovering"
            self.speed_mps = 0.0
            self.vertical_speed_mps = 0.0
        self.photo_burst = None
        self.audit.log("aborted", reason=reason, state=self.state)
        result["state"] = self.state
        return result

    def cmd_get_mission_status(self, args: dict) -> dict:
        mission_id = args.get("mission_id")
        if mission_id:
            record = self.get_mission(str(mission_id))
            if record is None:
                raise SimulatorError(
                    "E_MISSION_NOT_FOUND", "mission_id 不存在: %s" % mission_id, {"mission_id": mission_id}
                )
            return {"mission": record}
        if self.mission is not None:
            return {"mission": self.mission.to_record()}
        if self.missions:
            last = list(self.missions.values())[-1]
            return {"mission": last.to_record()}
        return {"mission": None}

    def cmd_set_mode(self, mode: str) -> dict:
        previous = self.mode
        self.mode = str(mode)
        self.audit.log("mode_changed", mode=self.mode, previous=previous)
        return {"mode": self.mode, "previous": previous}

    # ================================================================ 查询
    def get_mission(self, mission_id: str) -> Optional[dict]:
        mission = self.missions.get(str(mission_id))
        return mission.to_record() if mission is not None else None

    def list_missions(self, limit: int = 10) -> List[dict]:
        records = [mission.to_record() for mission in self.missions.values()]
        return list(reversed(records))[: max(1, int(limit))]

    # ================================================================ 主循环
    def advance(self, dt: float) -> None:
        """推进 dt 仿真秒（server 主循环按 dt=0.1*time_scale 调用）。"""
        if dt is None or dt <= 0:
            return
        self.sim_time_s += float(dt)
        self.speed_mps = 0.0
        self.vertical_speed_mps = 0.0

        if self.state == "idle":
            self._drain("idle", dt)
        else:
            self._maybe_force_rth()
            if self.state == "taking_off":
                self._tick_taking_off(dt)
            elif self.state == "hovering":
                self._drain("hover", dt)
            elif self.state == "mission":
                self._tick_mission(dt)
            elif self.state == "returning":
                self._tick_returning(dt)
            elif self.state == "landing":
                self._tick_landing(dt)
            elif self.state in ("aborted", "failsafe"):
                self._drain("hover", dt)
        self._tick_photo_burst()

    # 兼容：旧接口名
    tick = advance

    # -------------------------------------------------------------- 电量
    def _drain(self, kind: str, dt: float) -> None:
        rate = float(self.config.battery_rates.get(kind + "_pct_per_s", 0.0))
        self.battery_pct = max(0.0, self.battery_pct - rate * float(dt))

    def _maybe_force_rth(self) -> None:
        if self.state in ("returning", "landing", "failsafe"):
            return
        threshold = float(self.safety.force_rth_pct)
        if self.battery_pct >= threshold:
            return
        reason = "battery %.2f%% < %.2f%%" % (self.battery_pct, threshold)
        self.audit.log(
            "force_rth",
            reason=reason,
            decision="force_rth",
            battery_pct=round(self.battery_pct, 2),
            threshold_pct=threshold,
            mission_id=self.active_mission_id,
        )
        mission = self.active_mission
        if mission is not None:
            mission.state = "aborted"
            mission.error = mission.error_payload("FORCE_RTH", "低电量强制返航：" + reason)
            mission.ended_at = now_iso()
            self.mission = None
            self.audit.log("mission_aborted", mission_id=mission.mission_id, reason="force_rth")
        self.state = "returning"
        self.photo_burst = None
        self.audit.log("rth_started", reason="force_rth")

    # -------------------------------------------------------------- 运动
    def _move_horizontal(self, target_lat: float, target_lon: float, speed_mps: float, dt: float):
        distance = geo.haversine_m(self.lat, self.lon, target_lat, target_lon)
        if distance <= 1e-9:
            return 0.0, True
        step = min(max(speed_mps, 0.0) * dt, distance)
        if step >= distance - 1e-9:
            self.lat, self.lon = float(target_lat), float(target_lon)
            return distance, True
        ratio = step / distance
        self.lat += (float(target_lat) - self.lat) * ratio
        self.lon += (float(target_lon) - self.lon) * ratio
        return step, False

    def _move_vertical(self, target_alt_abs: float, dt: float):
        delta = float(target_alt_abs) - self.alt_abs_m
        if abs(delta) <= 1e-9:
            return 0.0, True
        speed = self.config.climb_speed_mps if delta > 0 else self.config.descend_speed_mps
        step = min(speed * dt, abs(delta))
        self.alt_abs_m += math.copysign(step, delta)
        self.alt_rel_m = self.alt_abs_m - self.home["alt_abs_m"]
        return step, abs(delta) - step <= 1e-9

    # -------------------------------------------------------------- 状态推进
    def _tick_taking_off(self, dt: float) -> None:
        target_abs = self.home["alt_abs_m"] + self.target_alt_rel
        step, done = self._move_vertical(target_abs, dt)
        self.vertical_speed_mps = step / dt
        self._drain("climb" if step > 0 else "hover", dt)
        if done:
            self.alt_abs_m = target_abs
            self.alt_rel_m = self.alt_abs_m - self.home["alt_abs_m"]
            self.vertical_speed_mps = 0.0
            self.state = "hovering"
            self.audit.log(
                "takeoff_completed",
                altitude_m=round(self.alt_rel_m, 3),
                lat=round(self.lat, 7),
                lon=round(self.lon, 7),
            )

    def _tick_returning(self, dt: float) -> None:
        home = self.home
        distance = geo.haversine_m(self.lat, self.lon, home["lat"], home["lon"])
        if distance > self.config.arrival_radius_m:
            step, _ = self._move_horizontal(
                home["lat"], home["lon"], self.config.rth_speed_mps, dt
            )
            self.speed_mps = step / dt if dt > 0 else 0.0
            self.heading_deg = geo.bearing_deg(self.lat, self.lon, home["lat"], home["lon"])
            self._drain("cruise", dt)
            return
        self.lat, self.lon = float(home["lat"]), float(home["lon"])
        if self.alt_abs_m > home["alt_abs_m"] + 1e-6:
            step, done = self._move_vertical(home["alt_abs_m"], dt)
            self.vertical_speed_mps = -step / dt if dt > 0 else 0.0
            self._drain("descend", dt)
            if done:
                self._on_landed()
        else:
            self._on_landed()

    def _tick_landing(self, dt: float) -> None:
        home = self.home
        if self.alt_abs_m > home["alt_abs_m"] + 1e-6:
            step, done = self._move_vertical(home["alt_abs_m"], dt)
            self.vertical_speed_mps = -step / dt if dt > 0 else 0.0
            self._drain("descend", dt)
            if done:
                self._on_landed()
        else:
            self._on_landed()

    def _on_landed(self) -> None:
        self.alt_abs_m = self.home["alt_abs_m"]
        self.alt_rel_m = 0.0
        self.state = "idle"
        self.speed_mps = 0.0
        self.vertical_speed_mps = 0.0
        self.video_recording = False
        self.photo_burst = None
        self.audit.log(
            "landed",
            lat=round(self.lat, 7),
            lon=round(self.lon, 7),
            battery_pct=round(self.battery_pct, 2),
        )

    # -------------------------------------------------------------- 任务
    def _tick_mission(self, dt: float) -> None:
        mission = self.mission
        if mission is None or mission.state != "executing":
            self.state = "hovering"
            return
        mission.sim_elapsed += dt
        waypoints = mission.mission["waypoints"]
        if mission.index >= len(waypoints):
            self._complete_mission(mission)
            return
        waypoint = waypoints[mission.index]

        if mission.phase == "travel":
            target_abs = self.home["alt_abs_m"] + float(waypoint["alt_rel_m"])
            distance = geo.haversine_m(self.lat, self.lon, waypoint["lat"], waypoint["lon"])
            speed = float(waypoint["speed_mps"])
            moved, horizontal_done = self._move_horizontal(
                waypoint["lat"], waypoint["lon"], speed, dt
            )
            if moved > 0:
                self.heading_deg = geo.bearing_deg(self.lat, self.lon, waypoint["lat"], waypoint["lon"])
            mission.distance_m += moved
            self.speed_mps = moved / dt if dt > 0 else 0.0
            delta_abs = target_abs - self.alt_abs_m
            vertical_done = abs(delta_abs) <= 1e-9
            if abs(delta_abs) > 1e-9:
                vstep, vertical_done = self._move_vertical(target_abs, dt)
                self.vertical_speed_mps = math.copysign(vstep / dt, delta_abs) if dt > 0 else 0.0
                self._drain("climb" if delta_abs > 0 else "descend", dt)
            elif moved > 0:
                self._drain("cruise", dt)
            else:
                self._drain("hover", dt)
            if horizontal_done and vertical_done:
                self.lat = float(waypoint["lat"])
                self.lon = float(waypoint["lon"])
                self.alt_abs_m = target_abs
                self.alt_rel_m = self.alt_abs_m - self.home["alt_abs_m"]
                self.speed_mps = 0.0
                self.vertical_speed_mps = 0.0
                self.heading_deg = float(waypoint["heading_deg"]) % 360.0
                if self.gimbal["pitch"] != float(waypoint["gimbal_pitch_deg"]):
                    self.gimbal["pitch"] = float(waypoint["gimbal_pitch_deg"])
                mission.phase = "hover"
                mission.hover_remaining = float(self.config.hover_before_action_s)
            return

        if mission.phase == "hover":
            self._drain("hover", dt)
            mission.hover_remaining -= dt
            if mission.hover_remaining <= 1e-9:
                mission.phase = "action"
            return

        if mission.phase == "photo_wait":
            self._drain("hover", dt)
            if self.sim_time_s + 1e-9 >= mission.next_photo_time:
                self._take_mission_photo(mission)
                mission.phase = "advance"
            return

        if mission.phase == "action":
            action = waypoint.get("action", "photo")
            if action == "photo" and not mission.take_photos:
                action = "none"
            if action == "photo":
                if self.sim_time_s - mission.last_photo_sim_time < mission.photo_interval_s - 1e-9:
                    mission.phase = "photo_wait"
                    mission.next_photo_time = mission.last_photo_sim_time + mission.photo_interval_s
                else:
                    self._take_mission_photo(mission)
                    mission.phase = "advance"
            elif action == "video_start":
                if not self.video_recording:
                    self.video_recording = True
                    self.audit.log(
                        "video_started",
                        mission_id=mission.mission_id,
                        waypoint_index=mission.index,
                    )
                mission.phase = "advance"
            elif action == "video_stop":
                if self.video_recording:
                    self.video_recording = False
                    self.audit.log(
                        "video_stopped",
                        mission_id=mission.mission_id,
                        waypoint_index=mission.index,
                    )
                mission.phase = "advance"
            else:
                mission.phase = "advance"
            return

        if mission.phase == "advance":
            mission.index += 1
            if mission.index >= len(waypoints):
                self._complete_mission(mission)
                return
            # 连续 photo 航点之间按 photo_interval_s 约束间隔
            mission.phase = "travel"
            return

    def _complete_mission(self, mission: MissionRuntime) -> None:
        if mission.state == "executing":
            mission.state = "completed"
            mission.ended_at = now_iso()
            self.audit.log(
                "mission_completed",
                mission_id=mission.mission_id,
                n_photos=len(mission.photos),
                distance_m=round(mission.distance_m, 2),
                duration_s=round(mission.sim_elapsed, 2),
            )
        self.mission = None
        self.state = "hovering"
        self.speed_mps = 0.0
        self.vertical_speed_mps = 0.0

    # -------------------------------------------------------------- 拍照
    def _record_photo(self, source: str) -> dict:
        if source == "mission" and self.mission is not None:
            mission = self.mission
            origin = mission.mission.get("origin_wgs84") or self.origin
            index = len(mission.photos)
            filename = "SIM_%04d.jpg" % (index + 1)
            photo = self._photo_payload(index, filename, origin)
            mission.photos.append(photo)
            mission.last_photo_sim_time = self.sim_time_s
            self.audit.log(
                "photo_captured",
                mission_id=mission.mission_id,
                index=index,
                file=filename,
                lat=photo["lat"],
                lon=photo["lon"],
                alt_rel_m=photo["alt_rel_m"],
                heading_deg=photo["heading_deg"],
                source=source,
            )
            return photo
        self.capture_seq += 1
        index = self.capture_seq - 1
        filename = "SIMCAP_%04d.jpg" % self.capture_seq
        photo = self._photo_payload(index, filename, self.origin)
        photo["mission_id"] = None
        if len(self.capture_photos) >= int(self.config.max_photo_records):
            self.capture_photos.pop(0)
        self.capture_photos.append(photo)
        self.audit.log(
            "photo_captured",
            mission_id=None,
            index=index,
            file=filename,
            lat=photo["lat"],
            lon=photo["lon"],
            alt_rel_m=photo["alt_rel_m"],
            heading_deg=photo["heading_deg"],
            source=source,
        )
        return photo

    def _photo_payload(self, index: int, filename: str, origin: dict) -> dict:
        alt_abs = float(self.alt_abs_m)
        c2w = geo.camera_c2w_from_pose(
            self.lat,
            self.lon,
            alt_abs,
            float(self.heading_deg),
            float(self.gimbal["pitch"]),
            origin=origin,
        )
        return {
            "index": int(index),
            "file": filename,
            "ts": now_iso(),
            "lat": round(self.lat, 7),
            "lon": round(self.lon, 7),
            "alt_rel_m": round(alt_abs - float(self.home["alt_abs_m"]), 3),
            "alt_abs_m": round(alt_abs, 3),
            "heading_deg": round(float(self.heading_deg) % 360.0, 3),
            "gimbal": {
                "pitch": round(self.gimbal["pitch"], 3),
                "yaw": round(self.gimbal["yaw"], 3),
                "roll": round(self.gimbal["roll"], 3),
            },
            "c2w": [round(float(value), 6) for value in c2w],
        }

    def _take_mission_photo(self, mission: MissionRuntime) -> None:
        self._record_photo(source="mission")

    def _tick_photo_burst(self) -> None:
        burst = self.photo_burst
        if not burst:
            return
        if self.state == "idle":
            self.photo_burst = None
            return
        if self.sim_time_s + 1e-9 >= burst["next_t"]:
            self._record_photo(source="capture")
            burst["remaining"] -= 1
            burst["next_t"] = burst["next_t"] + burst["interval"]
            if burst["remaining"] <= 0:
                self.photo_burst = None

    # ================================================================ §7.3 导出
    def mission_photos_metadata(self, mission_id: str, dataset: str = "synthetic_dji_mini4pro_mission_v1") -> dict:
        """把 §7.1 mission record 转成 §7.3 metadata.json（仿真记录版）。"""
        from .export import mission_record_to_metadata

        record = self.get_mission(mission_id)
        if record is None:
            raise SimulatorError("E_MISSION_NOT_FOUND", "mission_id 不存在: %s" % mission_id)
        mission_def = None
        runtime = self.missions.get(str(mission_id))
        if runtime is not None:
            mission_def = runtime.mission
        return mission_record_to_metadata(record, mission_def, dataset=dataset)
