"""
MCP (Model Context Protocol) endpoint для RAG.
Экспортирует tools: list_documents, get_document, search_documents.
Транспорт: HTTP JSON-RPC 2.0 (POST /mcp).
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Document

router = APIRouter(tags=["mcp"])

MCP_TOOLS = [
    {
        "name": "list_documents",
        "description": "Получить список документов RAG тенанта (название и id).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "description": "UUID тенанта"},
            },
            "required": ["tenant_id"],
        },
    },
    {
        "name": "get_document",
        "description": "Получить содержимое документа по id (markdown, до 8000 символов).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "UUID документа"},
            },
            "required": ["document_id"],
        },
    },
    {
        "name": "search_documents",
        "description": "Поиск по документам тенанта (подстрока в содержимом).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "description": "UUID тенанта"},
                "query": {"type": "string", "description": "Поисковый запрос"},
            },
            "required": ["tenant_id", "query"],
        },
    },
]


def _mcp_response(id_: int | str | None, result: dict | None = None, error: dict | None = None) -> dict:
    out = {"jsonrpc": "2.0", "id": id_}
    if error:
        out["error"] = error
    else:
        out["result"] = result
    return out


@router.post("/mcp")
async def mcp_handler(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """JSON-RPC 2.0: initialize, tools/list, tools/call."""
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        return JSONResponse(
            _mcp_response(
                req_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "cip-rag", "version": "1.0.0"},
                }
            )
    )

    if method == "tools/list":
        return JSONResponse(_mcp_response(req_id, {"tools": MCP_TOOLS}))

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            return JSONResponse(
                _mcp_response(req_id, error={"code": -32602, "message": "Missing tool name"})
            )
        try:
            text = await _run_tool(db, name, arguments)
            return JSONResponse(
                _mcp_response(
                    req_id,
                    {"content": [{"type": "text", "text": text}]},
                )
            )
        except Exception as e:
            return JSONResponse(
                _mcp_response(
                    req_id,
                    error={"code": -32000, "message": str(e)},
                )
            )

    return JSONResponse(
        _mcp_response(req_id, error={"code": -32601, "message": f"Method not found: {method}"})
    )


async def _run_tool(db: AsyncSession, name: str, arguments: dict) -> str:
    if name == "list_documents":
        tid = arguments.get("tenant_id")
        if not tid:
            return "Ошибка: укажите tenant_id."
        try:
            tenant_uuid = UUID(tid)
        except ValueError:
            return "Ошибка: неверный формат tenant_id."
        r = await db.execute(
            select(Document)
            .where(Document.tenant_id == tenant_uuid)
            .order_by(Document.created_at.desc())
        )
        docs = list(r.scalars().all())
        if not docs:
            return "Пока нет документов в базе."
        lines = [f"• {d.name} (id: {d.id})" for d in docs]
        return "Документы:\n" + "\n".join(lines)

    if name == "get_document":
        doc_id = arguments.get("document_id")
        if not doc_id:
            return "Укажите document_id для get_document."
        try:
            doc_uuid = UUID(doc_id)
        except ValueError:
            return "Ошибка: неверный формат document_id."
        r = await db.execute(select(Document).where(Document.id == doc_uuid))
        doc = r.scalar_one_or_none()
        if not doc:
            return "Документ не найден."
        content = (doc.content_md or "")[:8000]
        return f"Документ «{doc.name}»:\n\n{content}"

    if name == "search_documents":
        tid = arguments.get("tenant_id")
        q = arguments.get("query", "").strip()
        if not tid:
            return "Ошибка: укажите tenant_id."
        if not q:
            return "Укажите query для search_documents."
        try:
            tenant_uuid = UUID(tid)
        except ValueError:
            return "Ошибка: неверный формат tenant_id."
        pattern = f"%{q}%"
        r = await db.execute(
            select(Document)
            .where(
                Document.tenant_id == tenant_uuid,
                Document.content_md.ilike(pattern),
            )
            .order_by(Document.created_at.desc())
        )
        docs = list(r.scalars().all())
        if not docs:
            return "По запросу ничего не найдено."
        lines = [f"• {d.name} (id: {d.id})" for d in docs]
        return "Найдено:\n" + "\n".join(lines)

    return f"Неизвестный инструмент: {name}. Доступны: list_documents, get_document, search_documents."
