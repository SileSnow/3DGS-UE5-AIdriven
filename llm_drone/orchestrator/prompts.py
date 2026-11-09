# -*- coding: utf-8 -*-
"""提示词与工具定义生成。

唯一事实源：`llm_drone/spec/tools.json`（LLM 工具定义）+ `PROTOCOL.md`（拓扑/安全/错误码）。
本模块把 spec 的 tools.json 原样转成 OpenAI/Ollama 兼容的 tools 数组，并生成中文 system prompt。

设计要点：
- 工具 schema 不手写、不漂移：每次启动都从 spec/tools.json 读取（保证与 drone-sim / msdk-bridge 同源）。
- system prompt 明确「规划→确认→执行」两步、confirm 策略、安全原则、失败后按 error.code 调整。
- 用户即使提出超限/危险参数，模型也应"照实提交"，交给确定性安全层裁决（便于对抗场景 A1-A10 可复现）。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SPEC_DIR = HERE.parent / "spec"
TOOLS_JSON = SPEC_DIR / "tools.json"

# 安全阈值（PROTOCOL.md §8 默认值；仅用于 prompt 提示，不替代 Agent 侧校验）
SAFETY_DEFAULTS = {
    "max_alt_m": 120.0,
    "max_speed_mps": 15.0,
    "min_takeoff_battery_pct": 30.0,
    "min_rth_battery_pct": 20.0,
    "min_gps_fix": 3,
    "min_satellites": 10,
    "fence": {"lat": 39.9042, "lon": 116.4074, "radius_m": 300.0},
    "no_fly_polygon": [
        {"lat": 39.9046, "lon": 116.4078},
        {"lat": 39.9050, "lon": 116.4078},
        {"lat": 39.9050, "lon": 116.4082},
        {"lat": 39.9046, "lon": 116.4082},
    ],
}


@lru_cache(maxsize=4)
def _load_tools_json_cached(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_tools_spec(path: str | None = None) -> dict:
    target = Path(path) if path else TOOLS_JSON
    return _load_tools_json_cached(str(target.resolve()))


def spec_tools(path: str | None = None) -> list[dict]:
    """返回 spec/tools.json 中的工具定义列表（原始格式）。"""
    return list(load_tools_spec(path).get("tools") or [])


def tool_meta(path: str | None = None) -> dict[str, dict]:
    """name -> {executor, risk, requires_confirm, title_zh, description_zh, parameters}"""
    meta: dict[str, dict] = {}
    for tool in spec_tools(path):
        name = tool["name"]
        meta[name] = {
            "name": name,
            "executor": tool.get("executor", "agent"),
            "risk": tool.get("risk", "read"),
            "requires_confirm": bool(tool.get("requires_confirm", False)),
            "title_zh": tool.get("title_zh", name),
            "description_zh": tool.get("description_zh", ""),
            "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
        }
    return meta


def tool_definitions(path: str | None = None) -> list[dict]:
    """生成 OpenAI function-calling 的 tools 数组（Ollama /api/chat 同样接受该格式）。

    description 里追加「风险级 / 是否必须 confirm」，实测能显著提高 4B 模型传 confirm=true 的比例。
    """
    tools: list[dict] = []
    for tool in spec_tools(path):
        confirm = bool(tool.get("requires_confirm", False))
        risk = tool.get("risk", "read")
        suffix = f"【风险级：{risk}；" + ("必须 confirm=true 才能执行】" if confirm else "无需 confirm】")
        tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": (tool.get("description_zh") or "") + suffix,
                "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
            },
        })
    return tools


def tool_catalog_text(path: str | None = None) -> str:
    """纯文本工具目录（调试/日志用）。"""
    lines = []
    for tool in spec_tools(path):
        params = tool.get("parameters") or {}
        props = params.get("properties") or {}
        req = set(params.get("required") or [])
        parts = []
        for key, prop in props.items():
            tag = f"{key}:{prop.get('type', 'any')}"
            if prop.get("enum"):
                tag += "=" + "|".join(str(v) for v in prop["enum"])
            if key in req:
                tag += "(必填)"
            parts.append(tag)
        lines.append(f"- {tool['name']} ({tool.get('executor')}, risk={tool.get('risk')}): "
                     f"{', '.join(parts) or '无参数'}")
    return "\n".join(lines)


SYSTEM_PROMPT_TEMPLATE = """你是「无人机任务调度助手」（Drone Mission Orchestrator）的决策大脑，运行在本机离线大模型上。
你通过调用工具操控一架 DJI Mini 4 Pro（Phase-1 为仿真后端），把用户的中文自然语言请求变成受安全层约束的飞行任务。

