"""
Конвейер разбора команд пользовательского бота: блоки [EXECUTE]...[/EXECUTE].
Часть команд выполняется локально (лиды уже сохраняются при сообщении пользователя),
остальные вызывают API микросервисов (Gallery, RAG).
"""
import json
import re
import urllib.parse
from uuid import UUID

import httpx

from app.config import settings

EXECUTE_BLOCK_RE = re.compile(r"\[EXECUTE\](.*?)\[/EXECUTE\]", re.DOTALL | re.IGNORECASE)


def _parse_block(block_content: str) -> tuple[str, dict[str, str]]:
    """Первая строка — команда, остальные — key=value. Возвращает (command_upper, {key: value})."""
    lines = [s.strip() for s in block_content.strip().split("\n") if s.strip()]
    if not lines:
        return "", {}
    cmd = lines[0].upper()
    args = {}
    for line in lines[1:]:
        if "=" in line:
            k, _, v = line.partition("=")
            args[k.strip().lower()] = v.strip()
    return cmd, args


async def _call_gallery(path: str, method: str = "GET", json_body: dict | None = None) -> str:
    base = settings.gallery_service_url.rstrip("/")
    url = f"{base}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        if method == "GET":
            r = await client.get(url)
        elif method == "POST":
            r = await client.post(url, json=json_body or {})
        else:
            r = await client.request(method, url, json=json_body)
        r.raise_for_status()
        if r.content:
            return r.text
        return "OK"


async def _call_rag(path: str, method: str = "GET") -> str:
    base = settings.rag_service_url.rstrip("/")
    url = f"{base}{path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url) if method == "GET" else await client.request(method, url)
        r.raise_for_status()
        if r.content:
            return r.text
        return "OK"


async def run_user_command(tenant_id: UUID, block_content: str) -> str:
    """
    Выполняет одну команду из блока EXECUTE.
    tenant_id подставляется в вызовы микросервисов.
    Возвращает текстовый результат для подстановки в ответ пользователю.
    """
    cmd, args = _parse_block(block_content)
    tid = str(tenant_id)

    # --- Gallery ---
    if cmd == "LIST_GALLERIES":
        try:
            text = await _call_gallery(f"/api/v1/groups?tenant_id={tid}")
            data = json.loads(text)
            if not data:
                return "Пока нет ни одной галереи."
            lines = [f"• {g.get('name', '')} (id: {g.get('id')}) — {g.get('description', '') or 'без описания'}" for g in data]
            return "Список галерей:\n" + "\n".join(lines)
        except Exception as e:
            return f"Ошибка при запросе галерей: {e}"

    if cmd == "SHOW_GALLERY":
        gid = args.get("group_id")
        if not gid:
            return "Укажите group_id для SHOW_GALLERY."
        try:
            text = await _call_gallery(f"/api/v1/groups/{gid}")
            data = json.loads(text)
            name = data.get("name", "")
            images = data.get("images", [])
            if not images:
                return f"Галерея «{name}» пуста."
            base = settings.frontend_base_url.rstrip("/")
            urls = [
                f"{base}/api/v1/tenants/{tid}/me/gallery/groups/{gid}/images/{img.get('id', '')}/file"
                for img in images
            ]
            return f"Галерея «{name}»:\n" + "\n".join(urls)
        except Exception as e:
            return f"Ошибка: {e}"

    # --- RAG ---
    if cmd == "RAG_LIST_DOCUMENTS":
        try:
            text = await _call_rag(f"/api/v1/documents?tenant_id={tid}")
            data = json.loads(text)
            if not data:
                return "Пока нет документов в базе."
            lines = [f"• {d.get('name', '')} (id: {d.get('id')})" for d in data]
            return "Документы:\n" + "\n".join(lines)
        except Exception as e:
            return f"Ошибка при запросе документов: {e}"

    if cmd == "RAG_GET_DOCUMENT":
        doc_id = args.get("document_id")
        if not doc_id:
            return "Укажите document_id для RAG_GET_DOCUMENT."
        try:
            text = await _call_rag(f"/api/v1/documents/{doc_id}")
            data = json.loads(text)
            name = data.get("name", "")
            content = (data.get("content_md") or "")[:8000]
            return f"Документ «{name}»:\n\n{content}"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                try:
                    gtext = await _call_gallery(f"/api/v1/groups/{doc_id}")
                    gdata = json.loads(gtext)
                    name = gdata.get("name", "")
                    images = gdata.get("images", [])
                    if not images:
                        return f"Галерея «{name}» пуста."
                    base = settings.frontend_base_url.rstrip("/")
                    urls = [
                        f"{base}/api/v1/tenants/{tid}/me/gallery/groups/{doc_id}/images/{img.get('id', '')}/file"
                        for img in images
                    ]
                    return f"Галерея «{name}»:\n" + "\n".join(urls)
                except Exception:
                    pass
            return f"Ошибка: {e}"
        except Exception as e:
            return f"Ошибка: {e}"

    if cmd == "RAG_SEARCH":
        q = args.get("query") or args.get("q")
        if not q:
            return "Укажите query (или q) для RAG_SEARCH."
        try:
            text = await _call_rag(f"/api/v1/documents/search?tenant_id={tid}&q={urllib.parse.quote(q)}")
            data = json.loads(text)
            if not data:
                return "По запросу ничего не найдено."
            lines = [f"• {d.get('name', '')} (id: {d.get('id')})" for d in data]
            return "Найдено:\n" + "\n".join(lines)
        except Exception as e:
            return f"Ошибка поиска: {e}"

    return f"Неизвестная команда: {cmd}. Доступны: LIST_GALLERIES, SHOW_GALLERY, RAG_LIST_DOCUMENTS, RAG_GET_DOCUMENT, RAG_SEARCH."


def strip_execute_blocks(text: str) -> str:
    """Удаляет блоки [EXECUTE]...[/EXECUTE] из текста."""
    return EXECUTE_BLOCK_RE.sub("", text).strip()


async def process_user_reply(tenant_id: UUID, reply: str) -> str:
    """
    Обрабатывает ответ пользовательского бота: находит все [EXECUTE] блоки,
    выполняет команды, подставляет результаты в текст и убирает блоки.
    """
    if not reply or not reply.strip():
        return reply
    parts = []
    last_end = 0
    for m in EXECUTE_BLOCK_RE.finditer(reply):
        parts.append(reply[last_end : m.start()])
        block = m.group(1).strip()
        result = await run_user_command(tenant_id, block)
        parts.append("\n\n" + result + "\n\n")
        last_end = m.end()
    parts.append(reply[last_end:])
    return "".join(parts).strip()
