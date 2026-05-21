"""Админ-чат: диалог-помощник. Единый системный промпт админ-бота из БД или файла.
В ответе бота блок [SAVE_PROMPT]...[/SAVE_PROMPT] — сохранение промпта бота-пользователя в БД.
При валидации бот может вернуть JSON с полями validation и reason — парсим и отдаём во фронт."""
import json
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.llm_client import chat_once
from app.langfuse_tracing import chat_trace_scope
from app.services.prompt_loader import load_admin_prompt, load_test_prompt_for_tenant
from app.services.admin_prompt_service import get_admin_system_prompt
from app.services.cabinet_service import get_tenant_by_id
from app.services.microservices_client import gallery_request, rag_request

# Контекстное окно админ-чата: только последнее сообщение (проверка промпта без истории)
ADMIN_CHAT_CONTEXT_MESSAGE_LIMIT = 1

EXECUTE_BLOCK_RE = re.compile(r"\[EXECUTE\](.*?)\[/EXECUTE\]", re.DOTALL | re.IGNORECASE)
SAVE_PROMPT_RE = re.compile(r"\[SAVE_PROMPT\](.*?)\[/SAVE_PROMPT\]", re.DOTALL | re.IGNORECASE)

ADMIN_SYSTEM_PROMPT_FALLBACK = """Ты — Админ-помощник. Помогаешь настроить промпт чат-бота для клиентов. Промпт редактируется в разделе «Профиль» (системный промпт бота) и «Промпт админ-бота». Веди диалог пошагово, задавай уточняющие вопросы. Администратор команд не вводит."""


async def _get_admin_prompt_assembled(db: AsyncSession, tenant_id: UUID) -> str:
    """Системный промпт админ-бота: из БД (admin_system_prompt) или из файла по умолчанию."""
    system = await get_admin_system_prompt(db, tenant_id)
    if system and system.strip():
        return system.strip()
    try:
        return load_admin_prompt()
    except FileNotFoundError:
        return ADMIN_SYSTEM_PROMPT_FALLBACK


async def _fetch_galleries_and_documents(tenant_id: UUID) -> tuple[list[dict], list[dict]]:
    """Загружает список галерей и документов RAG тенанта для контекста админ-бота."""
    galleries: list[dict] = []
    documents: list[dict] = []
    try:
        status, text = await gallery_request(
            "GET", f"/api/v1/groups?tenant_id={tenant_id}", tenant_id
        )
        if status == 200 and text:
            data = json.loads(text)
            items = data if isinstance(data, list) else (data.get("items") or data.get("groups") or [])
            for g in items:
                if isinstance(g, dict):
                    galleries.append({"id": str(g.get("id", "")), "name": str(g.get("name") or g.get("title") or "Без названия")})
    except (json.JSONDecodeError, Exception):
        pass
    try:
        status, text = await rag_request(
            "GET", "/api/v1/documents", params={"tenant_id": str(tenant_id)}
        )
        if status == 200 and text:
            data = json.loads(text)
            items = data if isinstance(data, list) else (data.get("items") or data.get("documents") or [])
            for d in items:
                if isinstance(d, dict):
                    documents.append({"id": str(d.get("id", "")), "name": str(d.get("name") or d.get("title") or d.get("filename") or "Без названия")})
    except (json.JSONDecodeError, Exception):
        pass
    return galleries, documents


async def _get_client_system_prompt(db: AsyncSession, tenant_id: UUID) -> str:
    """Тестовый промпт бота-клиента (подставляется в контекст админ-бота для проверки)."""
    try:
        prompt = await load_test_prompt_for_tenant(db, tenant_id)
        return (prompt or "(пусто)").strip()
    except FileNotFoundError:
        return "(пусто)"


def _build_galleries_and_rag_tail(galleries: list[dict], documents: list[dict]) -> str:
    """
    Блок в конце промпта бота-администратора: списки галерей и документов RAG тенанта.
    Добавляется в конец промпта админ-бота.
    """
    lines = [
        "Список галерей изображений у тенанта (если в промпте бота-клиента нет сценария для галереи — предложи добавить):",
    ]
    if not galleries:
        lines.append("  (галерей пока нет)")
    else:
        for g in galleries:
            lines.append(f"  — id: {g['id']}, название: {g['name']}")

    lines.append("")
    lines.append("Список документов RAG у тенанта (если в промпте нет сценария использования документов — предложи добавить):")
    if not documents:
        lines.append("  (документов пока нет)")
    else:
        for d in documents:
            lines.append(f"  — id: {d['id']}, название: {d['name']}")

    return "\n".join(lines)


