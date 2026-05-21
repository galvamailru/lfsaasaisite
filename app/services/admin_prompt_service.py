"""Промпт админ-бота: отдельный системный промпт (admin_system_prompt). Чанки — отдельно."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminPromptChunk, Tenant


async def get_admin_system_prompt(db: AsyncSession, tenant_id: UUID) -> str | None:
    """Системный промпт админ-бота для тенанта (из БД)."""
    r = await db.execute(select(Tenant.admin_system_prompt).where(Tenant.id == tenant_id))
    row = r.one_or_none()
    return row[0] if row else None


async def set_admin_system_prompt(db: AsyncSession, tenant_id: UUID, content: str | None) -> str | None:
    """Установить системный промпт админ-бота. Возвращает новое значение."""
    r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = r.scalar_one_or_none()
    if not tenant:
        return None
    tenant.admin_system_prompt = (content or "").strip() or None
    await db.flush()
    return tenant.admin_system_prompt


async def list_admin_chunks(db: AsyncSession, tenant_id: UUID) -> list[AdminPromptChunk]:
    """Чанки промпта админ-бота по position."""
    r = await db.execute(
        select(AdminPromptChunk)
        .where(AdminPromptChunk.tenant_id == tenant_id)
        .order_by(AdminPromptChunk.position, AdminPromptChunk.id)
    )
    return list(r.scalars().all())


async def create_admin_chunk(
    db: AsyncSession,
    tenant_id: UUID,
    content: str,
    position: int | None = None,
    question: str | None = None,
) -> AdminPromptChunk:
    """Добавить чанк. content — текст (без жёсткого лимита в БД)."""
    content = (content or "").strip()
    if not content:
        raise ValueError("content must not be empty")
    q = (question or "").strip()[:1000] or None
    if position is None:
        r = await db.execute(
            select(AdminPromptChunk)
            .where(AdminPromptChunk.tenant_id == tenant_id)
            .order_by(AdminPromptChunk.position.desc())
            .limit(1)
        )
        last = r.scalar_one_or_none()
        position = (last.position + 1) if last is not None else 0
    chunk = AdminPromptChunk(tenant_id=tenant_id, position=position, question=q, content=content)
    db.add(chunk)
    await db.flush()
    return chunk


async def update_admin_chunk(
    db: AsyncSession,
    tenant_id: UUID,
    chunk_id: UUID,
    content: str | None = None,
    position: int | None = None,
    question: str | None = None,
) -> AdminPromptChunk | None:
    """Обновить чанк."""
    r = await db.execute(
        select(AdminPromptChunk).where(
            AdminPromptChunk.id == chunk_id, AdminPromptChunk.tenant_id == tenant_id
        )
    )
    chunk = r.scalar_one_or_none()
    if not chunk:
        return None
    if content is not None:
        chunk.content = (content or "").strip()
    if position is not None:
        chunk.position = position
    if question is not None:
        chunk.question = (question or "").strip()[:1000] or None
    await db.flush()
    return chunk


async def delete_admin_chunk(db: AsyncSession, tenant_id: UUID, chunk_id: UUID) -> bool:
    """Удалить чанк."""
    r = await db.execute(
        select(AdminPromptChunk).where(
            AdminPromptChunk.id == chunk_id, AdminPromptChunk.tenant_id == tenant_id
        )
    )
    chunk = r.scalar_one_or_none()
    if not chunk:
        return False
    await db.delete(chunk)
    await db.flush()
    return True


def build_admin_prompt_from_chunks(chunks: list[AdminPromptChunk]) -> str:
    """Собрать текст из чанков: для каждого — вопрос и описание."""
    if not chunks:
        return ""
    lines = []
    for c in chunks:
        q = (c.question or "").strip()
        body = (c.content or "").strip()
        if q:
            lines.append(f"Вопрос для пользователя: {q}\nОписание/контекст: {body}")
        else:
            lines.append(body)
    return "\n\n".join(lines)
