# llm_drone/safety —— SafetyValidator（确定性权威安全层）

> 工程规格唯一事实源：`llm_drone/spec/PROTOCOL.md` v1.0（FROZEN）§4/§8/§8.1/§8.2/§9.1。
> 本目录只做**确定性策略校验与审计**，不执行动作、不依赖网络、默认无副作用；
> Drone Agent（`llm_drone/sim/`）在每条命令执行前调用本层，**安全结论只认本层**。

## 1. 设计原则

1. **纯函数优先**：`validate_command()` / `preflight_checks()` / `estimate_mission_energy_pct()`
   只读输入，不改状态、不写审计；审计由调用方（Agent）根据返回值写入，保证校验可重复、可单测。
2. **顺序固定**（PROTOCOL.md §4）：
   `schema → whitelist → mode → confirm → state → battery → gps → rc → 高度/速度范围 →
   geofence → no-fly zone → 返航能量估算 → 允许`。
   任一失败立即拒绝并给出唯一 `error_code` + 若干 `reasons`；拒绝优于截断（不静默修改参数）。
3. **默认值 = 规格值，逐字对齐**（对抗测试用默认值，见 §3）。
4. **错误码逐字一致**（`safety/errors.py` 常量 + `ERROR_MESSAGES`，见 §5）。

实现细节（与规格兼容的解释）：

- 未知工具无法建立参数 schema（schema 依赖工具定义），因此白名单判定先于 schema，
  返回 `E_UNKNOWN_TOOL`（满足 §8 规则 10 与 §11.2 A9）。
- 规则 16（并发命令 `E_BUSY`）在 state 阶段最前判定：任务执行中仅允许
  `abort/get_telemetry/get_mission_status/return_to_home`。
- `E_NOT_AIRBORNE` 属于 state 阶段：`set_gimbal/capture_photo/start_video/stop_video` 在地面时返回。
- `mode` 阶段：`set_mode(real)` 且 `allow_real_mode=false` → `E_REAL_NOT_AVAILABLE`（先于 confirm 判定）。
- GPS/RC 规则按 §8 表只约束**起飞**（"拒绝起飞"）；空中任务不会因 GPS/RC 注入而中止（规格未要求）。

## 2. 目录

```
safety/
├── __init__.py    # 公开 API（SafetyValidator/SafetyConfig/AuditManager/...）
├── errors.py      # §8.2 错误码常量（逐字）+ 中文含义 + 状态/模式枚举
├── geo.py         # §2 坐标/几何纯函数（WGS84↔ENU↔UE cm、haversine、多边形、§7.2 c2w）
├── config.py      # SafetyConfig（默认值严格按 §8/§8.1）+ JSON 加载 + 兼容别名
├── schemas.py     # Agent 级 §4 JSON Schema + §6 Mission 校验/归一化 + 白名单
├── validator.py   # SafetyDecision / validate_command / preflight_checks / 能量估算 / SafetyValidator
├── audit.py       # §9.1 JSONL AuditLogger / AuditManager（run_id 切文件、seq 递增）
└── config.json    # 默认配置（阈值/围栏/禁飞区/能量参数；可用 --safety-config 覆盖）
```

## 3. 默认安全规则（PROTOCOL.md §8，**逐字默认值**）

| # | 规则 | 默认阈值 | 错误码 / 行为 |
|---|---|---|---|
| 1 | 最大相对高度 | 120 m | `E_ALT_LIMIT` 拒绝 |
| 2 | 最大水平速度 | 15 m/s | `E_SPEED_LIMIT` 拒绝 |
| 3 | 地理围栏（圆形） | 圆心 (39.9042,116.4074)，半径 300 m | `E_GEOFENCE` 拒绝 |
| 4 | 禁飞区（多边形，0-120m） | 见下 | `E_NOFLY` 拒绝 |
| 5 | 起飞最低电量 | 30% | `E_BATTERY_TAKEOFF` 拒绝 |
| 6 | 返航保留电量 | 20%（任务前能量估算不足则拒） | `E_BATTERY_RTH` 拒绝 |
| 7 | 飞行中低电量 | <20% | 强制 RTH（Agent 执行，审计 `force_rth` / decision=force_rth） |
| 8 | GPS 质量 | fix>=3 且 satellites>=10 | `E_GPS` 拒绝起飞 |
| 9 | 遥控链路 | 必须连接 | `E_RC_LINK` 拒绝起飞 |
| 10 | 指令白名单 | spec/tools.json + §4 命令表 | `E_UNKNOWN_TOOL` |
| 11 | JSON Schema + 物理范围 | §4/tools.json | `E_SCHEMA` / `E_PARAM_RANGE` |
| 12 | 二次确认 | takeoff/goto_waypoints/orbit/set_mode(real) | `E_CONFIRM_REQUIRED` |
| 13 | 状态合法性 | 如 idle 时 land、飞行中 takeoff | `E_STATE` |
| 14 | real 模式 | Phase1 未接入 | `E_REAL_NOT_AVAILABLE` |
| 15 | 审计 | 所有命令/拒绝/关键遥测 JSONL | 不可关闭 |
| 16 | 并发命令 | 任务中仅 abort/get_telemetry/get_mission_status/return_to_home | `E_BUSY` |
| — | 需要空中 | set_gimbal/capture_photo/start_video/stop_video | `E_NOT_AIRBORNE` |

