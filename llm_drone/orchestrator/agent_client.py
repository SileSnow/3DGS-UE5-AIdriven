# -*- coding: utf-8 -*-
"""Drone Agent HTTP 客户端（PROTOCOL.md §3）。

仅标准库（urllib）。职责：
  - 统一超时（spec §3.1：单次请求 10s）/ 重试 / 网络错误归一化（永远返回结构化 dict，不抛异常）；
  - 封装 /v1/health、/v1/telemetry、/v1/command、/v1/missions*、/v1/audit、/v1/reset、/v1/sim/config；
  - mission 进度轮询（wait_mission）/ 状态等待（wait_state）；
  - 兼容 drone-sim 当前实现的 /v1/sim/inject（当 /v1/sim/config 404 时自动回退）。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_AGENT_URL = "http://127.0.0.1:8765"
REQUEST_TIMEOUT_S = 10.0          # spec §3.1
DEFAULT_RETRIES = 2
MISSION_STOP_STATES = ("completed", "aborted", "failed")


class AgentClient:
    """极简 HTTP JSON 客户端。所有方法返回 dict（失败时 {"ok": false, "error": {...}}）。"""

    def __init__(self, base_url: str = DEFAULT_AGENT_URL, timeout: float = REQUEST_TIMEOUT_S,
                 retries: int = DEFAULT_RETRIES, retry_delay: float = 0.4,
                 verbose: bool = False) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.retry_delay = float(retry_delay)
        self.verbose = verbose
        self.request_count = 0
        self.last_error: dict | None = None

    # ---- 基础请求 -----------------------------------------------------------
    @staticmethod
    def _err(code: str, message: str, details: dict | None = None) -> dict:
        return {"ok": False, "error": {"code": code, "message": message, "details": details or {}}}

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = self.base_url + path
        last: dict | None = None
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        for attempt in range(self.retries + 1):
            self.request_count += 1
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    last = self._err("E_AGENT_PROTOCOL", f"Agent 返回非 JSON（{path}）：{raw[:200]}")
                    return last
                if not isinstance(body, dict):
                    return self._err("E_AGENT_PROTOCOL", f"Agent 返回非对象（{path}）")
                return body
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")[:400]
                except OSError:
                    pass
                try:
                    parsed = json.loads(detail)
                    if isinstance(parsed, dict) and "error" in parsed:
                        return parsed  # 4xx/5xx 但 body 是结构化错误：直接透传
                except (json.JSONDecodeError, ValueError):
                    pass
                last = self._err(f"E_AGENT_HTTP_{exc.code}", f"Agent HTTP {exc.code} {path}: {detail}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = self._err("E_AGENT_UNREACHABLE", f"无法连接 Agent {self.base_url}（{path}）：{exc}")
            if attempt < self.retries:
                time.sleep(self.retry_delay * (attempt + 1))
        self.last_error = last
        return last or self._err("E_AGENT_INTERNAL", "未知 Agent 错误")

    # ---- 端点 ---------------------------------------------------------------
    def health(self) -> dict:
        return self._request("GET", "/v1/health")

    def telemetry(self) -> dict:
        return self._request("GET", "/v1/telemetry")

    def command(self, tool: str, args: dict | None = None, confirm: bool = False,
                run_id: str = "", command_id: str | None = None) -> dict:
        payload: dict[str, Any] = {
            "tool": tool,
            "args": dict(args or {}),
            "confirm": bool(confirm),
            "command_id": command_id or f"c-{int(time.time() * 1000) % 1000000:06d}",
        }
        if run_id:
            payload["run_id"] = run_id
        return self._request("POST", "/v1/command", payload)

    def mission(self, mission_id: str) -> dict:
        return self._request("GET", "/v1/missions/" + urllib.parse.quote(str(mission_id), safe=""))

    def missions(self, limit: int = 10) -> dict:
        return self._request("GET", f"/v1/missions?limit={int(limit)}")

    def audit_events(self, since_seq: int = 0) -> dict:
        return self._request("GET", f"/v1/audit?since_seq={int(since_seq)}")

    def reset(self, run_id: str = "") -> dict:
        payload = {"run_id": run_id} if run_id else {}
        return self._request("POST", "/v1/reset", payload)

    def sim_config(self, config: dict) -> dict:
        """故障注入。spec: POST /v1/sim/config；兼容 drone-sim 当前 /v1/sim/inject。"""
        resp = self._request("POST", "/v1/sim/config", dict(config))
        err = resp.get("error") or {}
        code = str(err.get("code") or "")
        if not resp.get("ok") and ("404" in code or code in ("E_NOT_FOUND", "E_UNKNOWN_ENDPOINT")):
            resp = self._request("POST", "/v1/sim/inject", dict(config))
        return resp

    # ---- 轮询辅助 -----------------------------------------------------------
    def wait_mission(self, mission_id: str, timeout_s: float = 240.0,
                     poll_s: float = 0.25) -> dict:
        """轮询任务记录直到 completed/aborted/failed 或超时。返回最后一次记录（超时时附加 timed_out）。"""
        deadline = time.time() + float(timeout_s)
        last: dict = {}
        while time.time() < deadline:
            rec = self.mission(mission_id)
            last = rec
            if rec.get("ok") is False:
                err = rec.get("error") or {}
                if str(err.get("code", "")).startswith("E_AGENT_HTTP_404"):
                    time.sleep(poll_s)
                    continue
                return rec
            if rec.get("state") in MISSION_STOP_STATES:
                return rec
            time.sleep(poll_s)
        if last:
            last = dict(last)
            last["timed_out"] = True
            return last
        return self._err("E_AGENT_TIMEOUT", f"等待 mission {mission_id} 超时 {timeout_s}s")

    def wait_state(self, states, timeout_s: float = 120.0, poll_s: float = 0.2) -> dict:
        """轮询 telemetry 直到 state ∈ states 或超时；返回 telemetry（附 timed_out）。"""
        wanted = tuple(states)
        deadline = time.time() + float(timeout_s)
        last: dict = {}
        while time.time() < deadline:
            tel = self.telemetry()
            last = tel
            if tel.get("ok") is False:
                time.sleep(poll_s)
                continue
            if tel.get("state") in wanted:
                return tel
            time.sleep(poll_s)
        out = dict(last or {})
        out.setdefault("ok", True)
        out["timed_out"] = True
        return out


if __name__ == "__main__":
    import sys

    client = AgentClient(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_AGENT_URL)
    print("health:", json.dumps(client.health(), ensure_ascii=False)[:500])
    print("telemetry:", json.dumps(client.telemetry(), ensure_ascii=False)[:500])
