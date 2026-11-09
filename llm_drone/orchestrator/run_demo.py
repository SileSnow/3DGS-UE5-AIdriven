# -*- coding: utf-8 -*-
"""演示运行 CLI（PROTOCOL.md §11/§12）：真实 drone-sim Agent + 真实本地 LLM。

每个场景：
  GET /v1/health → POST /v1/reset(run_id) → POST /v1/sim/config（场景故障注入）
  → LLM 工具调用循环（或 --scripted 预置序列）→ 采集 mission/photos → 拷 Agent 审计
  → 写 llm_drone/demo/runs/<run_id>/ 全部文件（request/transcript/llm_events/tool_calls/
    agent_audit/mission/mission_record/photos_metadata/metrics/summary）。

用法：
  python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario all --out demo/runs
  python -m orchestrator.run_demo --scenario P1 --model qwen3.5:4b
  python -m orchestrator.run_demo --scenario A6 --scripted-for A6
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LLM_DRONE = HERE.parent
REPO_ROOT = LLM_DRONE.parent
if str(LLM_DRONE) not in sys.path:
    sys.path.insert(0, str(LLM_DRONE))

try:  # 包内导入
    from . import agent_client, audit as audit_mod, llm_client, planner, prompts, tools_runtime
    from .orchestrator import Orchestrator
except ImportError:  # 脚本/模块直跑
    import agent_client  # type: ignore
    import audit as audit_mod  # type: ignore
    import llm_client  # type: ignore
    import planner  # type: ignore
    import prompts  # type: ignore
    import tools_runtime  # type: ignore
    from orchestrator import Orchestrator  # type: ignore

CST = timezone(timedelta(hours=8))
SCENARIOS_PATH = LLM_DRONE / "demo" / "scenarios.json"
DEFAULT_OUT = LLM_DRONE / "demo" / "runs"
DEFAULT_SUMMARY = LLM_DRONE / "logs" / "orchestrator" / "SUMMARY.md"
AGENT_AUDIT_DIRS = (LLM_DRONE / "logs" / "drone-sim", LLM_DRONE / "logs")


# ---- 场景加载 ---------------------------------------------------------------
def load_scenarios(path: Path | str = SCENARIOS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    scenarios = data.get("scenarios") or []
    return {item["id"]: item for item in scenarios}


def expand_scenario_ids(token: str, scenarios: dict) -> list[str]:
    ids: list[str] = []
    for raw in str(token).split(","):
        raw = raw.strip()
        if not raw:
            continue
        if raw.lower() == "all":
            ids.extend([sid for sid in scenarios])
        elif raw.lower().startswith("p"):
            ids.append(raw.upper())
        elif raw.lower().startswith("a"):
            ids.append(raw.upper())
        else:
            ids.append(raw)
    seen, out = set(), []
    for sid in ids:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def now_cst() -> datetime:
    return datetime.now(CST)


def make_run_id(scenario_id: str) -> str:
    return now_cst().strftime("%Y%m%d_%H%M%S") + "_" + scenario_id


# ---- 文件写入 ---------------------------------------------------------------
def write_request_md(run_dir: Path, scenario: dict, meta: dict) -> None:
    lines = [f"# {scenario['id']} — {scenario.get('title', '')}", "",
             f"- scenario_id: `{scenario['id']}`",
             f"- kind: `{scenario.get('kind', '')}`",
             f"- run_id: `{meta['run_id']}`",
             f"- mode: `{meta['mode']}`（real_llm=真实 LLM；scripted=预置工具序列直调）",
             f"- model: `{meta.get('model')}`",
             f"- base_url: `{meta.get('base_url')}`",
             f"- api_style: `{meta.get('api_style')}`",
             f"- agent_url: `{meta.get('agent_url')}`",
             f"- started_at: `{meta.get('started_at')}`", "",
             "## 用户提示（发给 LLM 的 user message）", "", "```text",
             scenario.get("prompt", "").strip(), "```", ""]
    if scenario.get("sim_setup"):
        lines += ["## 仿真配置注入（/v1/sim/config）", "", "```json",
                  json.dumps(scenario["sim_setup"], ensure_ascii=False, indent=2), "```", ""]
    if scenario.get("expected_tools") or scenario.get("expected_error_code"):
        lines += ["## 期望（PROTOCOL.md §11）", "",
                  f"- expected_tools: `{scenario.get('expected_tools')}`",
                  f"- expected_error_code: `{scenario.get('expected_error_code')}`",
                  f"- expect_photos: `{scenario.get('expect_photos')}`",
                  f"- expect_mission_state: `{scenario.get('expect_mission_state')}`", ""]
    if meta.get("notes"):
        lines += ["## 备注", "", meta["notes"], ""]
    (run_dir / "request.md").write_text("\n".join(lines), encoding="utf-8")


def photos_metadata(record: dict, mission: dict) -> dict:
    """spec §7.3 metadata.json（仿真记录版，无真实图像）。"""
    camera = (mission or {}).get("camera") or planner.CAMERA
    origin = (mission or {}).get("origin_wgs84") or dict(planner.ORIGIN_WGS84)
    frames = []
    record = record or {}
    for photo in record.get("photos") or []:
        if not isinstance(photo, dict):
            continue
        gimbal = photo.get("gimbal") or {}
        frames.append({
            "file": photo.get("file"),
            "c2w": photo.get("c2w") or [],
            "gps": {"lat": photo.get("lat"), "lon": photo.get("lon"),
                    "alt": photo.get("alt_abs_m")},
            "gimbal_deg": {"yaw": gimbal.get("yaw", 0.0), "pitch": gimbal.get("pitch", 0.0),
                           "roll": gimbal.get("roll", 0.0)},
            "timestamp": photo.get("t_s", photo.get("timestamp", photo.get("index", 0))),
            "mission": {"mission_id": record.get("mission_id"),
                        "waypoint_index": photo.get("index")},
        })
    return {
        "dataset": "synthetic_dji_mini4pro_mission_v1",
        "camera_model": camera.get("model", "DJI Mini 4 Pro (simulated)"),
        "width": camera.get("width", 1600), "height": camera.get("height", 1200),
        "fx": camera.get("fx", 1148.343), "fy": camera.get("fy", 1148.343),
        "cx": camera.get("cx", 800.0), "cy": camera.get("cy", 600.0),
        "coord_system": "UE_LHS_Zup_cm",
        "origin_wgs84": origin,
        "source": "sim_record",
        "frames": frames,
    }


def copy_agent_audit(run_dir: Path, run_id: str, client) -> dict:
    candidates = []
    for folder in AGENT_AUDIT_DIRS:
        candidates.extend([folder / f"audit_{run_id}.jsonl", folder / f"audit_{run_id}.log"])
    for path in candidates:
        if path.is_file():
            shutil.copyfile(path, run_dir / "agent_audit.jsonl")
            return {"source": "file", "path": str(path), "bytes": path.stat().st_size}
    # 回退：/v1/audit
    for endpoint in ("/v1/audit", "/v1/audit/events"):
        resp = client._request("GET", endpoint + "?since_seq=0")
        events = resp.get("events") if isinstance(resp, dict) else None
        if isinstance(events, list) and events:
            with open(run_dir / "agent_audit.jsonl", "w", encoding="utf-8") as fh:
                for event in events:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            return {"source": "endpoint", "endpoint": endpoint, "events": len(events)}
    (run_dir / "agent_audit.jsonl").write_text("", encoding="utf-8")
    return {"source": "missing", "note": "未找到 Agent 审计文件（run_id 可能未被 sim 使用）"}


# ---- 判定 -------------------------------------------------------------------
def _photo_expectation(expect_photos) -> tuple:
    if expect_photos is None:
        return None, None
    if isinstance(expect_photos, int):
        return "exact", int(expect_photos)
    if isinstance(expect_photos, dict):
        if "exact" in expect_photos:
            return "exact", int(expect_photos["exact"])
        if "min" in expect_photos:
            return "min", int(expect_photos["min"])
    if isinstance(expect_photos, str):
        text = expect_photos.strip()
        if text.startswith(">="):
            return "min", int(text[2:])
        if text.isdigit():
            return "exact", int(text)
    return None, None


def _expected_codes(scenario: dict) -> list:
    raw = scenario.get("expected_error_code")
    if raw is None:
        raw = scenario.get("expected_error_codes")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw]


def judge_scenario(scenario: dict, summary: dict, counters: dict, record: dict,
                   final_telemetry: dict, agent_audit_text: str) -> tuple:
    checks: list[dict] = []
    sequence = [item.get("name") for item in summary.get("tool_sequence") or []]
    outcome_mode = scenario.get("pass_mode") == "outcome"
    for tool in scenario.get("expected_tools") or []:
        checks.append({"check": f"tool:{tool}", "passed": tool in sequence,
                       "detail": f"actual_sequence={sequence}",
                       "informational": outcome_mode})
    codes = list(counters.get("error_codes") or [])
    for code in _expected_codes(scenario):
        checks.append({"check": f"error_code:{code}", "passed": code in codes,
                       "detail": f"actual={codes}"})
    mode, value = _photo_expectation(scenario.get("expect_photos"))
    n_photos = int(record.get("stats", {}).get("n_photos")
                   or len(record.get("photos") or []) or 0)
    if mode == "exact":
        checks.append({"check": f"photos=={value}", "passed": n_photos == value,
                       "detail": f"actual={n_photos}"})
    elif mode == "min":
        checks.append({"check": f"photos>={value}", "passed": n_photos >= value,
                       "detail": f"actual={n_photos}"})
    expect_state = scenario.get("expect_mission_state")
    if expect_state:
        actual_state = record.get("state")
        if isinstance(expect_state, list):
            ok = actual_state in expect_state
        elif expect_state == "completed":
            ok = actual_state == "completed"
        else:
            ok = actual_state == expect_state
        checks.append({"check": f"mission_state:{expect_state}", "passed": ok,
                       "detail": f"actual={actual_state}"})
    if scenario.get("expect_no_rejection"):
        rejected = int(counters.get("rejected") or 0)
        checks.append({"check": "no_rejection", "passed": rejected == 0,
                       "detail": f"rejected={rejected}"})
    if scenario.get("expect_force_rth"):
        seen = "force_rth" in (agent_audit_text or "")
        checks.append({"check": "agent_audit:force_rth", "passed": seen, "detail": ""})
    expect_final = scenario.get("expect_final_state")
    if expect_final:
        final_state = (final_telemetry or {}).get("state")
        expected = expect_final if isinstance(expect_final, list) else [expect_final]
        checks.append({"check": f"final_state:{expected}", "passed": final_state in expected,
                       "detail": f"actual={final_state}"})
    # outcome 模式：以"任务结果"判定（照片数/状态/最终落地），工具序列只作信息记录；
    # 若中途出现安全拒绝但随后由模型自行纠正并完成任务，仍视为通过（写进 summary 说明）。
    if outcome_mode and (checks or True):
        rejected = int(counters.get("rejected") or 0)
        completed = (record or {}).get("state") == "completed"
        if rejected and completed:
            checks.append({"check": "self_corrected_after_rejection", "passed": True,
                           "detail": f"rejected={rejected} -> 后续 LLM 自纠错完成任务"})
    decisive = [item for item in checks if not item.get("informational")]
    passed = all(item["passed"] for item in decisive) if decisive else True
    return passed, checks


# ---- 单场景运行 -------------------------------------------------------------
def run_scenario(scenario: dict, args, client, out_dir: Path) -> dict:
    sid = scenario["id"]
    run_id = make_run_id(sid)
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started_at = audit_mod.now_iso()
    scripted = (sid in (args.scripted_for or set())) or scenario.get("mode") == "scripted"
    mode = "scripted" if scripted else "real_llm"
    model = "ScriptedLLMClient(steps)" if scripted else args.model
    base_url = "" if scripted else args.base_url
    api_style = "scripted" if scripted else args.api_style
    meta = {"run_id": run_id, "scenario_id": sid, "kind": scenario.get("kind", ""),
            "mode": mode, "model": model, "base_url": base_url, "api_style": api_style,
            "agent_url": args.agent_url, "started_at": started_at,
            "sim_setup": scenario.get("sim_setup") or {},
            "notes": ("scripted 直调（不经过真实 LLM 决策，仅复现安全拒绝路径）"
                      if scripted else "真实 LLM（Ollama qwen3.5:4b）工具调用循环")}
    audit = audit_mod.RunAudit(run_dir, run_id, sid, meta)
    write_request_md(run_dir, scenario, meta)
    print(f"\n=== [{sid}] run_id={run_id} mode={mode} ===")

    # 1) 健康检查 + reset + 故障注入
    health = client.health()
    if health.get("ok") is False:
        print("  Agent 不可用：", json.dumps(health, ensure_ascii=False)[:300])
        audit.error("Agent 不可用", "E_AGENT_UNREACHABLE")
        audit.close({"passed": False})
        return {"run_id": run_id, "scenario_id": sid, "passed": False,
                "error": "agent_unreachable"}
    reset_resp = client.reset(run_id)
    sim_setup = scenario.get("sim_setup") or {}
    sim_resp = client.sim_config(sim_setup) if sim_setup else {"ok": True, "skipped": True}
    audit.event("sim_setup", reset=_short(reset_resp), sim_config=_short(sim_resp))

    # 2) LLM / scripted 客户端
    if scripted:
        steps = scenario.get("script") or []
        llm = llm_client.ScriptedLLMClient(steps, final_text=scenario.get("final_text", ""))
        llm_health = llm.health()
    else:
        try:
            llm = llm_client.build_llm_client(args.api_style, args.base_url, args.model,
                                              timeout=args.timeout, temperature=args.temperature,
                                              think=getattr(args, "think", True))
        except llm_client.LLMError as exc:
            print("  LLM 不可用：", exc)
            audit.error(f"LLM 不可用：{exc}", "LLM_UNAVAILABLE")
            audit.close({"passed": False})
            return {"run_id": run_id, "scenario_id": sid, "passed": False,
                    "error": "llm_unavailable"}
        llm_health = llm.health()
    audit.event("runtime_info", llm_health=_short(llm_health), scenario=sid)

    runtime = tools_runtime.ToolRuntime(
        client, run_id=run_id,
        wait_missions=bool(scenario.get("wait_missions", True)),
        mission_timeout_s=float(scenario.get("mission_timeout_s", 240.0)),
        state_timeout_s=float(scenario.get("state_timeout_s", 120.0)))
    orchestrator = Orchestrator(
        llm, runtime, audit, model=model, base_url=base_url, api_style=api_style,
        agent_url=args.agent_url, run_id=run_id, max_rounds=args.max_rounds, verbose=args.verbose,
        expected_tools=scenario.get("expected_tools") or [],
        kind=scenario.get("kind", ""))
    wall_started = time.time()
    error_text = ""
    try:
        summary = orchestrator.run(scenario.get("prompt", ""))
    except Exception as exc:  # noqa: BLE001 - 任何异常都要落 run 目录
        error_text = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        audit.error(error_text, "E_ORCHESTRATOR_EXCEPTION")
        summary = {"final_answer": f"（运行异常：{error_text}）", "rounds": 0,
                   "tool_sequence": [], "llm_context": {}}
    wall_s = round(time.time() - wall_started, 2)
    counters = audit.counters_summary()

    # 3) 采集 mission / photos / telemetry
    record: dict = {}
    try:
        record = runtime.latest_mission_record() or {}
    except Exception:  # noqa: BLE001
        record = {}
    mission = runtime.last_mission or {}
    if not mission:
        for plan in runtime.plans.values():
            candidate = plan.get("mission") or {}
            if candidate:
                mission = candidate
    if mission and not (run_dir / "mission.json").exists():
        (run_dir / "mission.json").write_text(
            json.dumps(mission, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        (run_dir / "mission.json").write_text("{}", encoding="utf-8")
    (run_dir / "mission_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "photos_metadata.json").write_text(
        json.dumps(photos_metadata(record, mission), ensure_ascii=False, indent=2), encoding="utf-8")
    final_telemetry = client.telemetry()
    if not isinstance(final_telemetry, dict) or final_telemetry.get("ok") is False:
        final_telemetry = {}
    agent_audit_info = copy_agent_audit(run_dir, run_id, client)
    agent_audit_text = (run_dir / "agent_audit.jsonl").read_text(encoding="utf-8", errors="replace") \
        if (run_dir / "agent_audit.jsonl").exists() else ""

    # 4) 判定 + metrics
    passed, checks = judge_scenario(scenario, summary, counters, record, final_telemetry,
                                    agent_audit_text)
    if error_text:
        passed = False
    n_photos = int(record.get("stats", {}).get("n_photos")
                   or len(record.get("photos") or []) or 0)
    mission_sim_s = (record.get("stats") or {}).get("duration_s")
    expected = {
        "expected_tools": scenario.get("expected_tools") or [],
        "expected_error_code": _expected_codes(scenario),
        "expect_photos": scenario.get("expect_photos"),
        "expect_mission_state": scenario.get("expect_mission_state"),
        "expect_no_rejection": bool(scenario.get("expect_no_rejection")),
        "expect_force_rth": bool(scenario.get("expect_force_rth")),
        "expect_final_state": scenario.get("expect_final_state"),
    }
    actual = {
        "mode": mode,
        "tools": [item.get("name") for item in summary.get("tool_sequence") or []],
        "error_codes": counters.get("error_codes") or [],
        "rejected": int(counters.get("rejected") or 0),
        "n_photos": n_photos,
        "mission_id": record.get("mission_id") or runtime.last_mission_id,
        "mission_state": record.get("state"),
        "final_state": final_telemetry.get("state"),
        "final_answer": (summary.get("final_answer") or "")[:1200],
        "checks": checks,
    }
    metrics = {
        "run_id": run_id,
        "scenario_id": sid,
        "kind": scenario.get("kind", ""),
        "model": model,
        "base_url": base_url,
        "mode": mode,
        "llm_calls": int(counters.get("llm_calls") or 0),
        "tool_calls": int(counters.get("tool_calls") or 0),
        "rejected": int(counters.get("rejected") or 0),
        "error_codes": counters.get("error_codes") or [],
        "wall_s": wall_s,
        "mission_sim_s": mission_sim_s,
        "n_photos": n_photos,
        "tokens": counters.get("tokens") or {"prompt": 0, "completion": 0},
        "passed": bool(passed),
        "expected": expected,
        "actual": actual,
        "agent_url": args.agent_url,
        "started_at": started_at,
        "finished_at": audit_mod.now_iso(),
        "inputs": {"sim_setup": sim_setup, "scripted": scripted},
        "agent_audit": agent_audit_info,
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    write_run_summary(run_dir, scenario, metrics, agent_audit_text)
    audit.close({"passed": bool(passed), "n_photos": n_photos})
    status = "PASS" if passed else "FAIL"
    print(f"  {status} n_photos={n_photos} rejected={metrics['rejected']} "
          f"codes={metrics['error_codes']} llm_calls={metrics['llm_calls']} "
          f"tool_calls={metrics['tool_calls']} wall={wall_s}s")
    return metrics


def _short(value, limit: int = 600):
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def write_run_summary(run_dir: Path, scenario: dict, metrics: dict, agent_audit_text: str) -> None:
    lines = [f"# {scenario['id']} 运行小结", "",
             f"- run_id: `{metrics['run_id']}`",
             f"- kind: `{metrics['kind']}`",
             f"- mode: `{metrics['mode']}`（model: `{metrics['model']}`）",
             f"- **结论: {'PASS ✅' if metrics['passed'] else 'FAIL ❌'}**", "",
             "## 期望 vs 实际", "", "| 项 | 期望 | 实际 | 判定 |", "|---|---|---|---|"]
    for check in (metrics["actual"].get("checks") or []):
        lines.append(f"| {check['check']} | - | {check['detail']} | "
                     f"{'PASS' if check['passed'] else 'FAIL'} |")
    lines += ["", "## 指标", "",
              f"- LLM 调用: {metrics['llm_calls']}；工具调用: {metrics['tool_calls']}；拒绝: {metrics['rejected']}",
              f"- 错误码: `{metrics['error_codes']}`",
              f"- 照片数: {metrics['n_photos']}；mission_sim_s: {metrics['mission_sim_s']}；"
              f"wall_s: {metrics['wall_s']}",
              f"- tokens: {metrics['tokens']}", "", "## 最终回答（节选）", "",
              "```text", (metrics["actual"].get("final_answer") or "")[:1500], "```", "",
              "## 证据文件", ""]
    for name in ("request.md", "transcript.md", "llm_events.jsonl", "tool_calls.jsonl",
                 "agent_audit.jsonl", "mission.json", "mission_record.json",
                 "photos_metadata.json", "metrics.json"):
        path = run_dir / name
        if path.exists():
            lines.append(f"- [{name}]({name}) — {path.stat().st_size} bytes")
    # Agent 审计拒绝行号
    reject_lines = []
    for lineno, line in enumerate(agent_audit_text.splitlines(), 1):
        if '"error_code"' in line or '"command_rejected"' in line or '"force_rth"' in line:
            reject_lines.append((lineno, line[:220]))
    if reject_lines:
        lines += ["", "## Agent 审计关键行（拒绝/强制返航）", ""]
        for lineno, line in reject_lines[:12]:
            lines.append(f"- agent_audit.jsonl:{lineno} — `{line}`")
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- 汇总表 -----------------------------------------------------------------
def update_summary_md(out_dir: Path, summary_path: Path = DEFAULT_SUMMARY) -> list[dict]:
    rows = []
    for metrics_path in sorted(out_dir.glob("*/metrics.json")):
        try:
            rows.append(json.loads(metrics_path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    if not rows:
        return []
    lines = ["# LLM Orchestrator 演示运行汇总（spec §11/§12）", "",
             f"- 生成时间: {audit_mod.now_iso()}",
             f"- 输出目录: `{out_dir}`",
             f"- 复现命令: `cd dji_ue5_3dgs/llm_drone && python -m sim.server --port 8765 --time-scale 20`（后台），"
             "然后 `python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario all --out demo/runs`",
             "", "| run_id | scenario | kind | mode | passed | n_photos | error_codes | "
             "llm_calls | tool_calls | rejected | wall_s |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append("| {run_id} | {scenario_id} | {kind} | {mode} | {passed} | {n_photos} | "
                     "{codes} | {llm_calls} | {tool_calls} | {rejected} | {wall_s} |".format(
                         run_id=row.get("run_id"), scenario_id=row.get("scenario_id"),
                         kind=row.get("kind"), mode=row.get("mode"),
                         passed="PASS ✅" if row.get("passed") else "FAIL ❌",
                         n_photos=row.get("n_photos"), codes=row.get("error_codes"),
                         llm_calls=row.get("llm_calls"), tool_calls=row.get("tool_calls"),
                         rejected=row.get("rejected"), wall_s=row.get("wall_s")))
    total = len(rows)
    passed = sum(1 for row in rows if row.get("passed"))
    lines += ["", f"**总计：{passed}/{total} PASS**", ""]
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


# ---- CLI --------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LLM Orchestrator 演示 run（spec §12）")
    parser.add_argument("--agent-url", default="http://127.0.0.1:8765")
    parser.add_argument("--scenario", default="all", help="all | P1 | P1,P2 | A1 | A6")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="run 输出根目录")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--api-style", default="ollama",
                        choices=["ollama", "openai", "auto", "json"])
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-rounds", type=int, default=12)
    parser.add_argument("--scripted-for", default="",
                        help="逗号分隔的场景 ID 使用 scripted 预置序列，如 A6,A7,A8,A9,A10")
    parser.add_argument("--think", dest="think", action="store_true", default=False,
                        help="Ollama 原生模式开启 think 思考链（默认关：4B 在 4k 上下文下会被思维链吞掉输出）")
    parser.add_argument("--no-think", dest="think", action="store_false",
                        help="关闭 think 思考链（默认）")
    parser.add_argument("--summary-out", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--list", action="store_true", help="仅列出场景")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    scenarios = load_scenarios()
    if args.list:
        for sid, scenario in scenarios.items():
            print(f"{sid:>3}  {scenario.get('kind'):<11} {scenario.get('title', '')}")
        return 0
    args.scripted_for = {item.strip().upper() for item in str(args.scripted_for).split(",")
                         if item.strip()}
    scenario_ids = expand_scenario_ids(args.scenario, scenarios)
    unknown = [sid for sid in scenario_ids if sid not in scenarios]
    if unknown:
        print(f"未知场景：{unknown}；可用：{list(scenarios)}")
        return 2
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = LLM_DRONE / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    client = agent_client.AgentClient(args.agent_url)
    health = client.health()
    if health.get("ok") is False:
        print(f"Agent 不可用（{args.agent_url}）：{json.dumps(health, ensure_ascii=False)[:400]}")
        print("请先启动：cd dji_ue5_3dgs/llm_drone && python -m sim.server --port 8765 --time-scale 20")
        return 2
    print(f"Agent OK：{json.dumps(health, ensure_ascii=False)[:300]}")

    results = []
    for sid in scenario_ids:
        scenario = scenarios[sid]
        try:
            metrics = run_scenario(scenario, args, client, out_dir)
        except Exception as exc:  # noqa: BLE001 - 继续跑其它场景
            traceback.print_exc()
            metrics = {"run_id": "", "scenario_id": sid, "passed": False,
                       "error": f"{type(exc).__name__}: {exc}"}
        results.append(metrics)
    rows = update_summary_md(out_dir, Path(args.summary_out))
    print("\n===== 汇总 =====")
    for row in rows or results:
        print(f"{row.get('run_id') or row.get('scenario_id'):<28} {row.get('scenario_id', ''):<4} "
              f"{'PASS' if row.get('passed') else 'FAIL':<5} photos={row.get('n_photos')} "
              f"codes={row.get('error_codes')}")
    print(f"\n汇总表：{Path(args.summary_out)}")
    passed = sum(1 for row in (rows or results) if row.get("passed"))
    return 0 if passed == len(rows or results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
