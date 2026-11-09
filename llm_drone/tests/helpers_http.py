"""极简 HTTP 客户端（测试用，标准库）。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class HttpClient:
    def __init__(self, base_url, timeout=30.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method, path, body=None, timeout=None):
        url = self.base + path
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return exc.code, {"raw": raw}

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body):
        return self.request("POST", path, body)

    def command(self, command_id, tool, args=None, confirm=False):
        return self.post(
            "/v1/command",
            {"command_id": command_id, "tool": tool, "args": args or {}, "confirm": confirm},
        )

    def wait_for(self, predicate, timeout_s=120.0, interval=0.1):
        import time

        deadline = time.time() + timeout_s
        last = None
        while time.time() < deadline:
            status, payload = self.get("/v1/health")
            last = payload
            if status == 200 and predicate(payload):
                return payload
            time.sleep(interval)
        raise TimeoutError(f"等待条件超时: {json.dumps(last, ensure_ascii=False)[:500]}")
