# -*- coding: utf-8 -*-
"""llm_client 单测：本地 http.server mock 两种 arguments 形态 / thinking / 多 tool_calls / 重试。"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from orchestrator import llm_client


class _State:
    def __init__(self):
        self.calls = []
        self.requests = []
        self.fail_first = 0


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: D401 - 静音
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            state.calls.append(self.path)
            state.requests.append(payload)
            if state.fail_first > 0:
                state.fail_first -= 1
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"boom"}')
                return
            if self.path == "/api/chat" and any(
                    isinstance(m, dict) and m.get("content") == "plain"
                    for m in payload.get("messages") or []):
                body = {"message": {"role": "assistant", "content": "你好，需要航拍吗？",
                                    "thinking": ""}, "done": True}
            elif self.path == "/api/chat" and any(
                    isinstance(m, dict) and m.get("content") == "bad-json"
                    for m in payload.get("messages") or []):
                body = {"message": {"role": "assistant", "content": "",
                                    "tool_calls": [{"id": "call_x", "function": {
                                        "name": "takeoff", "arguments": "not-a-json"}}]},
                        "done": True}
            elif self.path == "/api/chat":
                body = {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "thinking": "先读遥测，再看电量。",
                        "tool_calls": [
                            {"id": "call_a", "function": {"name": "get_telemetry", "arguments": {}}},
                            {"id": "call_b", "function": {"name": "preflight_check", "arguments": {}}},
                        ],
                    },
                    "done": True,
                    "prompt_eval_count": 120,
                    "eval_count": 25,
                }
            elif self.path == "/v1/chat/completions":
                body = {
                    "choices": [{"message": {
                        "role": "assistant", "content": "ok",
                        "tool_calls": [{"id": "call_c", "type": "function", "function": {
                            "name": "takeoff",
                            "arguments": '{"altitude_m": 40, "confirm": true}'}}],
                    }, "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 88, "completion_tokens": 12},
                }
            elif self.path == "/api/chat/plain":
                body = {"message": {"role": "assistant", "content": "你好，需要航拍吗？",
                                    "thinking": ""}, "done": True}
            else:
                body = {"message": {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "call_x", "function": {"name": "takeoff",
                                                  "arguments": "not-a-json"}}]}}
            data = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


class LlmClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = _State()
        cls.server = HTTPServer(("127.0.0.1", 0), make_handler(cls.state))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.state.calls.clear()
        self.state.requests.clear()
        self.state.fail_first = 0

    def test_ollama_object_arguments_thinking_multi_calls(self):
        client = llm_client.OllamaNativeClient(self.base, "qwen3.5:4b", retries=0, think=False)
        resp = client.chat([{"role": "user", "content": "看看状态"}], [])
        self.assertEqual(len(resp.tool_calls), 2)
        self.assertEqual(resp.tool_calls[0].name, "get_telemetry")
        self.assertEqual(resp.tool_calls[0].arguments, {})
        self.assertEqual(resp.tool_calls[1].name, "preflight_check")
        self.assertIn("遥测", resp.thinking)
        self.assertEqual(resp.usage, {"prompt": 120, "completion": 25})
        self.assertEqual(resp.parse_mode, "native_tools")
        # 请求体包含 tools / 关闭 thinking
        payload = self.state.requests[-1]
        self.assertEqual(payload["model"], "qwen3.5:4b")
        self.assertFalse(payload["think"])

    def test_openai_string_arguments_and_usage(self):
        client = llm_client.OpenAICompatClient(self.base, "qwen3.5:4b", retries=0)
        resp = client.chat([{"role": "user", "content": "起飞"}], [])
        self.assertEqual(len(resp.tool_calls), 1)
        self.assertEqual(resp.tool_calls[0].name, "takeoff")
        self.assertEqual(resp.tool_calls[0].arguments, {"altitude_m": 40, "confirm": True})
        self.assertEqual(resp.tool_calls[0].parse_error, "")
        self.assertEqual(resp.usage, {"prompt": 88, "completion": 12})

    def test_plain_text_reply(self):
        client = llm_client.OllamaNativeClient(self.base + "/", "qwen3.5:4b", retries=0)
        resp = client.chat([{"role": "user", "content": "plain"}], [])
        self.assertEqual(resp.tool_calls, [])
        self.assertIn("航拍", resp.content)

    def test_malformed_arguments_reports_parse_error(self):
        client = llm_client.OllamaNativeClient(self.base, "qwen3.5:4b", retries=0)
        resp = client.chat([{"role": "user", "content": "bad-json"}], [])
        self.assertEqual(resp.tool_calls[0].name, "takeoff")
        self.assertIsNone(resp.tool_calls[0].arguments)
        self.assertTrue(resp.tool_calls[0].parse_error)

    def test_retry_on_http_500(self):
        client = llm_client.OllamaNativeClient(self.base, "qwen3.5:4b", retries=1)
        self.state.fail_first = 1
        resp = client.chat([{"role": "user", "content": "x"}], [])
        self.assertEqual(len(resp.tool_calls), 2)   # 第二次成功
        self.assertEqual(len(self.state.calls), 2)

    def test_unreachable_raises_llm_error(self):
        client = llm_client.OllamaNativeClient("http://127.0.0.1:1", "m", retries=0, timeout=1)
        with self.assertRaises(llm_client.LLMError):
            client.chat([{"role": "user", "content": "x"}], [])

    def test_parse_arguments_variants(self):
        self.assertEqual(llm_client.parse_arguments("{}"), ({}, ""))
        self.assertEqual(llm_client.parse_arguments({"a": 1}), ({"a": 1}, ""))
        self.assertEqual(llm_client.parse_arguments(None), ({}, ""))
        self.assertEqual(llm_client.parse_arguments('[1,2]')[0], None)
        args, err = llm_client.parse_arguments("not json")
        self.assertIsNone(args)
        self.assertTrue(err)

    def test_loads_loose(self):
        self.assertEqual(llm_client.loads_loose('{"a": 1,}'), {"a": 1})
        fenced = chr(96) * 3 + 'json\n{"tool": "takeoff"}\n' + chr(96) * 3
        self.assertEqual(llm_client.loads_loose(fenced), {"tool": "takeoff"})

    def test_scripted_client_control_and_placeholders(self):
        steps = [
            {"text": "规划", "tool": "plan_capture_mission", "args": {"pattern": "grid"}},
            {"tool": "goto_waypoints", "args": {"plan_id": "$plan_id", "confirm": True}},
            {"control": {"type": "sim_config", "config": {"battery_pct": 19}}},
            {"tool": "get_telemetry", "args": {}},
        ]
        client = llm_client.ScriptedLLMClient(steps, final_text="完成")
        first = client.chat([], [], context={"plan_id": "plan-xyz"})
        self.assertEqual(first.tool_calls[0].name, "plan_capture_mission")
        second = client.chat([], [], context={"plan_id": "plan-xyz"})
        self.assertEqual(second.tool_calls[0].arguments["plan_id"], "plan-xyz")
        third = client.chat([], [], context={})
        self.assertIsNone(third.raw.get("control") and None)
        self.assertEqual(third.raw.get("control"), {"type": "sim_config", "config": {"battery_pct": 19}})
        fourth = client.chat([], [], context={})
        self.assertEqual(fourth.tool_calls[0].name, "get_telemetry")
        fifth = client.chat([], [], context={})
        self.assertEqual(fifth.content, "完成")

    def test_tool_definitions_from_spec(self):
        from orchestrator import prompts
        tools = prompts.tool_definitions()
        self.assertGreaterEqual(len(tools), 15)
        names = [item["function"]["name"] for item in tools]
        self.assertIn("plan_capture_mission", names)
        self.assertIn("goto_waypoints", names)
        goto = next(item for item in tools if item["function"]["name"] == "goto_waypoints")
        self.assertIn("confirm", goto["function"]["parameters"]["properties"])
        plan = next(item for item in tools if item["function"]["name"] == "plan_capture_mission")
        self.assertIn("center_lat", plan["function"]["parameters"]["properties"])
        system = prompts.build_system_prompt(agent_url="http://x", run_id="r1")
        for keyword in ("confirm=true", "plan_capture_mission", "E_ALT_LIMIT", "两步"):
            self.assertIn(keyword, system)


if __name__ == "__main__":
    unittest.main()
