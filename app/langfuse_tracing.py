"""LangFuse: трассировка вызовов LLM (DeepSeek) и MCP без замены httpx."""
from __future__ import annotations

import contextvars
import json
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from app.config import settings

_chat_trace_ctx: contextvars.ContextVar["ChatTrace | None"] = contextvars.ContextVar(
    "chat_trace", default=None
)

_langfuse_client = None


def is_enabled() -> bool:
    return bool(
        settings.langfuse_enabled
        and settings.langfuse_public_key.strip()
        and settings.langfuse_secret_key.strip()
        and settings.langfuse_host.strip()
    )


def get_client():
    global _langfuse_client
    if not is_enabled():
        return None
    if _langfuse_client is None:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key.strip(),
            secret_key=settings.langfuse_secret_key.strip(),
            host=settings.langfuse_host.rstrip("/"),
        )
    return _langfuse_client


def get_active_trace() -> "ChatTrace | None":
    return _chat_trace_ctx.get()


def _truncate(value: Any, limit: int = 8000) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…[truncated]"
    try:
        s = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        s = str(value)
    if len(s) <= limit:
        return value
    return s[:limit] + "…[truncated]"


class ChatTrace:
    """Один trace на запрос чата (пользовательский, тестовый, Telegram, админ)."""

    def __init__(
        self,
        *,
        name: str,
        session_id: str,
        tenant_id: UUID | str | None = None,
        chat_type: str = "chat",
        metadata: dict | None = None,
    ):
        self.name = name
        self.session_id = session_id
        self.tenant_id = str(tenant_id) if tenant_id else None
        self.chat_type = chat_type
        self.metadata = metadata or {}
        self._trace = None
        self._llm_round = 0

    def start(self) -> "ChatTrace":
        client = get_client()
        if not client:
            return self
        meta = {**self.metadata, "chat_type": self.chat_type}
        if self.tenant_id:
            meta["tenant_id"] = self.tenant_id
        self._trace = client.trace(
            name=self.name,
            session_id=self.session_id,
            user_id=self.tenant_id,
            metadata=meta,
        )
        _chat_trace_ctx.set(self)
        return self

    def end(self) -> None:
        client = get_client()
        if client:
            client.flush()
        _chat_trace_ctx.set(None)

    def log_llm(
        self,
        *,
        input_messages: list[dict],
        output: Any,
        model: str = "deepseek-chat",
        has_tools: bool = False,
        usage: dict | None = None,
        latency_ms: float | None = None,
    ) -> None:
        if not self._trace:
            return
        self._llm_round += 1
        gen_name = f"llm-round-{self._llm_round}" + ("-tools" if has_tools else "")
        meta: dict[str, Any] = {"has_tools": has_tools}
        if latency_ms is not None:
            meta["latency_ms"] = round(latency_ms, 2)
        gen = self._trace.generation(
            name=gen_name,
            model=model,
            input=_truncate({"messages": input_messages}),
            metadata=meta,
        )
        end_kwargs: dict[str, Any] = {"output": _truncate(output)}
        if usage:
            end_kwargs["usage"] = usage
        gen.end(**end_kwargs)

    def log_mcp(
        self,
        *,
        method: str,
        base_url: str,
        tool_name: str | None = None,
        input_data: Any = None,
        output: Any = None,
        error: str | None = None,
    ) -> None:
        if not self._trace:
            return
        span_name = f"mcp/{method}"
        if tool_name:
            span_name += f"/{tool_name}"
        span = self._trace.span(
            name=span_name,
            input=_truncate(input_data),
            metadata={
                "base_url": base_url,
                "method": method,
                "tool": tool_name,
            },
        )
        if error:
            span.end(output=_truncate(error), level="ERROR")
        else:
            span.end(output=_truncate(output))


@asynccontextmanager
async def chat_trace_scope(
    *,
    name: str,
    session_id: str,
    tenant_id: UUID | str | None = None,
    chat_type: str = "chat",
    metadata: dict | None = None,
):
    trace = ChatTrace(
        name=name,
        session_id=session_id,
        tenant_id=tenant_id,
        chat_type=chat_type,
        metadata=metadata,
    ).start()
    try:
        yield trace
    finally:
        trace.end()
