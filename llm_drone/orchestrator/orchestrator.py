# -*- coding: utf-8 -*-
"""LLM 工具调用主循环（PROTOCOL.md §1 的①层）。"""
from __future__ import annotations

import argparse
import json
import time

try:
    from . import audit as audit_mod
    from . import llm_client, prompts
except ImportError:  # pragma: no cover
    import audit as audit_mod  # type: ignore
    import llm_client  # type: ignore
    import prompts  # type: ignore

DEFAULT_MAX_ROUNDS = 12
MAX_NUDGES = 4   # 阶段明确的续跑提醒（计划→起飞→执行→收尾），4B 模型多步执行需要外部状态驱动


class Orchestrator:
    """messages→LLM→tool_calls→执行→tool result→LLM…，直到最终回答或轮次上限。"""

    def __init__(self, llm, runtime, audit, model: str = "", base_url: str = "",
                 api_style: str = "ollama", agent_url: str = "", run_id: str = "",
                 max_rounds: int = DEFAULT_MAX_ROUNDS, system_prompt: str | None = None,
                 tools: list | None = None, verbose: bool = False,
                 expected_tools: list | None = None, kind: str = "") -> None:
        self.llm = llm
        self.runtime = runtime
        self.audit = audit
        self.model = model or getattr(llm, "model", "") or type(llm).__name__
        self.base_url = base_url or getattr(llm, "base_url", "")
        self.api_style = api_style or "ollama"
        self.agent_url = agent_url
        self.run_id = run_id
        self.max_rounds = max(1, int(max_rounds))
        self.tools = tools if tools is not None else prompts.tool_definitions()
        self.system_prompt = system_prompt or prompts.build_system_prompt(
            agent_url=agent_url or "http://127.0.0.1:8765", run_id=run_id,
            now_iso=audit_mod.now_iso())
        self.verbose = verbose
        self.expected_tools = list(expected_tools or [])
        self.kind = kind or ""
        self.messages: list[dict] = []
        self.llm_context: dict = {}

    # ---- 主循环 -------------------------------------------------------------
    def run(self, user_prompt: str) -> dict:
        self.user_prompt = user_prompt
        self.audit.user_message(user_prompt)
        self.messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        tool_sequence: list[dict] = []
        rounds = 0
        nudge = 0
        while rounds < self.max_rounds:
            rounds += 1
            self.audit.llm_request(rounds, self.model, self.base_url, self.api_style,
                                   len(self.messages), len(self.tools))
            try:
                response = self.llm.chat(self.messages, self.tools,
                                         context=dict(self.llm_context))
            except llm_client.LLMError as exc:
                self.audit.error(f"LLM 调用失败：{exc}", getattr(exc, "code", "LLM_ERROR"))
                return self._finish(f"（LLM 调用失败：{exc}）", rounds, tool_sequence)
            except Exception as exc:  # noqa: BLE001
                self.audit.error(f"LLM 未预期异常：{type(exc).__name__}: {exc}", "E_LLM")
                return self._finish(f"（LLM 异常：{exc}）", rounds, tool_sequence)
            calls_payload = [{"id": call.id, "name": call.name, "arguments": call.arguments}
                             for call in response.tool_calls]
            self.audit.llm_response(response.content, response.thinking, calls_payload,
                                    response.latency_ms, response.usage, response.parse_mode,
                                    raw=response.raw)
            if self.verbose:
                print(f"  [turn {rounds}] tool_calls={[c.name for c in response.tool_calls]} "
                      f"content={response.content[:80]!r}")
            # scripted 控制步（故障注入/等待），不消耗工具调用
            control = (response.raw or {}).get("control")
            if control and not response.tool_calls:
                outcome = self.runtime.control(control)
                self.audit.control(control, outcome.get("response"))
                if not outcome.get("ok"):
                    self.audit.error(f"控制步失败：{outcome.get('response')}", "E_CONTROL")
                self.messages.append({"role": "assistant",
                                      "content": response.content or f"（执行控制步 {control.get('type')}）"})
                self.messages.append({"role": "user",
                                      "content": "【系统】控制步已执行：" + json.dumps(
                                          outcome.get("response"), ensure_ascii=False) + "。请继续下一步。"})
                nudge = 0
                continue
            # 工具调用
            if response.tool_calls:
                self.messages.append(self.llm.assistant_message(response.content, response.tool_calls))
                for call in response.tool_calls:
                    self.audit.tool_call(rounds, call.id, call.name, call.arguments)
                    started = time.time()
                    if call.arguments is None and call.parse_error:
                        outcome = {
                            "ok": False, "tool": call.name, "error_code": "E_SCHEMA",
                            "error": {"code": "E_SCHEMA",
                                      "message": f"tool_calls.arguments 无法解析：{call.parse_error}",
                                      "details": {}},
                            "result": {"ok": False, "tool": call.name,
                                       "error": {"code": "E_SCHEMA",
                                                 "message": f"arguments 无法解析：{call.parse_error}"}},
                        }
                    else:
                        outcome = self.runtime.execute(call.name,
                                                       call.arguments if call.arguments is not None else {})
                    latency_ms = (time.time() - started) * 1000.0
                    self.audit.tool_result(call.id, call.name, outcome["ok"], outcome["result"],
                                           outcome.get("error_code"), latency_ms)
                    tool_sequence.append({"name": call.name, "ok": outcome["ok"],
                                          "error_code": outcome.get("error_code"),
                                          "turn": rounds, "latency_ms": round(latency_ms, 1)})
                    self._note_meta(call, outcome)
                    self.messages.append(self.llm.tool_message(
                        call, json.dumps(outcome["result"], ensure_ascii=False)))
                nudge = 0
                continue
            # 非工具回复 → 最终回答（空回复时最多催 2 次）
            content = (response.content or "").strip()
            # 任务未完成但模型想用一段文字结束 → Orchestrator 续跑提醒（最多 2 次）
            continuation = self._need_continue(tool_sequence, user_prompt)
            if content and continuation and nudge < MAX_NUDGES:
                nudge += 1
                self.audit.nudge(continuation, reason="final_answer_before_task_complete")
                self.messages.append({"role": "assistant", "content": content})
                self.messages.append({"role": "user", "content": continuation})
                continue
            if not content:
                nudge += 1
                if nudge > MAX_NUDGES:
                    self.audit.error("LLM 连续返回空内容", "E_LLM_EMPTY")
                    return self._finish("（模型未返回有效回答）", rounds, tool_sequence)
                self.messages.append({"role": "assistant", "content": ""})
                self.messages.append({"role": "user",
                                      "content": "请继续：调用必要工具，或用中文给出最终回答。"})
                continue
            self.audit.final_answer(content, rounds)
            return self._finish(content, rounds, tool_sequence)
        self.audit.error(f"超过最大工具调用轮次 {self.max_rounds}", "E_MAX_ROUNDS")
        return self._finish("（达到最大工具调用轮次，任务未完成）", rounds, tool_sequence)

    # ---- 续跑判定 -----------------------------------------------------------
    def _need_continue(self, sequence: list, prompt: str) -> str:
        """阶段感知续跑提醒：优先按场景 expected_tools 给出"下一个未完成工具"的具体提示。"""
        if not sequence:
            return ""
        names = [item.get("name") for item in sequence]
        errors = [str(item.get("error_code")) for item in sequence if item.get("error_code")]
        recoverable_codes = ("E_STATE", "E_BUSY", "E_SCHEMA", "E_CONFIRM_REQUIRED")
        if errors and not (self.kind == "positive"
                           and all(code in recoverable_codes for code in errors)):
            return ""   # 对抗场景的安全拒绝 / 不可恢复错误：按预期终止
        has_mission_end = "return_to_home" in names or "land" in names
        if self.llm_context.get("mission_completed") and has_mission_end:
            return ""   # 任务已执行完成且已返航/降落：允许模型结束（不做重复执行）
        plan_id = self.llm_context.get("plan_id")
        altitude = self.llm_context.get("altitude_m")
        alt_text = f"{altitude:g}" if isinstance(altitude, (int, float)) else "<计划航高>"
        for tool in self.expected_tools:
            if tool in names:
                continue
            if tool == "plan_capture_mission":
                return ("下一步请调用 plan_capture_mission 生成计划（参数取自用户请求：pattern/"
                        "center_lat/center_lon/altitude_m/radius_m/shots/gimbal_pitch_deg），"
                        "不要重复只读工具，也不要只输出文字总结。")
            if tool == "takeoff":
                if self.llm_context.get("airborne"):
                    continue
                plan_text = f"（计划 plan_id={plan_id}）" if plan_id else ""
                return (f"下一步请调用 takeoff(altitude_m={alt_text}, confirm=true) 起飞{plan_text}，"
                        f"不要只输出文字总结。")
            if tool == "goto_waypoints":
                if not plan_id:
                    return ("还没有可执行的 plan_id。请先调用 plan_capture_mission 生成计划，"
                            "再调用 goto_waypoints(plan_id=..., confirm=true) 执行。")
                return (f"下一步请调用 goto_waypoints(plan_id=\"{plan_id}\", confirm=true) "
                        f"执行航拍计划，不要重复 takeoff/get_telemetry。")
            if tool == "return_to_home":
                return "航拍任务已完成。下一步请调用 return_to_home() 返航收尾。"
            if tool == "land":
                return "任务已完成。下一步请调用 land() 原地降落收尾。"
            return f"下一步请继续调用 {tool} 完成场景期望的工具序列。"
        # 兜底（无 expected_tools 或已全部完成时）
        has_flight = "goto_waypoints" in names or "orbit" in names
        has_end = "return_to_home" in names or "land" in names
        if plan_id and not has_flight:
            return (f"计划已生成（plan_id=\"{plan_id}\"）但尚未执行。下一步请调用 "
                    f"takeoff(altitude_m={alt_text}, confirm=true)，再调用 "
                    f"goto_waypoints(plan_id=\"{plan_id}\", confirm=true)。")
        if has_flight and not has_end:
            return "任务已完成飞行。下一步请调用 return_to_home() 或 land() 收尾。"
        return ""

    # ---- 记录/上下文 --------------------------------------------------------
    def _note_meta(self, call, outcome: dict) -> None:
        meta = outcome.get("meta") or {}
        name = call.name
        args = call.arguments or {}
        if name == "plan_capture_mission" and outcome["ok"]:
            self.audit.plan_created(meta.get("plan_id", ""), meta.get("pattern", ""),
                                    int(meta.get("n_waypoints") or 0),
                                    int(meta.get("n_photos") or 0), meta.get("summary", ""))
            self.llm_context["plan_id"] = meta.get("plan_id")
            self.llm_context["altitude_m"] = meta.get("altitude_m")
        if name == "orbit" and outcome["ok"]:
            self.audit.plan_created(meta.get("plan_id", ""), "orbit", 0,
                                    int(meta.get("n_photos") or 0), "orbit 直接执行")
        if outcome["ok"] and name in ("takeoff", "goto_waypoints", "orbit"):
            self.audit.user_confirm(name, True, plan_id=str(args.get("plan_id") or ""),
                                    note="confirm=true 且 Agent 接受")
        if outcome.get("error_code") == "E_CONFIRM_REQUIRED":
            self.audit.user_confirm(name, False, plan_id=str(args.get("plan_id") or ""),
                                    note="缺少 confirm=true，Orchestrator confirm 门禁拒绝")
        if meta.get("mission_id"):
            self.llm_context["mission_id"] = meta["mission_id"]
        if meta.get("n_photos") is not None:
            self.llm_context["n_photos"] = meta["n_photos"]
        if outcome["ok"] and name == "takeoff":
            self.llm_context["airborne"] = True
        if outcome["ok"] and name in ("goto_waypoints", "orbit"):
            self.llm_context["mission_completed"] = True
            self.llm_context["airborne"] = True
        if outcome["ok"] and name in ("return_to_home", "land"):
            self.llm_context["mission_completed"] = True
            self.llm_context["airborne"] = False
            self.llm_context["ended"] = True

    def _finish(self, content: str, rounds: int, tool_sequence: list) -> dict:
        return {"final_answer": content, "rounds": rounds, "tool_sequence": tool_sequence,
                "llm_context": dict(self.llm_context),
                "audit_counters": self.audit.counters_summary()}