def _strip_execute_blocks(reply: str) -> str:
    return EXECUTE_BLOCK_RE.sub("", reply).strip()


def _strip_save_prompt_blocks(reply: str) -> str:
    return SAVE_PROMPT_RE.sub("", reply).strip()


async def _apply_save_prompt_blocks(db: AsyncSession, tenant_id: UUID, reply: str) -> tuple[str, bool]:
    """
    Ищет в reply блоки [SAVE_PROMPT]...[/SAVE_PROMPT], сохраняет содержимое в боевой промпт
    (tenant.system_prompt — используется в iframe/Telegram), с сохранением предыдущей версии для отката.
    Возвращает (reply без блоков, был ли хотя бы один сохранён).
    """
    saved = False
    for m in SAVE_PROMPT_RE.finditer(reply):
        content = (m.group(1) or "").strip()
        if not content:
            continue
        tenant = await get_tenant_by_id(db, tenant_id)
        if tenant is not None:
            # Боевой промпт — tenant.system_prompt (не тестовый settings['test_system_prompt'])
            prev = (getattr(tenant, "system_prompt", None) or "").strip() or None
            if prev and prev != content:
                settings = dict(tenant.settings or {})
                settings["prod_system_prompt_prev"] = prev
                tenant.settings = settings
                flag_modified(tenant, "settings")
            tenant.system_prompt = content or None
            await db.flush()
            saved = True
    cleaned = _strip_save_prompt_blocks(reply)
    return cleaned, saved


