"""Прокси-вызовы к микросервисам Gallery и RAG из кабинета (JWT + tenant_id)."""
import logging
from uuid import UUID

import httpx

from app.config import settings

_log = logging.getLogger(__name__)


async def gallery_request(
    method: str,
    path: str,
    tenant_id: UUID,
    json_body: dict | None = None,
    files: dict | None = None,
) -> tuple[int, str]:
    """Вызов API галереи. path без ведущего слэша. Возвращает (status_code, text)."""
    base = settings.gallery_service_url.rstrip("/")
    url = f"{base}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                r = await client.get(url)
            elif method == "POST":
                if files:
                    r = await client.post(url, files=files)
                else:
                    r = await client.post(url, json=json_body or {})
            elif method == "PATCH":
                r = await client.patch(url, json=json_body or {})
            elif method == "DELETE":
                r = await client.delete(url)
            else:
                r = await client.request(method, url, json=json_body)
            return r.status_code, r.text
    except Exception as e:
        _log.warning("gallery_request failed: url=%s method=%s error=%s", url, method, e)
        raise


async def gallery_get_file(path: str) -> tuple[int, bytes, str | None]:
    """GET бинарного файла из галереи. Возвращает (status_code, content, content_type)."""
    base = settings.gallery_service_url.rstrip("/")
    url = f"{base}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            ct = r.headers.get("content-type")
            return r.status_code, r.content, ct
    except Exception as e:
        _log.warning("gallery_get_file failed: url=%s error=%s", url, e)
        raise


# Таймаут для RAG: конвертация PDF (docling) может занимать несколько минут на больших файлах
RAG_TIMEOUT = httpx.Timeout(60.0, read=600.0)  # connect 60s, read 10 min


async def rag_request(
    method: str,
    path: str,
    params: dict | None = None,
    files: dict | None = None,
    data: dict | None = None,
) -> tuple[int, str]:
    """Вызов API RAG. Возвращает (status_code, text)."""
    base = settings.rag_service_url.rstrip("/")
    url = f"{base}{path}"
    try:
        async with httpx.AsyncClient(timeout=RAG_TIMEOUT) as client:
            if method == "GET":
                r = await client.get(url, params=params)
            elif method == "POST":
                if files:
                    r = await client.post(url, params=params, files=files, data=data)
                else:
                    r = await client.post(url, params=params, json=data or {})
            elif method == "DELETE":
                r = await client.delete(url)
            else:
                r = await client.request(method, url, params=params, json=data)
            return r.status_code, r.text
    except Exception as e:
        _log.warning("rag_request failed: url=%s method=%s error=%s", url, method, e)
        raise
