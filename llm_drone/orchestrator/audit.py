# -*- coding: utf-8 -*-
"""运行审计产物生成（PROTOCOL.md §9.2 / §12）：llm_events.jsonl、tool_calls.jsonl、transcript.md。

- llm_events.jsonl：每个事件一行 JSON，必含 ts/run_id/seq/event；事件名与 §9.2 对齐
  （llm_request / llm_response / tool_call / tool_result / plan_created / user_confirm / final_answer / error，
   另含 run_start / user_message / control / run_end 便于复现）。
- tool_calls.jsonl：每次工具调用一行（name/args/ok/error_code/latency_ms）。
- transcript.md：人类可读对话（user → assistant(thinking/content) → tool_call → tool_result → final）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CST = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(CST).isoformat(timespec="milliseconds")


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(k): _jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(v) for v in value]
        return str(value)


def _compact(value: Any, max_chars: int = 3000) -> str:
    try:
        text = json.dumps(_jsonable(value), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > max_chars:
        text = text[:max_chars] + f"… <truncated {len(text) - max_chars} chars>"
    return text


class RunAudit:
    """一次 run 的三件审计产物；线程非安全（单进程顺序调用即可）。"""

    def __init__(self, run_dir: str | Path, run_id: str, scenario_id: str = "",
                 meta: dict | None = None) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.scenario_id = scenario_id
        self.events_path = self.run_dir / "llm_events.jsonl"
        self.tool_calls_path = self.run_dir / "tool_calls.jsonl"
        self.transcript_path = self.run_dir / "transcript.md"
        self._seq = 0
        self._tool_seq = 0
        self._pending: dict[str, dict] = {}
        self._closed = False
        self.counters: dict[str, Any] = {
            "llm_calls": 0, "tool_calls": 0, "rejected": 0,
            "error_codes": [], "prompt_tokens": 0, "completion_tokens": 0,
        }
        self._fh_events = open(self.events_path, "w", encoding="utf-8", newline="\n")
        self._fh_tools = open(self.tool_calls_path, "w", encoding="utf-8", newline="\n")
        self._fh_md = open(self.transcript_path, "w", encoding="utf-8", newline="\n")
        self._md_header(meta or {})

    # ---- 基础 ---------------------------------------------------------------
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def event(self, event: str, **fields: Any) -> dict:
        record = {"ts": now_iso(), "run_id": self.run_id, "seq": self._next_seq(),
                  "event": event}
        record.update(_jsonable(fields))
        self._fh_events.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh_events.flush()
        return record

    def _write_md(self, text: str) -> None:
        self._fh_md.write(text)
        self._fh_md.flush()

    def _md_header(self, meta: dict) -> None:
        self._write_md(f"# LLM Orchestrator 运行记录 — `{self.run_id}`\n\n")
        self._write_md(f"- scenario: `{self.scenario_id}`\n")
        for key in ("kind", "mode", "model", "base_url", "api_style", "agent_url", "started_at",
                    "sim_setup", "notes"):
            if meta.get(key) not in (None, "", {}):
                value = meta[key]
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                self._write_md(f"- {key}: `{value}`\n")
        self._write_md("\n")

    # ---- 语义化事件 ---------------------------------------------------------
    def user_message(self, prompt: str, sim_setup: dict | None = None) -> dict:
        self._write_md("\n## 用户请求\n\n" + prompt.strip() + "\n")
        if sim_setup:
            self._write_md("\n**故障注入（/v1/sim/config）**：`"
                           + json.dumps(sim_setup, ensure_ascii=False) + "`\n")
        return self.event("user_message", prompt=prompt, sim_setup=sim_setup or None)

    def llm_request(self, round_: int, model: str, base_url: str, api_style: str,
                    message_count: int, tools_count: int) -> dict:
        self.counters["llm_calls"] += 1
        self._write_md(f"\n## 第 {round_} 轮（LLM 请求）\n")
        return self.event("llm_request", round=round_, model=model, base_url=base_url,
                          api_style=api_style, message_count=message_count,
                          tools_count=tools_count)

    def llm_response(self, content: str = "", thinking: str = "", tool_calls: list | None = None,
                     latency_ms: float = 0.0, usage: dict | None = None,
                     parse_mode: str = "native_tools", raw: Any = None) -> dict:
        usage = usage or {}
        prompt = int(usage.get("prompt") or 0)
        completion = int(usage.get("completion") or 0)
        self.counters["prompt_tokens"] += prompt
        self.counters["completion_tokens"] += completion
        calls = []
        for call in tool_calls or []:
            calls.append({"id": call.get("id"), "name": call.get("name"),
                          "arguments": _jsonable(call.get("arguments"))})
        self._write_md("\n### assistant\n")
        if thinking:
            self._write_md("\n<details><summary>thinking（模型思考链，节选）</summary>\n\n"
                           + "\n".join(thinking.splitlines()[:40]) + "\n\n</details>\n")
        if content:
            self._write_md("\n" + content.strip() + "\n")
        if calls:
            self._write_md("\n**tool_calls**：" + "、".join(f"`{c['name']}`" for c in calls) + "\n")
        return self.event("llm_response", content=(content or "")[:6000],
                          thinking=(thinking or "")[:6000], tool_calls=calls,
                          latency_ms=round(float(latency_ms), 1), usage=usage,
                          parse_mode=parse_mode,
                          raw=_jsonable(raw) if raw is not None else None)

    def tool_call(self, turn: int, call_id: str, name: str, args: Any) -> dict:
        self.counters["tool_calls"] += 1
        self._pending[call_id] = {"turn": turn, "name": name, "args": _jsonable(args)}
        self._write_md(f"\n### tool_call `{name}`（call_id={call_id}）\n\n"
                       f"```json\n{_compact(args, 2000)}\n```\n")
        return self.event("tool_call", turn=turn, call_id=call_id, tool=name, args=_jsonable(args))

    def tool_result(self, call_id: str, name: str, ok: bool, result: Any,
                    error_code: str | None = None, latency_ms: float = 0.0) -> dict:
        pending = self._pending.pop(call_id, {})
        code = None if ok else (error_code or "E_INTERNAL")
        if not ok:
            self.counters["rejected"] += 1
            if code not in self.counters["error_codes"]:
                self.counters["error_codes"].append(code)
        self._tool_seq += 1
        entry = {
            "ts": now_iso(), "run_id": self.run_id, "seq": self._tool_seq,
            "turn": pending.get("turn"), "call_id": call_id, "name": name,
            "args": pending.get("args"), "ok": bool(ok), "error_code": code,
            "latency_ms": round(float(latency_ms), 1),
        }
        self._fh_tools.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._fh_tools.flush()
        self._write_md(f"\n### tool_result `{name}` — {'ok' if ok else 'FAILED(=' + str(code) + ')'}"
                       f"（{latency_ms:.0f} ms）\n\n```json\n{_compact(result, 3000)}\n```\n")
        return self.event("tool_result", call_id=call_id, tool=name, ok=bool(ok),
                          error_code=code, latency_ms=round(float(latency_ms), 1),
                          result=_jsonable(result))

    def plan_created(self, plan_id: str, pattern: str, n_waypoints: int, n_photos: int,
                     summary: str = "") -> dict:
        self._write_md(f"\n> 📋 计划生成 `{plan_id}`：{pattern}，{n_waypoints} 航点 / {n_photos} 照片\n")
        return self.event("plan_created", plan_id=plan_id, pattern=pattern,
                          n_waypoints=n_waypoints, n_photos=n_photos, summary=summary)

    def user_confirm(self, tool: str, approved: bool, plan_id: str = "", note: str = "") -> dict:
        self._write_md(f"\n> ✅ 用户确认：`{tool}` → {'批准' if approved else '拒绝'}"
                       + (f"（{note}）" if note else "") + "\n")
        return self.event("user_confirm", tool=tool, approved=bool(approved),
                          plan_id=plan_id or None, note=note)

    def nudge(self, text: str, reason: str = "") -> dict:
        self._write_md(f"\n> 🔁 Orchestrator 续跑提醒：{text}\n")
        return self.event("nudge", text=text, reason=reason)

    def control(self, control: dict, response: Any = None) -> dict:
        self._write_md(f"\n> ⚙️ 控制步（scripted）：`{json.dumps(control, ensure_ascii=False)}`\n")
        return self.event("control", control=_jsonable(control), response=_jsonable(response))

    def final_answer(self, content: str, rounds: int = 0) -> dict:
        self._write_md("\n## 最终回答\n\n" + (content or "").strip() + "\n")
        return self.event("final_answer", content=content, rounds=rounds)

    def error(self, message: str, code: str = "E_ORCHESTRATOR") -> dict:
        self._write_md(f"\n> ❌ 错误 `{code}`：{message}\n")
        return self.event("error", code=code, message=message)

    def close(self, summary: dict | None = None) -> dict:
        if self._closed:
            return {}
        record = self.event("run_end", summary=_jsonable(summary or {}),
                            counters=dict(self.counters))
        self._fh_events.close()
        self._fh_tools.close()
        self._fh_md.close()
        self._closed = True
        return record

    def counters_summary(self) -> dict:
        return {
            "llm_calls": self.counters["llm_calls"],
            "tool_calls": self.counters["tool_calls"],
            "rejected": self.counters["rejected"],
            "error_codes": list(self.counters["error_codes"]),
            "tokens": {"prompt": self.counters["prompt_tokens"],
                       "completion": self.counters["completion_tokens"]},
        }


if __name__ == "__main__":
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    a = RunAudit(tmp, "run-selftest", "P1", {"kind": "positive", "mode": "scripted"})
    a.user_message("测试任务", {"battery_pct": 90})
    a.llm_request(1, "qwen3.5:4b", "http://127.0.0.1:11434", "ollama", 2, 15)
    a.llm_response("", "thinking...", [{"id": "c1", "name": "get_telemetry", "arguments": {}}],
                   1200.0, {"prompt": 100, "completion": 20})
    a.tool_call(1, "c1", "get_telemetry", {})
    a.tool_result("c1", "get_telemetry", True, {"ok": True}, None, 30.0)
    a.plan_created("plan-abc", "grid", 20, 20, "网格")
    a.user_confirm("takeoff", True)
    a.final_answer("完成", 2)
    a.close({"passed": True})
    for name in ("llm_events.jsonl", "tool_calls.jsonl"):
        lines = (tmp / name).read_text(encoding="utf-8").strip().splitlines()
        print(name, len(lines), "lines; json ok:", all(json.loads(x) for x in lines))
    print("transcript bytes:", (tmp / "transcript.md").stat().st_size)
    print("counters:", a.counters_summary())