def _extract_validation(reply: str) -> tuple[str, bool | None, str | None]:
    """
    Ищет в ответе JSON с полями validation (bool) и reason (str).
    Поддерживает: чистый JSON, JSON внутри ```json ... ```, объект в тексте.
    Возвращает (reply_для_показа, validation, reason).
    """
    reply_clean = reply.strip()
    validation: bool | None = None
    reason: str | None = None

    def apply_validation(obj: dict) -> bool:
        nonlocal validation, reason, reply_clean
        if not isinstance(obj, dict) or "validation" not in obj:
            return False
        validation = bool(obj["validation"])
        reason = str(obj.get("reason") or "").strip() or None
        reply_clean = (
            ("Промпт требует доработки: " + reason) if not validation and reason
            else ("Валидация пройдена. " + (reason or "")) if validation else reply_clean
        )
        return True

    # 1) Пробуем распарсить весь ответ как JSON
    try:
        obj = json.loads(reply_clean)
        if apply_validation(obj):
            return reply_clean, validation, reason
    except (json.JSONDecodeError, TypeError):
        pass

    # 2) Извлекаем JSON из блока ```json ... ``` или ``` ... ```
    code_block_re = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
    for m in code_block_re.finditer(reply_clean):
        raw = m.group(1).strip()
        try:
            obj = json.loads(raw)
            if apply_validation(obj):
                reply_clean = code_block_re.sub("", reply_clean, count=1).strip()
                reply_clean = ("Промпт требует доработки: " + reason) if not validation and reason else ("Валидация пройдена. " + (reason or ""))
                return reply_clean, validation, reason
        except (json.JSONDecodeError, TypeError, IndexError):
            continue

    # 3) Ищем первый объект {...} с полем "validation" (по балансу скобок)
    start = reply_clean.find('{"validation"')
    if start == -1:
        start = reply_clean.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(reply_clean)):
            if reply_clean[i] == "{":
                depth += 1
            elif reply_clean[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(reply_clean[start : i + 1])
                        if apply_validation(obj):
                            before = reply_clean[:start].strip()
                            after = reply_clean[i + 1 :].strip()
                            summary = ("Промпт требует доработки: " + reason) if not validation and reason else ("Валидация пройдена. " + (reason or ""))
                            parts = [p for p in (before, summary, after) if p]
                            reply_clean = "\n\n".join(parts) if parts else summary
                            return reply_clean, validation, reason
                    except (json.JSONDecodeError, TypeError):
                        pass
                    break

    # 4) Regex для компактного JSON в одну строку
    pattern = re.compile(
        r'\{\s*"validation"\s*:\s*(true|false)\s*,\s*"reason"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(reply_clean)
    if m:
        validation = m.group(1).lower() == "true"
        reason = m.group(2).replace('\\"', '"').strip() or None
        before = reply_clean[: m.start()].strip()
        after = reply_clean[m.end() :].strip()
        summary = ("Промпт требует доработки: " + reason) if not validation and reason else ("Валидация пройдена. " + (reason or ""))
        parts = [p for p in (before, summary, after) if p]
        reply_clean = "\n\n".join(parts) if parts else (summary or reply_clean)

    # 5) Fallback: в тексте есть "validation": false — считаем валидацию не пройденной
    if validation is None and ('"validation": false' in reply_clean.lower() or '"validation":false' in reply_clean.lower()):
        validation = False
        reason_m = re.search(r'"reason"\s*:\s*"([^"]*)"', reply_clean)
        reason = reason_m.group(1).strip() if reason_m else None

    return reply_clean, validation, reason


async def handle_admin_message(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    message: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """
    Диалог админ-помощника. Бот использует единый системный промпт из БД или файла.
    Блоки [EXECUTE] в ответе удаляются (команды по чанкам отключены).
    """
    text = (message or "").strip()
    if not text:
        return "Напишите, чем могу помочь: настроить промпт бота для клиентов?"

    # Промпт админ-бота; в конец промпта админ-бота добавляются списки галерей и RAG
    admin_prompt = await _get_admin_prompt_assembled(db, tenant_id)
    galleries, documents = await _fetch_galleries_and_documents(tenant_id)
    admin_tail = _build_galleries_and_rag_tail(galleries, documents)
    client_prompt = await _get_client_system_prompt(db, tenant_id)

    # Итоговый system: промпт админ-бота + в конце блок галереи/RAG + промпт бота-клиента для проверки
    system_with_context = (
        admin_prompt.rstrip()
        + "\n\n---\n"
        + admin_tail
        + "\n\n---\nПромпт бота-клиента (для проверки):\n---\n"
        + client_prompt
    )
    request_context = admin_tail + "\n\n---\nПромпт бота-клиента (для проверки):\n---\n" + client_prompt

    # Контекстное окно: только последнее сообщение (1 сообщение)
    messages = []
    for h in (history or [])[-ADMIN_CHAT_CONTEXT_MESSAGE_LIMIT:]:
        role = h.get("role", "user")
        content = (h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text})

    session_key = f"admin_{user_id}"
    async with chat_trace_scope(
        name="admin-chat",
        session_id=session_key,
        tenant_id=tenant_id,
        chat_type="adminchat",
    ):
        raw_reply = (await chat_once(system_with_context, messages) or "").strip()
    reply = raw_reply
    reply = _strip_execute_blocks(reply)
    reply, saved = await _apply_save_prompt_blocks(db, tenant_id, reply)
    reply = reply.strip()
    # При сохранении промпта убираем из reply любое сообщение о сохранении, чтобы не дублировать зелёную рамку на фронте
    if saved:
        # Удаляем все строки, в которых есть и галочка, и "сохранён" (модель может добавить "АДМИН ПОМОЩНИК:" и т.д.)
        lines = [ln for ln in reply.split("\n") if "✓" not in ln or "сохранён" not in ln.lower()]
        reply = re.sub(r"\n\n\n+", "\n\n", "\n".join(lines)).strip()
        # Точно убираем типичные формулировки (целиком)
        for _phrase in (
            "✓ Промпт бота-пользователя сохранён. Проверьте страницу «Промпт» — там отображается текущий текст.",
            "✓ Промпт бота-пользователя сохранён. Проверьте страницу «Промпт».",
            '✓ Промпт бота-пользователя сохранён. Проверьте страницу "Промпт" — там отображается текущий текст.',
        ):
            reply = reply.replace(_phrase, "").strip()
        # Если после очистки осталось только короткое подтверждение — отдаём пустой reply
        if reply and "сохранён" in reply.lower() and ("промпт" in reply.lower() or "страниц" in reply.lower()) and len(reply) < 320:
            reply = ""

    reply, validation, validation_reason = _extract_validation(reply)
    reply = reply.strip()
    # При сохранении промпта пустой reply не подменяем на "Готово." — фронт покажет только зелёную рамку
    if not reply and not saved:
        reply = "Готово."

    return {
        "reply": reply,
        "validation": validation,
        "validation_reason": validation_reason,
        "prompt_saved": saved,
        "raw_reply": raw_reply,
        "request_system": system_with_context,
        "request_system_prompt": admin_prompt.rstrip(),
        "request_context": request_context,
        "request_messages": messages,
    }