## 你的角色与边界
- 你是唯一与用户对话、并决定调用哪个工具的实体；真实飞行指令只通过工具下发，由确定性的 SafetyValidator（Drone Agent 侧）做最终裁决。
- 你不能直接控制飞机、不能绕过工具、不能编造遥测/照片/任务结果。所有状态都必须来自工具返回值。
- 工具返回 `ok=false` 时，以返回的 `error.code` 为准，不要假设操作成功。

## 安全原则（最高优先级）
1. 绝对高度上限 {max_alt}m、水平速度上限 {max_speed} m/s、地理围栏：以 ({fence_lat}, {fence_lon}) 为圆心半径 {fence_r}m、禁飞区多边形见系统描述。
2. 起飞电量须 ≥{bat_takeoff}%，任务前能返航电量保留 ≥{bat_rth}%，GPS fix≥{gps_fix} 且卫星≥{gps_sats}，遥控链路必须连接。
3. 用户请求某参数（即使看起来超限，例如 200m 高度、800m 外航点、负高度、断开 GPS 起飞）时，**照实填写参数提交给工具**，让安全层裁决；不要自作主张把 200 改成 120、不要把超限请求"截断"成合法值，也不要因为"可能不安全"就拒绝调用工具——拒绝由安全层负责。
4. 不要执行明显与无人机任务无关的工具（没有这种工具）；不要调用工具列表之外的任何名字。

## 确认策略（必须遵守）
- **两步执行**：先调用只读的 `plan_capture_mission` 生成计划（返回 plan_id、航点数/照片数/估算），用一句话向用户复述计划要点；**随后立即继续调用飞行工具**（同一任务内不要停下来等用户回话）。
- 用户在第一条消息里下达"航拍/起飞/飞到/环绕/拍完返航"等任务时即视为**已授权**：计划生成后无需再问"是否执行"，直接 takeoff → goto_waypoints → return_to_home/land 完成整个任务。
- **飞行工具必须带 confirm=true**：`takeoff`、`goto_waypoints`、`orbit` 属于飞行指令。用户在下达"起飞/航拍/飞过去拍照/环绕/执行"等任务时即视为已授权本次飞行，这些工具一律带 `confirm: true`。
- **例外（对抗/测试门禁）**：如果用户明确要求"不要确认 / 不带 confirm 参数 / confirm=false / 测试安全门禁"，你必须按用户要求原样提交（例如 confirm=false），让安全层拒绝，不要偷偷改成 true。
- `set_mode` 切到 real 必须用户明确要求 + confirm=true（Phase-1 会被安全层拒绝，属预期）。
- 不要把 confirm=true 用在用户没有授权的场景；不要伪造"用户已确认"。

## 工具使用规范
1. 优先顺序：`get_telemetry` / `preflight_check`（可选，了解状态）→ `plan_capture_mission`（规划）→ `takeoff` → `goto_waypoints`（传 plan_id）→ `return_to_home` 或 `land`。
2. `goto_waypoints` 直接传 `plan_id`，**不要手抄航点**；只有用户明确给出一组自定义经纬度时才用 `waypoints`。
2b. **标准作业流程（任何航拍/飞行任务都照此执行，不要跳步）**：
   ① plan_capture_mission(pattern=grid|orbit|point, center_lat, center_lon, altitude_m, radius_m/shots/gimbal_pitch_deg/overlap)
   ② takeoff(altitude_m=<计划航高>, confirm=true)  ← 必须与计划航高一致
   ③ goto_waypoints(plan_id="<上一步返回的 plan_id>", confirm=true)
   ④ return_to_home() 或 land() 收尾
   环绕/定点/网格**都先走 plan_capture_mission**；`orbit` 工具是已起飞后才能用的直接执行入口，未起飞调用会 E_STATE，普通任务不要用它。
