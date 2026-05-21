"""
Пользовательский чат с MCP: встроенные tools Gallery и RAG (tenant_id подставляется на бэкенде)
и динамические серверы из БД; цикл до финального ответа.
"""
import json
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm_client import chat_once_with_tools
from app.services.mcp_client import (
    GALLERY_TOOL_NAMES,
    RAG_TOOL_NAMES,
    call_gallery_tool,
    call_mcp_tool_by_url,
    call_rag_tool,
    fetch_tools_from_url,
    get_gallery_tools_for_llm,
    get_rag_tools_for_llm,
)
from app.services.cabinet_service import list_mcp_servers, get_mcp_server
from app.services.llm_exchange_logger import append_exchange
from app.langfuse_tracing import chat_trace_scope

MAX_TOOL_ROUNDS = 3
# Сколько последних сообщений диалога передавать в модель (контекстное окно)
CONTEXT_MESSAGE_LIMIT = 10


def _inject_base_url_to_image_paths(text: str, tenant_id: UUID) -> str:
    """Подставляет frontend_base_url в пути вида /api/v1/tenants/.../me/gallery/..."""
    base = (settings.frontend_base_url or "").rstrip("/")
    if not base:
        return text
    # Пути от show_gallery: /api/v1/tenants/{tid}/me/gallery/groups/.../file
    pattern = r"(?<![\"'])(/api/v1/tenants/[^/]+/me/gallery/[^\s\"']+)"
    def repl(m: re.Match) -> str:
        return base + m.group(1)
    return re.sub(pattern, repl, text)


# Блок, добавляемый к системному промпту: контекст тенанта, инструменты, изображения
_CONTEXT_TENANT_BLOCK = """

Контекст: диалог ведётся в рамках текущего тенанта (пользователя). Идентификатор тенанта уже известен системе и подставляется автоматически при вызове инструментов галереи и документов. Никогда не проси пользователя ввести tenant_id, UUID тенанта или другие внутренние идентификаторы. На вопросы «какие галереи», «покажи галереи», «какие документы» сразу вызывай инструменты list_galleries или list_documents соответственно.

Изображения из галереи: инструмент show_gallery возвращает список URL-путей изображений (каждая строка — один путь вида /api/v1/tenants/.../me/gallery/.../file). Формат отображения ссылок на изображения задаётся в системном промпте.
"""

# Контекст для запросов из Telegram-бота (добавляется в системный промпт)
_TELEGRAM_CONTEXT = "\n\nОбрати внимание! Этот запрос от телеграм бота."

_FORMAT_RULE = "\n\nФормат ответов: используй только Markdown (заголовки, списки, **жирный**, *курсив*, ссылки). Не используй блоки [HTML]...[/HTML]."

# Сообщение, которым заменяются блоки [HTML]...[/HTML] в истории: в модель они не отправляются, в логах видно, что было скрыто
_SANITIZED_BLOCK_PLACEHOLDER = "[[блок [HTML] в истории — в модель не передан]]"

_HTML_BLOCK_RE = re.compile(r"\[HTML\].*?\[/HTML\]", re.DOTALL | re.IGNORECASE)


def _strip_html_blocks_from_text(text: str) -> str:
    """Заменяет блоки [HTML]...[/HTML] на служебное сообщение; содержимое в модель не отправляется."""
    if not text or not isinstance(text, str):
        return text
    return _HTML_BLOCK_RE.sub(_SANITIZED_BLOCK_PLACEHOLDER, text).strip()


def _sanitize_messages_for_llm(messages: list[dict]) -> list[dict]:
    """
    Удаляет из сообщений ассистента блоки [HTML]...[/HTML] перед отправкой в модель:
    они заменяются на служебное сообщение, в модель не передаются.
    """
    out = []
    for m in messages:
        msg = dict(m)
        if (msg.get("role") or "").strip().lower() == "assistant":
            content = msg.get("content")
            if isinstance(content, str) and "[HTML]" in content.upper():
                msg["content"] = _strip_html_blocks_from_text(content)
        out.append(msg)
    return out


def _build_request_to_llm_text(prompt: str, messages: list[dict]) -> str:
    """Собирает текст запроса к LLM для логирования (в логах видно системный промпт и историю диалога)."""
    parts = [
        "[system]\n",
        prompt,
        "\n\n=== ИСТОРИЯ ДИАЛОГА (отправляется в модель) ===\n[messages]\n",
    ]
    for m in messages:
        role = m.get("role", "")
        content = m.get("content") or ""
        if isinstance(content, list):
            content = str(content)
        parts.append(f"{role}:\n{content}\n")
    return "".join(parts)


async def _get_all_tools_for_llm(tenant_id: UUID, db: AsyncSession) -> list[dict]:
    """Встроенные tools Gallery и RAG + включённые MCP-серверы из БД (префикс mcp_<id>__)."""
    out = []
    out.extend(get_gallery_tools_for_llm())
    out.extend(get_rag_tools_for_llm())
    servers = await list_mcp_servers(db, tenant_id)
    for s in servers:
        if not s.enabled:
            continue
        try:
            raw = await fetch_tools_from_url(s.base_url)
            for t in raw:
                name = t.get("name", "")
                if not name:
                    continue
                prefixed = f"mcp_{s.id}__{name}"
                desc = (t.get("description") or "").strip()
                schema = dict(t.get("inputSchema") or {})
                out.append({
                    "type": "function",
                    "function": {
                        "name": prefixed,
                        "description": desc or f"Инструмент {name} (сервер {s.name})",
                        "parameters": schema,
                    },
                })
        except Exception:
            continue
    return out


