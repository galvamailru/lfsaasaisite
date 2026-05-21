"""
MCP (Model Context Protocol) endpoint для галереи.
Экспортирует tools: list_galleries, show_gallery.
Транспорт: HTTP JSON-RPC 2.0 (POST /mcp).
"""
import json
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import GalleryGroup, GalleryImage

router = APIRouter(tags=["mcp"])

MCP_TOOLS = [
    {
        "name": "list_galleries",
        "description": "Получить список галерей изображений тенанта. Возвращает название, id и описание каждой галереи.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "description": "UUID тенанта"},
            },
            "required": ["tenant_id"],
        },
    },
    {
        "name": "show_gallery",
        "description": "Показать содержимое галереи по id: список URL изображений. Используй после list_galleries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "description": "UUID тенанта"},
                "group_id": {"type": "string", "description": "UUID группы (галереи)"},
            },
            "required": ["tenant_id", "group_id"],
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
                    "serverInfo": {"name": "cip-gallery", "version": "1.0.0"},
                }
            )
    )

    if method == "tools/list":
        return JSONResponse(
            _mcp_response(req_id, {"tools": MCP_TOOLS})
        )

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
    tid = arguments.get("tenant_id")
    if not tid:
        return "Ошибка: укажите tenant_id."
    try:
        tenant_uuid = UUID(tid)
    except ValueError:
        return "Ошибка: неверный формат tenant_id."

    if name == "list_galleries":
        r = await db.execute(
            select(GalleryGroup)
            .where(GalleryGroup.tenant_id == tenant_uuid)
            .order_by(GalleryGroup.created_at.desc())
        )
        groups = list(r.scalars().all())
        if not groups:
            return "Пока нет ни одной галереи."
        lines = [
            f"• {g.name} (id: {g.id}) — {g.description or 'без описания'}"
            for g in groups
        ]
        return "Список галерей:\n" + "\n".join(lines)

    if name == "show_gallery":
        gid = arguments.get("group_id")
        if not gid:
            return "Укажите group_id для show_gallery."
        try:
            group_uuid = UUID(gid)
        except ValueError:
            return "Ошибка: неверный формат group_id."
        r = await db.execute(select(GalleryGroup).where(GalleryGroup.id == group_uuid))
        group = r.scalar_one_or_none()
        if not group:
            return "Галерея не найдена."
        r2 = await db.execute(
            select(GalleryImage)
            .where(GalleryImage.group_id == group_uuid)
            .order_by(GalleryImage.created_at)
        )
        images = list(r2.scalars().all())
        if not images:
            return f"Галерея «{group.name}» пуста."
        # URL для получения файла через основное приложение (клиент подставит base)
        paths = [
            f"/api/v1/tenants/{tid}/me/gallery/groups/{gid}/images/{img.id}/file"
            for img in images
        ]
        return f"Галерея «{group.name}»:\n" + "\n".join(paths)

    return f"Неизвестный инструмент: {name}. Доступны: list_galleries, show_gallery."
