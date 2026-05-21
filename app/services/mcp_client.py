"""
Клиент MCP: запрос tools/list и tools/call по произвольному base_url.
Встроенные инструменты Gallery и RAG (tenant_id подставляется на бэкенде).
Дополнительные MCP — из БД (страница «MCP серверы» в кабинете).
"""
import httpx

from app.config import settings

# Встроенные инструменты галереи и RAG — tenant_id не передаётся в LLM, подставляется при вызове
GALLERY_TOOL_NAMES = {"list_galleries", "show_gallery"}
RAG_TOOL_NAMES = {"list_documents", "get_document", "search_documents"}


def get_gallery_tools_for_llm() -> list[dict]:
    """Инструменты галереи для LLM: без параметра tenant_id (подставляется при вызове)."""
    return [
        {
            "type": "function",
            "function": {
                "name": "list_galleries",
                "description": "Получить список галерей изображений текущего пользователя. Возвращает название, id и описание каждой галереи. Используй при вопросах «какие галереи», «покажи галереи».",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "show_gallery",
                "description": "Показать содержимое галереи по id: список URL изображений. Используй после list_galleries, когда пользователь просит открыть конкретную галерею.",
                "parameters": {
                    "type": "object",
                    "properties": {"group_id": {"type": "string", "description": "UUID группы (галереи) из list_galleries"}},
                    "required": ["group_id"],
                },
            },
        },
    ]


def get_rag_tools_for_llm() -> list[dict]:
    """Инструменты RAG для LLM: без параметра tenant_id (подставляется при вызове)."""
    return [
        {
            "type": "function",
            "function": {
                "name": "list_documents",
                "description": "Получить список документов текущего пользователя (название и id). Используй при вопросах про документы, базу знаний.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_document",
                "description": "Получить содержимое документа по id (markdown).",
                "parameters": {
                    "type": "object",
                    "properties": {"document_id": {"type": "string", "description": "UUID документа из list_documents"}},
                    "required": ["document_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_documents",
                "description": "Поиск по документам текущего пользователя (подстрока в содержимом).",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Поисковый запрос"}},
                    "required": ["query"],
                },
            },
        },
    ]


async def call_gallery_tool(tenant_id, name: str, arguments: dict) -> str:
    """Вызов инструмента галереи: tenant_id подставляется автоматически."""
    args = dict(arguments)
    args["tenant_id"] = str(tenant_id)
    return await call_mcp_tool_by_url(settings.gallery_service_url, name, args)


async def call_rag_tool(tenant_id, name: str, arguments: dict) -> str:
    """Вызов инструмента RAG: tenant_id подставляется для list_documents и search_documents."""
    args = dict(arguments)
    if name in ("list_documents", "search_documents"):
        args["tenant_id"] = str(tenant_id)
    return await call_mcp_tool_by_url(settings.rag_service_url, name, args)


async def _mcp_request(url: str, method: str, params: dict | None = None) -> dict:
    """Отправляет JSON-RPC 2.0 запрос, возвращает result или поднимает ошибку."""
    from app.langfuse_tracing import get_active_trace

    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    base_url = url.removesuffix("/mcp") if url.endswith("/mcp") else url
    tool_name = (params or {}).get("name") if method == "tools/call" else None
    trace = get_active_trace()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
        if "error" in data:
            err = data["error"].get("message", "MCP error")
            if trace:
                trace.log_mcp(
                    method=method,
                    base_url=base_url,
                    tool_name=tool_name,
                    input_data=params,
                    error=err,
                )
            raise RuntimeError(err)
        result = data.get("result", {})
        if trace:
            trace.log_mcp(
                method=method,
                base_url=base_url,
                tool_name=tool_name,
                input_data=params,
                output=result,
            )
        return result
    except RuntimeError:
        raise
    except Exception as e:
        if trace:
            trace.log_mcp(
                method=method,
                base_url=base_url,
                tool_name=tool_name,
                input_data=params,
                error=str(e),
            )
        raise


def _mcp_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/mcp"


async def fetch_tools_from_url(base_url: str) -> list[dict]:
    """
    Запрашивает tools/list у MCP-сервера по base_url (например http://host:8010).
    Возвращает список сырых tools: [{"name", "description", "inputSchema"}, ...].
    При ошибке соединения возвращает [] или поднимает исключение — вызывающий код решает.
    """
    url = _mcp_url(base_url)
    try:
        result = await _mcp_request(url, "tools/list")
        return result.get("tools") or []
    except Exception:
        raise


async def call_mcp_tool_by_url(base_url: str, name: str, arguments: dict) -> str:
    """Вызывает tool по имени на произвольном MCP-сервере по base_url."""
    url = _mcp_url(base_url)
    result = await _mcp_request(url, "tools/call", {"name": name, "arguments": arguments})
    content = result.get("content") or []
    for part in content:
        if part.get("type") == "text":
            return part.get("text", "")
    return ""
