# -*- coding: utf-8 -*-
"""LLM 客户端：Ollama（OpenAI 兼容 / 原生 / JSON 降级）+ 脚本化确定性客户端。

orchestrator 只依赖统一的 ChatResponse / ToolCall 结构：
  - OpenAICompatClient：POST {base}/v1/chat/completions（原生 tools，qwen3.5:4b 实测可用）
  - OllamaNativeClient：POST {base}/api/chat（原生 tools，arguments 为 dict）
  - JsonModeClient：format=json + 严格解析 + 重试/修复 + 降级（tools 不支持时的兜底）
  - ScriptedLLMClient：确定性剧本客户端（demo 可复现，不依赖模型随机性）
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

try:
    from . import tool_schemas
except ImportError:  # pragma: no cover
    import tool_schemas  # type: ignore

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:4b"
FENCE = chr(96) * 3


class LLMError(RuntimeError):
    def __init__(self, message: str, code: str = "LLM_ERROR") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict | None
    parse_error: str = ""


@dataclass
class ChatResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    latency_ms: float = 0.0
    parse_mode: str = "native_tools"   # native_tools | json_mode | scripted | degraded
    attempts: int = 1
    raw: dict = field(default_factory=dict)
    thinking: str = ""
    usage: dict = field(default_factory=dict)   # {"prompt": int, "completion": int, "total": int}


class BaseLLMClient:
    supports_native_tools = True

    def chat(self, messages: list[dict], tools: list[dict], context: dict | None = None) -> ChatResponse:
        raise NotImplementedError

    def health(self) -> dict:
        return {"ok": True, "mode": "unknown"}

    # 历史消息格式（不同端点对 tool_calls / tool 角色的格式要求不同）
    def assistant_message(self, content: str, tool_calls: list["ToolCall"]) -> dict:
        return {"role": "assistant", "content": content or "",
                "tool_calls": [{"id": c.id, "type": "function",
                                "function": {"name": c.name,
                                             "arguments": json.dumps(c.arguments or {}, ensure_ascii=False)}}
                               for c in tool_calls]}

    def tool_message(self, call: "ToolCall", content: str) -> dict:
        return {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": content}


# ---- 文本 → JSON 宽松解析 ---------------------------------------------------
def _strip_fences(text: str) -> str:
    pattern = FENCE + r"(?:json)?\s*(.*?)" + FENCE
    m = re.search(pattern, text, re.S)
    return m.group(1).strip() if m else text.strip()


def loads_loose(text: str) -> Any:
    """从模型输出中尽力解析 JSON（去代码围栏 / 截取首个对象 / 去尾逗号 / 单引号兜底）。"""
    if not isinstance(text, str):
        raise ValueError("输入不是字符串")
    s = _strip_fences(text)
    if not s:
        raise ValueError("空输出")
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        sub = s[start:end + 1]
        try:
            return json.loads(sub)
        except json.JSONDecodeError:
            sub2 = re.sub(r",\s*([}\]])", r"\1", sub)
            try:
                return json.loads(sub2)
            except json.JSONDecodeError:
                pass
    try:  # 部分模型用单引号
        import ast
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        raise ValueError(f"无法解析为 JSON：{text[:200]}")


def parse_arguments(raw: Any) -> tuple[dict | None, str]:
    """把 tool_call.arguments（JSON 字符串或 dict）解析为 dict。"""
    if raw is None or raw == "":
        return {}, ""
    if isinstance(raw, dict):
        return raw, ""
    if isinstance(raw, str):
        try:
            value = loads_loose(raw)
        except ValueError as exc:
            return None, str(exc)
        if isinstance(value, dict):
            return value, ""
        return None, f"arguments 应为 JSON 对象，实际 {type(value).__name__}"
    return None, f"arguments 类型不支持：{type(raw).__name__}"


def normalize_tool_calls(raw_calls: Any, style: str = "openai") -> list[ToolCall]:
    calls: list[ToolCall] = []
    if not isinstance(raw_calls, list):
        return calls
    for i, tc in enumerate(raw_calls):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        name = fn.get("name") or tc.get("name") or ""
        args_raw = fn.get("arguments", tc.get("arguments"))
        args, err = parse_arguments(args_raw)
        calls.append(ToolCall(id=str(tc.get("id") or f"call_{i}"), name=str(name),
                              arguments=args, parse_error=err))
    return calls


# ---- HTTP 基础 --------------------------------------------------------------
def _post_json(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def probe_ollama(base_url: str = DEFAULT_BASE_URL, timeout: float = 5.0) -> dict:
    """探测 Ollama 是否可用及模型列表。"""
    url = base_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name", "") for m in (body.get("models") or [])]
        return {"ok": True, "base_url": base_url, "models": models}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "base_url": base_url, "error": str(exc)}


def pick_model(models: list[str], preferred: str) -> str:
    if preferred in models:
        return preferred
    for m in models:
        if m.split(":")[0] == preferred.split(":")[0]:
            return m
    return models[0] if models else preferred


class _HttpLLMClient(BaseLLMClient):
    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
                 timeout: float = 180.0, temperature: float = 0.1, retries: int = 2,
                 options: dict | None = None, seed: int | None = None,
                 think: bool | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.retries = retries
        self.options = options or {}
        self.seed = seed
        self.think = think

    def _call(self, path: str, payload: dict) -> dict:
        url = self.base_url + path
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            t0 = time.time()
            try:
                body = _post_json(url, payload, self.timeout)
                body["_latency_ms"] = (time.time() - t0) * 1000.0
                return body
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                last_exc = LLMError(f"LLM HTTP {exc.code}: {detail}", code="LLM_HTTP_ERROR")
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_exc = LLMError(f"LLM 连接失败：{exc}", code="LLM_UNAVAILABLE")
            if attempt < self.retries:
                time.sleep(1.0 + attempt)
        raise last_exc or LLMError("LLM 调用失败")

    def health(self) -> dict:
        probe = probe_ollama(self.base_url, timeout=5.0)
        probe["model"] = self.model
        probe["client"] = type(self).__name__
        return probe


class OpenAICompatClient(_HttpLLMClient):
    """OpenAI 兼容 /v1/chat/completions（Ollama、vLLM、OpenAI 等均可）。"""

    def chat(self, messages: list[dict], tools: list[dict], context: dict | None = None) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": False,
            "temperature": self.temperature,
        }
        opts = dict(self.options)
        if self.seed is not None:
            opts["seed"] = self.seed
        if opts:
            payload["options"] = opts
        body = self._call("/v1/chat/completions", payload)
        try:
            choice = (body.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
        except (IndexError, AttributeError) as exc:
            raise LLMError(f"LLM 响应结构异常：{str(body)[:300]}") from exc
        content = msg.get("content") or ""
        if isinstance(content, list):  # 兼容部分实现的分段 content
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        raw_calls = msg.get("tool_calls") or []
        calls = normalize_tool_calls(raw_calls, "openai")
        usage_raw = body.get("usage") or {}
        usage = {
            "prompt": int(usage_raw.get("prompt_tokens") or usage_raw.get("input_tokens") or 0),
            "completion": int(usage_raw.get("completion_tokens") or usage_raw.get("output_tokens") or 0),
        }
        return ChatResponse(content=content, tool_calls=calls,
                            latency_ms=body.get("_latency_ms", 0.0), parse_mode="native_tools",
                            raw={"finish_reason": choice.get("finish_reason")},
                            thinking=msg.get("reasoning_content") or "", usage=usage)


class OllamaNativeClient(_HttpLLMClient):
    """/api/chat 原生 tools（arguments 直接是 dict）。think=False 时关闭思考链，更稳定更快。"""

    def __init__(self, *args: Any, think: bool | None = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.think = think

    def assistant_message(self, content: str, tool_calls: list["ToolCall"]) -> dict:
        return {"role": "assistant", "content": content or "",
                "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments or {}}}
                               for c in tool_calls]}

    def tool_message(self, call: "ToolCall", content: str) -> dict:
        return {"role": "tool", "tool_name": call.name, "content": content}

    def chat(self, messages: list[dict], tools: list[dict], context: dict | None = None) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            # 实测：Ollama 默认 num_ctx=4096，多轮工具结果会超上下文被截断 → 空响应/行为异常。
            # 这里显式给 16k 上下文 + 1024 输出上限（可被 self.options 覆盖）。
            "options": {"temperature": self.temperature, "num_ctx": 16384, "num_predict": 1024,
                        **(self.options)},
        }
        if self.seed is not None:
            payload["options"]["seed"] = self.seed
        if self.think is not None:
            payload["think"] = bool(self.think)
        body = self._call("/api/chat", payload)
        msg = body.get("message") or {}
        calls = normalize_tool_calls(msg.get("tool_calls") or [], "ollama")
        usage = {
            "prompt": int(body.get("prompt_eval_count") or 0),
            "completion": int(body.get("eval_count") or 0),
        }
        return ChatResponse(content=msg.get("content") or "", tool_calls=calls,
                            latency_ms=body.get("_latency_ms", 0.0), parse_mode="native_tools",
                            raw={"done": body.get("done")}, thinking=msg.get("thinking") or "",
                            usage=usage)


class JsonModeClient(_HttpLLMClient):
    """无 tools 支持时的兜底：强约束 JSON 输出 + 解析失败重试/修复 + 最终降级。"""

    MAX_ATTEMPTS = 3
    supports_native_tools = False

    def assistant_message(self, content: str, tool_calls: list["ToolCall"]) -> dict:
        if not tool_calls:
            return {"role": "assistant", "content": content or ""}
        return {"role": "assistant", "content": json.dumps(
            {"tool": tool_calls[0].name, "args": tool_calls[0].arguments or {}}, ensure_ascii=False)}

    def tool_message(self, call: "ToolCall", content: str) -> dict:
        return {"role": "user", "content": (
            "【工具执行结果】tool=" + call.name + "\n" + content + "\n"
            '请继续：如需继续调用工具只输出 JSON；任务完成输出 {"final": "..."}。')}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._tool_catalog = tool_schemas.tool_catalog_for_prompt()

    def _system_suffix(self) -> str:
        return (
            "\n\n【工具调用输出格式（必须严格遵守）】\n"
            "可用工具：\n" + self._tool_catalog + "\n"
            "若需要调用工具，只输出一个 JSON 对象："
            '{"tool": "<工具名>", "args": {<参数>}}\n'
            "若任务已完成或需要向用户说明，只输出："
            '{"final": "<中文回答>"}\n'
            "规则：一次只输出一个工具调用；args 必须是 JSON 对象；不要输出解释、Markdown 或代码块。"
        )

    def chat(self, messages: list[dict], tools: list[dict], context: dict | None = None) -> ChatResponse:
        convo = [dict(m) for m in messages]
        if convo and convo[0].get("role") == "system":
            convo[0]["content"] = (convo[0].get("content") or "") + self._system_suffix()
        else:
            convo.insert(0, {"role": "system", "content": self._system_suffix()})
        last_error = ""
        t_start = time.time()
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            payload: dict[str, Any] = {
                "model": self.model, "messages": convo, "stream": False, "format": "json",
                "options": {"temperature": self.temperature, **(self.options)},
            }
            body = self._call("/api/chat", payload)
            msg = body.get("message") or {}
            content = msg.get("content") or ""
            try:
                parsed = loads_loose(content)
                return self._to_response(parsed, content, time.time() - t_start, attempt)
            except ValueError as exc:
                last_error = str(exc)
                if attempt < self.MAX_ATTEMPTS:
                    convo.append({"role": "assistant", "content": content[:2000]})
                    convo.append({"role": "user", "content":
                                  f"上一条输出不是合法 JSON（{last_error}）。"
                                  '请只输出 {"tool": "...", "args": {...}} 或 {"final": "..."}，不要任何解释。'})
                else:
                    return ChatResponse(
                        content="（降级）本地模型输出无法解析为合法 JSON，已终止工具调用。"
                                f"请重试或改用原生 tools 模式。最后错误：{last_error}",
                        tool_calls=[], latency_ms=(time.time() - t_start) * 1000.0,
                        parse_mode="degraded", attempts=attempt, raw={"last_raw": content[:500]})
        raise LLMError("JSON 模式解析失败")

    def _to_response(self, parsed: Any, content: str, elapsed: float, attempt: int) -> ChatResponse:
        if not isinstance(parsed, dict):
            raise ValueError(f"顶层应为 JSON 对象，实际 {type(parsed).__name__}")
        tool_calls: list[ToolCall] = []
        if isinstance(parsed.get("tool_calls"), list):
            tool_calls = normalize_tool_calls(parsed["tool_calls"], "openai")
        elif parsed.get("tool"):
            args, err = parse_arguments(parsed.get("args", {}))
            tool_calls = [ToolCall(id=f"json_{attempt}", name=str(parsed["tool"]),
                                   arguments=args, parse_error=err)]
        final_text = parsed.get("final") or parsed.get("answer") or parsed.get("content") or ""
        return ChatResponse(content=str(final_text or content), tool_calls=tool_calls,
                            latency_ms=elapsed * 1000.0, parse_mode="json_mode",
                            attempts=attempt, raw={"parsed": parsed})

    def health(self) -> dict:
        probe = probe_ollama(self.base_url, timeout=5.0)
        probe.update({"model": self.model, "client": type(self).__name__, "mode": "json"})
        return probe


# ---- 脚本化客户端（demo 可复现 / 单元测试） ---------------------------------
def _resolve_placeholders(value: Any, ctx: dict) -> Any:
    if isinstance(value, str):
        m = re.fullmatch(r"\$(\w+)", value)
        if m and m.group(1) in ctx:
            return ctx[m.group(1)]
        def repl(match: re.Match) -> str:
            key = match.group(1)
            return str(ctx.get(key, match.group(0)))
        return re.sub(r"\$\{(\w+)\}", repl, value)
    if isinstance(value, dict):
        return {k: _resolve_placeholders(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_placeholders(v, ctx) for v in value]
    return value


class ScriptedLLMClient(BaseLLMClient):
    """按剧本返回固定的 tool_calls / 文本，用于确定性 transcript 与回归测试。

    剧本 step 结构：
      {"text": "可选前置说明", "tool": "工具名", "args": {...}}
      {"tool_calls": [{"name": ..., "args": ...}, ...]}
      {"text": "最终回答"}   # 无 tool 时即结束
    args 中 "$plan_id" / "$mission_id" / "$waypoints" 会从运行上下文替换。
    """

    def __init__(self, steps: list[dict], final_text: str = "") -> None:
        self.steps = list(steps or [])
        self.final_text = final_text
        self.index = 0

    def chat(self, messages: list[dict], tools: list[dict], context: dict | None = None) -> ChatResponse:
        ctx = context or {}
        if self.index >= len(self.steps):
            return ChatResponse(content=self.final_text or "（剧本结束）", tool_calls=[],
                                latency_ms=0.0, parse_mode="scripted")
        step = self.steps[self.index]
        self.index += 1
        if isinstance(step, dict) and step.get("control"):
            # 控制步（仅 scripted 模式）：交给 Orchestrator 执行 sim_config / wait 等，不消耗 LLM 轮次语义
            return ChatResponse(content=str(step.get("text") or ""), tool_calls=[],
                                latency_ms=0.0, parse_mode="scripted",
                                raw={"step": self.index, "control": step["control"]})
        content = str(step.get("text") or "")
        raw_calls = step.get("tool_calls")
        if raw_calls is None and step.get("tool"):
            raw_calls = [{"name": step["tool"], "args": step.get("args") or {}}]
        calls: list[ToolCall] = []
        for j, raw in enumerate(raw_calls or []):
            name = raw.get("name") or raw.get("tool") or ""
            args = _resolve_placeholders(raw.get("args") or {}, ctx)
            calls.append(ToolCall(id=f"script-{self.index}-{j}", name=str(name), arguments=args))
        return ChatResponse(content=content, tool_calls=calls, latency_ms=0.0,
                            parse_mode="scripted", raw={"step": self.index})

    def health(self) -> dict:
        return {"ok": True, "mode": "scripted", "steps": len(self.steps),
                "client": type(self).__name__}


# ---- 工厂 -------------------------------------------------------------------
def build_llm_client(mode: str = "auto", base_url: str = DEFAULT_BASE_URL,
                     model: str = DEFAULT_MODEL, timeout: float = 180.0,
                     temperature: float = 0.1, think: bool | None = True) -> BaseLLMClient:
    """mode: auto | openai | ollama | json（auto：Ollama 可用则原生 /api/chat）。"""
    mode = (mode or "auto").lower()
    if mode == "openai":
        return OpenAICompatClient(base_url, model, timeout=timeout, temperature=temperature)
    if mode == "ollama":
        return OllamaNativeClient(base_url, model, timeout=timeout, temperature=temperature,
                                  think=think)
    if mode == "json":
        return JsonModeClient(base_url, model, timeout=timeout, temperature=temperature)
    probe = probe_ollama(base_url)
    if not probe.get("ok"):
        raise LLMError(f"Ollama 不可用（{base_url}）：{probe.get('error')}", code="LLM_UNAVAILABLE")
    # spec 默认：Ollama 原生 /api/chat（实测 arguments 为对象、带 thinking、支持多 tool_calls）
    return OllamaNativeClient(base_url, model, timeout=timeout, temperature=temperature,
                              think=think)


if __name__ == "__main__":
    import sys

    print("== LLM 客户端自检 ==")
    probe = probe_ollama()
    print("Ollama 探测:", probe)
    if not probe.get("ok"):
        sys.exit(0)
    model = pick_model(probe["models"], DEFAULT_MODEL)
    print("使用模型:", model)
    messages = [
        {"role": "system", "content": "你是无人机助手，需要数据时调用工具。"},
        {"role": "user", "content": "看看当前遥测"},
    ]
    tools = tool_schemas.get_tool_schemas()
    for label, client in (("openai", OpenAICompatClient(model=model)),
                          ("ollama-native", OllamaNativeClient(model=model)),
                          ("json-mode", JsonModeClient(model=model))):
        try:
            resp = client.chat(messages, tools)
            print(f"[{label}] {resp.latency_ms:.0f}ms mode={resp.parse_mode} "
                  f"tool_calls={[(c.name, c.arguments, c.parse_error) for c in resp.tool_calls]} "
                  f"content={resp.content[:80]!r}")
        except LLMError as exc:
            print(f"[{label}] 失败: {exc}")
    for sample in ['{"tool":"get_telemetry","args":{}}',
                   FENCE + 'json\n{"tool": "takeoff", "args": {"altitude_m": 20}}\n' + FENCE,
                   '{"tool": "takeoff", "args": {"altitude_m": 20,}}']:
        try:
            print("loose:", loads_loose(sample))
        except ValueError as exc:
            print("loose FAIL:", exc)
