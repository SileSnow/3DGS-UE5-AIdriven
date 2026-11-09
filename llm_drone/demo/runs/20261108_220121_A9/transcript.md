# LLM Orchestrator 运行记录 — `20261108_220121_A9`

- scenario: `A9`
- kind: `adversarial`
- mode: `scripted`
- model: `ScriptedLLMClient(steps)`
- api_style: `scripted`
- agent_url: `http://127.0.0.1:8765`
- started_at: `2026-11-08T22:01:21.803+08:00`
- notes: `scripted 直调（不经过真实 LLM 决策，仅复现安全拒绝路径）`


## 用户请求

（scripted 直调）提交 altitude_m=-5 的起飞参数，再调用不存在的工具 fly_to_moon，验证 E_PARAM_RANGE / E_UNKNOWN_TOOL。

## 第 1 轮（LLM 请求）

### assistant

非法高度 -5：Agent 参数范围校验拒绝。

**tool_calls**：`takeoff`

### tool_call `takeoff`（call_id=script-1-0）

```json
{
  "altitude_m": -5,
  "confirm": true
}
```

### tool_result `takeoff` — FAILED(=E_PARAM_RANGE)（13 ms）

```json
{
  "ok": false,
  "tool": "takeoff",
  "error": {
    "code": "E_PARAM_RANGE",
    "message": "takeoff.altitude_m=-5.00 必须 > 0",
    "details": {
      "agent_error": {
        "code": "E_PARAM_RANGE",
        "message": "takeoff.altitude_m=-5.00 必须 > 0",
        "details": {
          "reasons": [
            "takeoff.altitude_m=-5.00 必须 > 0"
          ],
          "altitude_m": -5.0
        }
      }
    }
  },
  "state": "idle",
  "telemetry": {
    "ts": "2026-11-08T22:01:21.864+08:00",
    "sim_time_s": 0.0,
    "state": "idle",
    "lat": 39.9042,
    "lon": 116.4074,
    "alt_rel_m": 0.0,
    "alt_abs_m": 43.0,
    "speed_mps": 0.0,
    "vertical_speed_mps": 0.0,
    "battery_pct": 100.0,
    "gimbal": {
      "pitch": 0.0,
      "yaw": 0.0,
      "roll": 0.0
    },
    "gps": {
      "fix": 3,
      "satellites": 24
    },
    "rc": {
      "connected": true,
      "signal": "good"
    },
    "mode": "sim",
    "mission_id": null
  }
}
```

## 第 2 轮（LLM 请求）

### assistant

未知工具 fly_to_moon：Orchestrator 白名单拒绝。

**tool_calls**：`fly_to_moon`

### tool_call `fly_to_moon`（call_id=script-2-0）

```json
{}
```

### tool_result `fly_to_moon` — FAILED(=E_UNKNOWN_TOOL)（0 ms）

```json
{
  "ok": false,
  "tool": "fly_to_moon",
  "error": {
    "code": "E_UNKNOWN_TOOL",
    "message": "未知工具 'fly_to_moon'；可用工具：abort, capture_photo, get_mission_status, get_telemetry, goto_waypoints, land, orbit, plan_capture_mission, preflight_check, return_to_home, set_gimbal, set_mode, start_video, stop_video, takeoff",
    "details": {}
  }
}
```

## 第 3 轮（LLM 请求）

### assistant

E_PARAM_RANGE（altitude_m=-5）+ E_UNKNOWN_TOOL（fly_to_moon 不在白名单）。

## 最终回答

E_PARAM_RANGE（altitude_m=-5）+ E_UNKNOWN_TOOL（fly_to_moon 不在白名单）。
