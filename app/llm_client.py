"""HTTP client for DeepSeek LLM with streaming and tool calling."""
import json
import time
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.langfuse_tracing import get_active_trace


def _build_url() -> str:
    base = settings.deepseek_api_url.rstrip("/")
    return f"{base}/chat/completions"


def _build_messages(system_prompt: str, messages: list[dict]) -> list[dict]:
    """Собирает messages с system в начале."""
    return [{"role": "system", "content": system_prompt}, *messages]


def _usage_from_response(data: dict) -> dict | None:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    out = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key in usage:
            out[key] = usage[key]
    return out or None


async def stream_chat(
    system_prompt: str,
    messages: list[dict],
) -> AsyncIterator[str]:
    """
    Call DeepSeek chat completions with stream=True.
    Yields content deltas (text chunks) from the stream.
    """
    url = _build_url()
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    built = _build_messages(system_prompt, messages)
    payload = {
        "model": "deepseek-chat",
        "messages": built,
        "stream": True,
    }
    trace = get_active_trace()
    t0 = time.perf_counter()
    full_content: list[str] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choice = obj.get("choices") or []
                if not choice:
                    continue
                delta = choice[0].get("delta") or {}
                content = delta.get("content")
                if content is not None and isinstance(content, str):
                    full_content.append(content)
                    yield content
    if trace:
        trace.log_llm(
            input_messages=built,
            output="".join(full_content),
            has_tools=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )


async def chat_once(system_prompt: str, messages: list[dict]) -> str:
    """Один запрос к LLM без стриминга. Возвращает полный ответ (только content)."""
    full: list[str] = []
    async for chunk in stream_chat(system_prompt, messages):
        full.append(chunk)
    return "".join(full)


async def chat_once_with_tools(
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
) -> dict:
    """
    Один запрос к LLM с передачей tools. Без стриминга.
    Возвращает {"content": str, "tool_calls": list | None}.
    tool_calls: [{"id": str, "name": str, "arguments": dict}].
    """
    url = _build_url()
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    built = _build_messages(system_prompt, messages)
    payload = {
        "model": "deepseek-chat",
        "messages": built,
        "tools": tools,
    }
    trace = get_active_trace()
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = (msg.get("content") or "").strip()
    raw_tool_calls = msg.get("tool_calls") or []
    tool_calls = []
    for tc in raw_tool_calls:
        fid = tc.get("id") or ""
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        args_str = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            args = {}
        tool_calls.append({"id": fid, "name": name, "arguments": args})
    result = {"content": content, "tool_calls": tool_calls if tool_calls else None}
    if trace:
        trace.log_llm(
            input_messages=built,
            output=result,
            has_tools=True,
            usage=_usage_from_response(data),
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    return result