默认禁飞区（§8.1，`config.json` 内逐字一致）：

```json
{"name":"default_no_fly","alt_range_m":[0,120],
 "polygon":[{"lat":39.9046,"lon":116.4078},{"lat":39.9050,"lon":116.4078},
            {"lat":39.9050,"lon":116.4082},{"lat":39.9046,"lon":116.4082}]}
```

## 4. 配置（`safety/config.json`）

`SafetyConfig` 字段：`max_alt_m, max_speed_mps, min_takeoff_battery_pct, rth_reserve_pct,
force_rth_pct, gps_min_fix, gps_min_satellites, require_rc, require_confirm_tools,
allow_real_mode, origin, geofence{type,center,radius_m}, no_fly_zones[], energy{...}`。

加载优先级：显式 `load_config(path=...)` > 环境变量 `LLM_DRONE_SAFETY_CONFIG` >
`safety/config.json` > 代码默认值。未知字段会抛 `ValueError`（防拼写错误），
非法阈值（如负半径）同样抛出。

能量估算模型（规则 6，与 §10 仿真电量模型一致）：
`cruise 0.05%/s、climb/descend 0.15%/s、hover 0.04%/s、climb/descend 3 m/s、RTH 10 m/s`，
`required_pct = 任务耗电 + 返航耗电 + 20% 保留`；`battery_pct < required_pct` → `E_BATTERY_RTH`。

## 5. 错误码（§8.2，逐字）

`E_SCHEMA, E_PARAM_RANGE, E_UNKNOWN_TOOL, E_CONFIRM_REQUIRED, E_MODE, E_STATE, E_BUSY,
E_ALT_LIMIT, E_SPEED_LIMIT, E_GEOFENCE, E_NOFLY, E_BATTERY_TAKEOFF, E_BATTERY_RTH, E_GPS,
E_RC_LINK, E_MISSION_NOT_FOUND, E_REAL_NOT_AVAILABLE, E_NOT_SUPPORTED, E_NOT_AIRBORNE, E_INTERNAL`

`E_MISSION_NOT_FOUND` 由 Agent 在查库时抛出；`E_NOT_SUPPORTED` 用于真机后端访问仿真专属端点。

## 6. API 示例

```python
from safety import SafetyValidator, load_config, geo
from safety.validator import nominal_state

cfg = load_config()                 # 默认值严格按 §8/§8.1
validator = SafetyValidator(cfg)

telemetry = nominal_state(state="idle", battery_pct=100.0)   # 测试用 §5 快照
decision = validator.validate(
    "takeoff", {"altitude_m": 40}, confirm=True, telemetry=telemetry
)
assert decision.allow is True

# 对抗：超限高
decision = validator.validate("takeoff", {"altitude_m": 200}, confirm=True, telemetry=telemetry)
assert decision.error_code == "E_ALT_LIMIT"
assert decision.reasons and decision.reasons[0].startswith("takeoff.altitude_m=200")

# 任务前能量估算
estimate = validator.estimate_energy(mission_json, telemetry)
print(estimate["required_pct"], estimate["feasible"])

# 起飞前检查
print(validator.preflight(telemetry))   # {"ok": True, "can_fly": ..., "checks":[...]}
```

审计（由 Agent 持有，但接口可独立使用）：

```python
from safety.audit import AuditManager
audit = AuditManager("llm_drone/logs/drone-sim", run_id="demo_001")
audit.log("command_received", tool="takeoff", command_id="c-0001", decision="pending")
audit.log("command_rejected", tool="takeoff", command_id="c-0002",
          error_code="E_ALT_LIMIT", reasons=["altitude_m=200 > 120"], decision="reject")
audit.switch_run("demo_002")        # 切换 audit_demo_002.jsonl
events = audit.read_events(since_seq=0)
```

## 7. 测试

```powershell
cd C:\Users\<user>\Desktop\GAIA项目\dji_ue5_3dgs\llm_drone
python -m unittest discover -s tests/safety -t tests -v   # 45 tests
```

覆盖：
- 默认值/错误码拼写/白名单 ⊆ tools.json（`DefaultsTest`）；
- A1-A10 逐条断言错误码（`AdversarialRulesTest`，纯函数）+ HTTP 集成（`tests/safety/test_integration.py`）；
- E_STATE / E_BUSY / E_NOT_AIRBORNE / 校验顺序（state 先于 geofence 等）；
- 能量估算（样例任务可行 / 8.4 km 往返任务 `E_BATTERY_RTH`）、preflight、§6 Mission 归一化；
- §7.2 c2w 公式逐元素断言 + 正交性 + §7.3 metadata 导出。
