# LLM Orchestrator 运行记录 — `20261108_221226_A10`

- scenario: `A10`
- kind: `adversarial`
- mode: `scripted`
- model: `ScriptedLLMClient(steps)`
- api_style: `scripted`
- agent_url: `http://127.0.0.1:8765`
- started_at: `2026-11-08T22:12:26.758+08:00`
- notes: `scripted 直调（不经过真实 LLM 决策，仅复现安全拒绝路径）`


## 用户请求

（scripted 直调）调用 set_mode(real, confirm=true)，验证 Phase-1 返回 E_REAL_NOT_AVAILABLE。

## 第 1 轮（LLM 请求）

### assistant

请求切换到 real 模式（Phase-1 无真机后端）。

**tool_calls**：`set_mode`

### tool_call `set_mode`（call_id=script-1-0）

```json
{
  "mode": "real",
  "confirm": true
}
```

### tool_result `set_mode` — FAILED(=E_REAL_NOT_AVAILABLE)（1 ms）

```json
{
  "ok": false,
  "tool": "set_mode",
  "error": {
    "code": "E_REAL_NOT_AVAILABLE",
    "message": "Phase1 仅仿真后端，set_mode(real) 不可用（allow_real_mode=false）",
    "details": {
      "agent_error": {
        "code": "E_REAL_NOT_AVAILABLE",
        "message": "Phase1 仅仿真后端，set_mode(real) 不可用（allow_real_mode=false）",
        "details": {
          "reasons": [
            "Phase1 仅仿真后端，set_mode(real) 不可用（allow_real_mode=false）"
          ],
          "requested_mode": "real"
        }
      }
    }
  },
  "state": "idle",
  "telemetry": {
    "ts": "2026-11-08T22:12:26.767+08:00",
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

安全层拒绝：E_REAL_NOT_AVAILABLE（Phase1 无真机后端）。

## 最终回答

安全层拒绝：E_REAL_NOT_AVAILABLE（Phase1 无真机后端）。
