"""LangFuse SDK v3: трассировка LLM (DeepSeek) и MCP. Совместимо с LangFuse server 3."""
from __future__ import annotations

import contextvars
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from app.config import settings

_log = logging.getLogger("app.langfuse")

_chat_trace_ctx: contextvars.ContextVar["ChatTrace | None"] = contextvars.ContextVar(
    "chat_trace", default=None
)


def _base_url() -> str:
    return (settings.langfuse_base_url or settings.langfuse_host or "").rstrip("/")


def is_enabled() -> bool:
    return bool(
        settings.langfuse_enabled
        and settings.langfuse_public_key.strip()
        and settings.langfuse_secret_key.strip()
        and _base_url()
    )


def _sync_env_from_settings() -> None:
    """get_client() читает LANGFUSE_* из окружения — синхронизируем с .env / compose."""
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key.strip()
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key.strip()
    os.environ["LANGFUSE_BASE_URL"] = _base_url()


def get_client():
    if not is_enabled():
        return None
    try:
        _sync_env_from_settings()
        from langfuse import get_client as lf_get_client

        return lf_get_client()
    except Exception as e:
        _log.warning("LangFuse client init failed: %s", e)
        return None


def get_active_trace() -> "ChatTrace | None":
    return _chat_trace_ctx.get()


def log_startup_status() -> None:
    if not is_enabled():
        _log.info(
            "LangFuse tracing disabled (enabled=%s, host/base_url set=%s, keys set=%s)",
            settings.langfuse_enabled,
            bool(_base_url()),
            bool(settings.langfuse_public_key and settings.langfuse_secret_key),
        )
        return
    _log.info("LangFuse tracing enabled, base_url=%s", _base_url())


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


def _usage_details(usage: dict | None) -> dict | None:
    if not usage:
        return None
    out: dict[str, int] = {}
    if "prompt_tokens" in usage:
        out["input"] = int(usage["prompt_tokens"])
    if "completion_tokens" in usage:
        out["output"] = int(usage["completion_tokens"])
    if "total_tokens" in usage:
        out["total"] = int(usage["total_tokens"])
    return out or None


class ChatTrace:
    """Корневой span на один запрос чата; вложенные generation/span через OTEL-контекст."""

    def __init__(self, *, disabled: bool = False):
        self._disabled = disabled
        self._llm_round = 0
        self._propagator = None
        self._root_cm = None

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
        if self._disabled:
            return
        client = get_client()
        if not client:
            return
        self._llm_round += 1
        gen_name = f"llm-round-{self._llm_round}" + ("-tools" if has_tools else "")
        meta: dict[str, Any] = {"has_tools": has_tools}
        if latency_ms is not None:
            meta["latency_ms"] = round(latency_ms, 2)
        try:
            with client.start_as_current_observation(
                as_type="generation",
                name=gen_name,
                model=model,
                metadata=meta,
            ) as gen:
                gen.update(
                    input=_truncate({"messages": input_messages}),
                    output=_truncate(output),
                    usage_details=_usage_details(usage),
                )
        except Exception as e:
            _log.warning("LangFuse log_llm failed: %s", e)

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
        if self._disabled:
            return
        client = get_client()
        if not client:
            return
        span_name = f"mcp/{method}"
        if tool_name:
            span_name += f"/{tool_name}"
        try:
            with client.start_as_current_observation(
                as_type="span",
                name=span_name,
                metadata={"base_url": base_url, "method": method, "tool": tool_name},
            ) as span:
                if error:
                    span.update(
                        input=_truncate(input_data),
                        output=_truncate(error),
                        metadata={"error": "true"},
                    )
                else:
                    span.update(input=_truncate(input_data), output=_truncate(output))
        except Exception as e:
            _log.warning("LangFuse log_mcp failed: %s", e)


@asynccontextmanager
async def chat_trace_scope(
    *,
    name: str,
    session_id: str,
    tenant_id: UUID | str | None = None,
    chat_type: str = "chat",
    metadata: dict | None = None,
):
    if not is_enabled():
        yield ChatTrace(disabled=True)
        return

    client = get_client()
    if not client:
        yield ChatTrace(disabled=True)
        return

    from langfuse import propagate_attributes

    raw_meta = {**(metadata or {}), "chat_type": chat_type}
    if tenant_id:
        raw_meta["tenant_id"] = str(tenant_id)
    # LangFuse metadata — только строки (иначе ingestion может падать с 500)
    meta = {k: str(v) for k, v in raw_meta.items()}
    user_id = str(tenant_id) if tenant_id else None

    trace = ChatTrace(disabled=False)
    _chat_trace_ctx.set(trace)

    propagator = propagate_attributes(
        session_id=session_id,
        user_id=user_id,
        metadata=meta,
    )
    root_cm = client.start_as_current_observation(
        as_type="span",
        name=name,
        metadata=meta,
    )
    propagator.__enter__()
    root_cm.__enter__()
    try:
        yield trace
    finally:
        try:
            root_cm.__exit__(None, None, None)
        except Exception as e:
            _log.warning("LangFuse root span close failed: %s", e)
        try:
            propagator.__exit__(None, None, None)
        except Exception as e:
            _log.warning("LangFuse propagate_attributes close failed: %s", e)
        try:
            client.flush()
        except Exception as e:
            _log.warning("LangFuse flush failed: %s", e)
        _chat_trace_ctx.set(None)
