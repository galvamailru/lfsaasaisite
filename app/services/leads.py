"""Извлечение контактов (email, телефон) из сообщений пользователя. Один лид на сессию (tenant_id, user_id, dialog_id)."""
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lead

EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)
PHONE_RE = re.compile(
    r"(?:\+7|8)?[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
    r"|\+\d{1,3}[\s\-]?\d{2,3}[\s\-]?\d{2,3}[\s\-]?\d{2,4}",
)


def _extract_contact_parts(text: str) -> list[str]:
    parts = []
    seen = set()
    for m in EMAIL_RE.finditer(text):
        s = m.group(0).strip().lower()
        if s and s not in seen:
            seen.add(s)
            parts.append(m.group(0).strip())
    for m in PHONE_RE.finditer(text):
        s = _normalize_contact(m.group(0))
        if s and s not in seen:
            seen.add(s)
            parts.append(m.group(0).strip())
    return parts


def _normalize_contact(s: str) -> str:
    s = s.strip().lower()
    digits = "".join(c for c in s if c.isdigit() or c == "+")
    if not digits:
        return s
    if digits.startswith("+7"):
        digits = "8" + digits[2:]
    elif digits.startswith("7") and len(digits) == 11:
        digits = "8" + digits[1:]
    if digits.startswith("8") and len(digits) == 11:
        return digits
    if len(digits) == 10 and digits[0] == "9":
        return "8" + digits
    return digits


def _merge_contacts(existing_text: str | None, new_parts: list[str]) -> str:
    seen = set()
    parts = []
    if existing_text:
        for p in (x.strip() for x in existing_text.split(" | ") if x.strip()):
            p_norm = _normalize_contact(p)
            if p_norm and p_norm not in seen:
                seen.add(p_norm)
                parts.append(p.strip())
    for p in new_parts:
        p = p.strip()
        if not p:
            continue
        p_norm = _normalize_contact(p)
        if p_norm and p_norm not in seen:
            seen.add(p_norm)
            parts.append(p)
    return " | ".join(parts)


async def save_lead_if_contact(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    dialog_id: UUID,
    user_message: str,
) -> bool:
    """Лид выставляется сервером при срабатывании regex на контакты (email/телефон) в сообщении пользователя. Отдельно от атрибута «просмотрен». Один лид на (tenant_id, user_id, dialog_id)."""
    new_parts = _extract_contact_parts(user_message)
    if not new_parts:
        return False
    result = await db.execute(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.user_id == user_id,
            Lead.dialog_id == dialog_id,
        )
    )
    existing = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing:
        merged = _merge_contacts(existing.contact_text, new_parts)
        if merged == existing.contact_text:
            return False
        existing.contact_text = merged
        existing.updated_at = now
        await db.flush()
        return True
    lead = Lead(
        tenant_id=tenant_id,
        user_id=user_id,
        dialog_id=dialog_id,
        contact_text=" | ".join(p.strip() for p in new_parts),
        created_at=now,
        updated_at=now,
    )
    db.add(lead)
    await db.flush()
    return True