def main(argv=None) -> int:
    """单条 prompt 调试入口：python -m orchestrator.orchestrator --prompt "..."（需要 Agent 已启动）。"""
    parser = argparse.ArgumentParser(description="LLM Orchestrator 单条 prompt 调试")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--agent-url", default="http://127.0.0.1:8765")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--api-style", default="ollama", choices=["ollama", "openai", "auto"])
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    parser.add_argument("--run-id", default="debug")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    import agent_client
    import planner  # noqa: F401
    import tools_runtime
    audit_dir = args.out or str(__import__("pathlib").Path(__file__).resolve().parents[1]
                                / "logs" / "orchestrator" / "debug")
    audit = audit_mod.RunAudit(audit_dir, args.run_id, "debug",
                               {"mode": "real_llm", "model": args.model,
                                "base_url": args.base_url, "agent_url": args.agent_url})
    client = agent_client.AgentClient(args.agent_url)
    health = client.health()
    if health.get("ok") is False:
        print("Agent 不可用：", json.dumps(health, ensure_ascii=False))
        return 2
    cli = llm_client.build_llm_client(args.api_style, args.base_url, args.model)
    runtime = tools_runtime.ToolRuntime(client, run_id=args.run_id)
    orch = Orchestrator(cli, runtime, audit, model=args.model, base_url=args.base_url,
                        api_style=args.api_style, agent_url=args.agent_url,
                        run_id=args.run_id, max_rounds=args.max_rounds, verbose=True)
    summary = orch.run(args.prompt)
    audit.close({"final_answer": summary["final_answer"]})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