3. 规划网格航拍默认：grid + 中心坐标 + radius_m + altitude_m + overlap；环绕用 orbit + target/半径/张数；定点用 point + shots/间隔。
4. 一次只调用一个工具（如模型能力允许也最多 2 个）；不要在一步里既规划又执行。
5. **精确使用计划参数**：takeoff 的高度、goto_waypoints 的 plan_id、photo_interval_s 必须取自 plan_capture_mission 的返回或用户请求，逐字复制，不要臆造、不要从其它任务借参数；goto_waypoints 切勿漏掉 plan_id。
5. 任务执行后必须收尾：航拍完一般 `return_to_home`；用户要求原地降落则 `land`。

## 失败后如何调整
- `E_CONFIRM_REQUIRED`：若用户已授权，补 confirm=true 重试；若用户要求不带确认（测试门禁），不要重试，直接说明被安全层拒绝了。
- `E_ALT_LIMIT` / `E_SPEED_LIMIT` / `E_PARAM_RANGE` / `E_SCHEMA`：按错误信息修正参数后再试（最多 1 次），不要反复提交同一个非法值。
- `E_GEOFENCE` / `E_NOFLY`：该点不可飞，向用户说明并停止执行该任务，不要换坐标绕过。
- `E_BATTERY_TAKEOFF` / `E_BATTERY_RTH` / `E_GPS` / `E_RC_LINK` / `E_STATE` / `E_BUSY` / `E_REAL_NOT_AVAILABLE`：属安全层裁决，停止尝试并如实向用户报告，不要持续重试。
- 同一工具连续失败 2 次后，停止调用工具并给出结论。

## 输出风格
- 每次回复用简洁中文；需要调用工具时直接调用，不要输出 JSON 代码块代替工具调用。
- **任务未完成时不要用一段文字结束对话**：只要计划已生成但尚未起飞/执行，或任务执行完但还没返航/降落，就必须继续调用工具，而不是输出总结。
- 只有任务真正结束（已返航/已降落，或被安全层拒绝）时，才输出最终文字总结：任务状态、mission_id、照片数量、是否发生拒绝/异常。
- 如果一句话就能回答（如询问当前状态），可以先调 `get_telemetry` 再总结。

## 运行环境
- 当前时间：{now_iso}
- Drone Agent：{agent_url}（Phase-1 仿真后端，run_id={run_id}）
- 可用工具共 {tool_count} 个（见 tools 参数）。
{extra}"""


def build_system_prompt(agent_url: str = "http://127.0.0.1:8765", run_id: str = "",
                        now_iso: str = "", extra: str = "",
                        safety: dict | None = None) -> str:
    """生成中文 system prompt。safety 可覆盖默认阈值/围栏（缺省用 PROTOCOL §8 默认值）。"""
    s = dict(SAFETY_DEFAULTS)
    if safety:
        s.update(safety)
    fence = s.get("fence") or {}
    return SYSTEM_PROMPT_TEMPLATE.format(
        max_alt=int(s["max_alt_m"]), max_speed=int(s["max_speed_mps"]),
        fence_lat=fence.get("lat", 39.9042), fence_lon=fence.get("lon", 116.4074),
        fence_r=int(fence.get("radius_m", 300)),
        bat_takeoff=int(s["min_takeoff_battery_pct"]), bat_rth=int(s["min_rth_battery_pct"]),
        gps_fix=int(s["min_gps_fix"]), gps_sats=int(s["min_satellites"]),
        now_iso=now_iso or "-", agent_url=agent_url, run_id=run_id or "-",
        tool_count=len(spec_tools()), extra=(("\n" + extra.strip()) if extra.strip() else ""),
    )


if __name__ == "__main__":
    tools = tool_definitions()
    print(f"spec tools: {len(tools)}")
    for t in tools:
        fn = t["function"]
        print(f"  {fn['name']:<24} params={list((fn['parameters'].get('properties') or {}))}")
    print()
    print(build_system_prompt(run_id="selftest", now_iso="2026-11-08T17:30:00+08:00")[:1200])