async def _call_tool(tenant_id: UUID, name: str, arguments: dict, db: AsyncSession) -> str:
    """Маршрутизация: встроенные Gallery/RAG (tenant_id подставляется) или MCP из БД (mcp_<id>__)."""
    if name in GALLERY_TOOL_NAMES:
        return await call_gallery_tool(tenant_id, name, arguments)
    if name in RAG_TOOL_NAMES:
        return await call_rag_tool(tenant_id, name, arguments)
    if name.startswith("mcp_") and "__" in name:
        prefix, inner_name = name.split("__", 1)
        server_id_str = prefix.replace("mcp_", "")
        try:
            server_uuid = UUID(server_id_str)
        except ValueError:
            return f"Ошибка: неверный идентификатор сервера в имени инструмента."
        server = await get_mcp_server(db, tenant_id, server_uuid)
        if not server:
            return f"Ошибка: MCP сервер не найден."
        try:
            return await call_mcp_tool_by_url(server.base_url, inner_name, arguments)
        except Exception as e:
            return f"Ошибка вызова инструмента: {e}"
    return f"Неизвестный инструмент: {name}."


async def run_user_chat_with_mcp_tools(
    tenant_id: UUID,
    system_prompt: str,
    messages: list[dict],
    db: AsyncSession,
    *,
    from_telegram: bool = False,
    is_admin: bool = False,
    is_test: bool = False,
    session_id: str | None = None,
) -> str:
    """
    Запускает диалог с моделью, передаёт tools только из MCP-серверов, добавленных в БД.
    При tool_calls выполняет вызовы через MCP и повторяет запрос (до 3 раундов).
    Возвращает финальный текст ответа (без tool_calls).
    Логирование: prodchat (iframe) и telegramchat (Telegram) — всегда; testchat — только при is_admin.
    При from_telegram в промпт добавляется контекст про Telegram.
    """
    tools = await _get_all_tools_for_llm(tenant_id, db)
    prompt_with_context = (system_prompt or "").strip() + _CONTEXT_TENANT_BLOCK + _FORMAT_RULE
    if from_telegram:
        prompt_with_context += _TELEGRAM_CONTEXT
    # Разделение логов: iframe → prodchat, Telegram → telegramchat, тест в кабинете → testchat
    if is_test:
        chat_type = "testchat"
    elif from_telegram:
        chat_type = "telegramchat"
    else:
        chat_type = "prodchat"
    log_session_id = session_id or "user"
    # prodchat и telegramchat логируем всегда; testchat — только для админа
    should_log = (chat_type in ("prodchat", "telegramchat")) or is_admin

    async with chat_trace_scope(
        name="user-chat",
        session_id=log_session_id,
        tenant_id=tenant_id,
        chat_type=chat_type,
        metadata={"is_admin": is_admin, "from_telegram": from_telegram},
    ):
        return await _run_user_chat_inner(
            tenant_id,
            prompt_with_context,
            messages,
            db,
            tools=tools,
            chat_type=chat_type,
            log_session_id=log_session_id,
            should_log=should_log,
            is_admin=is_admin,
        )


async def _run_user_chat_inner(
    tenant_id: UUID,
    prompt_with_context: str,
    messages: list[dict],
    db: AsyncSession,
    *,
    tools: list[dict],
    chat_type: str,
    log_session_id: str,
    should_log: bool,
    is_admin: bool,
) -> str:
    if not tools:
        from app.llm_client import chat_once
        current_messages = list(messages)[-CONTEXT_MESSAGE_LIMIT:]
        messages_for_llm = _sanitize_messages_for_llm(current_messages)
        request_text = _build_request_to_llm_text(prompt_with_context, messages_for_llm)
        result = await chat_once(prompt_with_context, messages_for_llm)
        if should_log:
            append_exchange(
                chat_type,
                tenant_id,
                log_session_id,
                request_text,
                result or "",
                is_new_session=True,
                is_admin=is_admin,
            )
        return result or ""

    # Контекстное окно: только последние N сообщений; блоки [HTML] в истории санитизируются — в модель не передаются
    current_messages = list(messages)[-CONTEXT_MESSAGE_LIMIT:]
    round_index = 0
    for _ in range(MAX_TOOL_ROUNDS):
        messages_for_llm = _sanitize_messages_for_llm(current_messages)
        request_text = _build_request_to_llm_text(prompt_with_context, messages_for_llm)
        out = await chat_once_with_tools(prompt_with_context, messages_for_llm, tools)
        content = out.get("content") or ""
        tool_calls = out.get("tool_calls")
        response_for_log = content
        if tool_calls:
            response_for_log += "\n[tool_calls]\n" + "\n".join(
                f"  {tc.get('name', '')}(...)" for tc in tool_calls
            )
        if should_log:
            append_exchange(
                chat_type,
                tenant_id,
                log_session_id,
                request_text,
                response_for_log,
                is_new_session=(round_index == 0),
                is_admin=is_admin,
            )
        round_index += 1

        if not tool_calls:
            return _inject_base_url_to_image_paths(content, tenant_id)

        # Формат assistant message с tool_calls для следующего запроса
        assistant_msg = {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]) if isinstance(tc.get("arguments"), dict) else (tc.get("arguments") or "{}"),
                    },
                }
                for tc in tool_calls
            ],
        }
        current_messages.append(assistant_msg)

        for tc in tool_calls:
            tid = tc["id"]
            name = tc.get("name") or ""
            arguments = tc.get("arguments") or {}
            try:
                result = await _call_tool(tenant_id, name, arguments, db)
            except Exception as e:
                result = f"Ошибка: {e}"
            current_messages.append({
                "role": "tool",
                "tool_call_id": tid,
                "content": result,
            })

    return content or "Достигнут лимит вызовов инструментов."

