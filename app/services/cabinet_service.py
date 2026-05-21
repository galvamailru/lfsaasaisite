"""Cabinet: dialogs list, dialog detail, saved items, profile."""
import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.models import Dialog, DialogView, Lead, McpServer, Message, SavedItem, UserProfile
from app.services.auth_service import get_tenant_user_by_id, get_tenant_user_by_primary_key


PREVIEW_MAX_LEN = 120


async def is_user_admin_for_tenant(
    db: AsyncSession, tenant_id: UUID, user_id_str: str
) -> bool:
    """
    Проверяет, является ли пользователь администратором (для текущего или домашнего тенанта).
    Используется для включения логирования обменов с DeepSeek только для админов.
    """
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        return False
    admin_slug = (app_settings.admin_tenant_slug or "").strip()
    if not admin_slug:
        return False
    if tenant.slug == admin_slug:
        return True
    try:
        uid = UUID(user_id_str)
    except ValueError:
        return False
    home_user = await get_tenant_user_by_primary_key(db, uid)
    if not home_user:
        return False
    home_tenant = await get_tenant_by_id(db, home_user.tenant_id)
    return bool(home_tenant and home_tenant.slug == admin_slug)


async def get_tenant_by_slug(db: AsyncSession, slug: str):
    from app.models import Tenant
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    return result.scalar_one_or_none()


async def get_tenant_by_id(db: AsyncSession, tenant_id: UUID):
    from app.models import Tenant
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none()


async def get_first_confirmed_user_of_tenant(db: AsyncSession, tenant_id: UUID):
    """Первый подтверждённый пользователь тенанта (для входа администратора в кабинет тенанта)."""
    from app.models import TenantUser
    result = await db.execute(
        select(TenantUser)
        .where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.email_confirmed_at.isnot(None),
        )
        .order_by(TenantUser.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_all_tenants(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
) -> tuple[int, list]:
    """Список тенантов с пагинацией и поиском по slug/названию (для страницы «Пользователи»). Возвращает (total, list)."""
    from app.models import Tenant
    condition = True
    if search and search.strip():
        term = "%" + search.strip() + "%"
        condition = or_(
            Tenant.slug.ilike(term),
            Tenant.name.ilike(term),
        )
    count_q = select(func.count()).select_from(Tenant).where(condition)
    total = (await db.execute(count_q)).scalar() or 0
    q = select(Tenant).where(condition).order_by(Tenant.slug).limit(limit).offset(offset)
    result = await db.execute(q)
    return total, list(result.scalars().all())


async def list_dialogs(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    limit: int,
    offset: int,
) -> tuple[int, list]:
    count_q = select(func.count()).select_from(Dialog).where(
        Dialog.tenant_id == tenant_id,
        Dialog.user_id == user_id,
    )
    total = (await db.execute(count_q)).scalar() or 0
    q = (
        select(Dialog)
        .where(Dialog.tenant_id == tenant_id, Dialog.user_id == user_id)
        .order_by(Dialog.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(q)
    dialogs = result.scalars().all()
    items = []
    for d in dialogs:
        preview = None
        msg_q = (
            select(Message.content)
            .where(Message.dialog_id == d.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        msg_result = await db.execute(msg_q)
        row = msg_result.scalar_one_or_none()
        if row:
            preview = (row[0] or "")[:PREVIEW_MAX_LEN] or None
        items.append({"dialog": d, "preview": preview})
    return total, items


async def list_tenant_dialogs(
    db: AsyncSession,
    tenant_id: UUID,
    cabinet_user_id: str,
    limit: int,
    offset: int,
    date_from: date | None = None,
    date_to: date | None = None,
    only_new: bool = False,
    only_leads: bool = False,
    include_archived: bool = False,
) -> tuple[int, list]:
    """Все диалоги тенанта. По умолчанию архивные не показываются. Просмотренность — по текущему пользователю кабинета. Лид (has_lead) выставляется сервером при срабатывании regex на контакты."""
    count_q = select(func.count()).select_from(Dialog).where(Dialog.tenant_id == tenant_id)
    q = select(Dialog).where(Dialog.tenant_id == tenant_id)
    if not include_archived:
        count_q = count_q.where(Dialog.archived == False)  # noqa: E712
        q = q.where(Dialog.archived == False)  # noqa: E712
    if date_from is not None:
        dt_from = datetime.combine(date_from, datetime.min.time())
        count_q = count_q.where(Dialog.updated_at >= dt_from)
        q = q.where(Dialog.updated_at >= dt_from)
    if date_to is not None:
        dt_to = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
        count_q = count_q.where(Dialog.updated_at < dt_to)
        q = q.where(Dialog.updated_at < dt_to)
    if only_new:
        viewed_by_me = exists().where(
            DialogView.dialog_id == Dialog.id,
            DialogView.tenant_id == tenant_id,
            DialogView.cabinet_user_id == cabinet_user_id,
        )
        count_q = count_q.where(~viewed_by_me)
        q = q.where(~viewed_by_me)
    if only_leads:
        lead_exists = exists().where(Lead.dialog_id == Dialog.id, Lead.tenant_id == tenant_id)
        count_q = count_q.where(lead_exists)
        q = q.where(lead_exists)
    total = (await db.execute(count_q)).scalar() or 0
    q = q.order_by(Dialog.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    dialogs = result.scalars().all()
    dialog_ids = [d.id for d in dialogs]
    viewed_map: dict[UUID, datetime] = {}
    if dialog_ids:
        dv_result = await db.execute(
            select(DialogView.dialog_id, DialogView.viewed_at).where(
                DialogView.tenant_id == tenant_id,
                DialogView.cabinet_user_id == cabinet_user_id,
                DialogView.dialog_id.in_(dialog_ids),
            )
        )
        for row in dv_result.all():
            viewed_map[row[0]] = row[1]
    items = []
    for d in dialogs:
        preview = None
        msg_q = (
            select(Message.content)
            .where(Message.dialog_id == d.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        msg_result = await db.execute(msg_q)
        row = msg_result.scalar_one_or_none()
        if row:
            preview = (row[0] or "")[:PREVIEW_MAX_LEN] or None
        cnt_result = await db.execute(select(func.count()).select_from(Message).where(Message.dialog_id == d.id))
        message_count = cnt_result.scalar() or 0
        lead_exists = await db.execute(select(exists().where(Lead.dialog_id == d.id, Lead.tenant_id == tenant_id)))
        has_lead = lead_exists.scalar() or False
        items.append({
            "dialog": d,
            "preview": preview,
            "message_count": message_count,
            "has_lead": has_lead,
            "viewed_at": viewed_map.get(d.id),
        })
    return total, items


async def get_dialog_by_id(db: AsyncSession, tenant_id: UUID, dialog_id: UUID):
    """Получить диалог по id в рамках тенанта."""
    result = await db.execute(
        select(Dialog).where(Dialog.id == dialog_id, Dialog.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def archive_dialog(db: AsyncSession, tenant_id: UUID, dialog_id: UUID) -> bool:
    """Перевести диалог в архив. Возвращает True если диалог найден и обновлён."""
    dialog = await get_dialog_by_id(db, tenant_id, dialog_id)
    if not dialog:
        return False
    dialog.archived = True
    await db.flush()
    return True


async def delete_dialog(db: AsyncSession, tenant_id: UUID, dialog_id: UUID) -> bool:
    """Удалить диалог и все связанные сообщения/просмотры/лиды. Возвращает True если диалог найден и удалён."""
    dialog = await get_dialog_by_id(db, tenant_id, dialog_id)
    if not dialog:
        return False
    await db.delete(dialog)
    await db.flush()
    return True


async def mark_dialog_viewed(
    db: AsyncSession,
    tenant_id: UUID,
    cabinet_user_id: str,
    dialog_id: UUID,
) -> datetime | None:
    """Пометить диалог как просмотренный данным пользователем кабинета. Все диалоги, которые он открывал, остаются в списке прочитанных."""
    now = datetime.now(timezone.utc)
    r = await db.execute(
        select(DialogView).where(
            DialogView.tenant_id == tenant_id,
            DialogView.cabinet_user_id == cabinet_user_id,
            DialogView.dialog_id == dialog_id,
        )
    )
    existing = r.scalar_one_or_none()
    if existing:
        existing.viewed_at = now
        await db.flush()
        return now
    dv = DialogView(
        tenant_id=tenant_id,
        cabinet_user_id=cabinet_user_id,
        dialog_id=dialog_id,
        viewed_at=now,
    )
    db.add(dv)
    await db.flush()
    return now


async def get_dialog_messages(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    dialog_id: UUID,
) -> list | None:
    result = await db.execute(
        select(Dialog).where(
            Dialog.id == dialog_id,
            Dialog.tenant_id == tenant_id,
            Dialog.user_id == user_id,
        )
    )
    dialog = result.scalar_one_or_none()
    if not dialog:
        return None
    msg_result = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog_id, Message.tenant_id == tenant_id)
        .order_by(Message.created_at)
    )
    return list(msg_result.scalars().all())


async def get_dialog_messages_for_tenant(
    db: AsyncSession,
    tenant_id: UUID,
    dialog_id: UUID,
) -> list | None:
    """Сообщения диалога по tenant_id и dialog_id (админ может открыть любой диалог тенанта)."""
    result = await db.execute(
        select(Dialog).where(
            Dialog.id == dialog_id,
            Dialog.tenant_id == tenant_id,
        )
    )
    if not result.scalar_one_or_none():
        return None
    msg_result = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog_id, Message.tenant_id == tenant_id)
        .order_by(Message.created_at)
    )
    return list(msg_result.scalars().all())


async def list_saved(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    limit: int,
    offset: int,
) -> tuple[int, list]:
    count_q = select(func.count()).select_from(SavedItem).where(
        SavedItem.tenant_id == tenant_id,
        SavedItem.user_id == user_id,
    )
    total = (await db.execute(count_q)).scalar() or 0
    q = (
        select(SavedItem)
        .where(SavedItem.tenant_id == tenant_id, SavedItem.user_id == user_id)
        .order_by(SavedItem.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(q)
    items = list(result.scalars().all())
    return total, items


async def get_saved_by_id(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    saved_id: UUID,
) -> SavedItem | None:
    result = await db.execute(
        select(SavedItem).where(
            SavedItem.id == saved_id,
            SavedItem.tenant_id == tenant_id,
            SavedItem.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_leads(
    db: AsyncSession,
    tenant_id: UUID,
    limit: int,
    offset: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[int, list]:
    count_q = select(func.count()).select_from(Lead).where(Lead.tenant_id == tenant_id)
    q = select(Lead).where(Lead.tenant_id == tenant_id)
    if date_from is not None:
        dt_from = datetime.combine(date_from, datetime.min.time())
        count_q = count_q.where(Lead.updated_at >= dt_from)
        q = q.where(Lead.updated_at >= dt_from)
    if date_to is not None:
        dt_to = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
        count_q = count_q.where(Lead.updated_at < dt_to)
        q = q.where(Lead.updated_at < dt_to)
    total = (await db.execute(count_q)).scalar() or 0
    q = q.order_by(Lead.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return total, list(result.scalars().all())


async def get_profile(db: AsyncSession, tenant_id: UUID, user_id: str) -> UserProfile | None:
    result = await db.execute(
        select(UserProfile).where(
            UserProfile.tenant_id == tenant_id,
            UserProfile.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_profile(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    display_name: str | None = None,
    contact: str | None = None,
) -> UserProfile:
    profile = await get_profile(db, tenant_id, user_id)
    if profile is None:
        profile = UserProfile(tenant_id=tenant_id, user_id=user_id)
        db.add(profile)
        await db.flush()
    if display_name is not None:
        profile.display_name = display_name
    if contact is not None:
        profile.contact = contact
    await db.flush()
    return profile


# MCP servers
async def list_mcp_servers(db: AsyncSession, tenant_id: UUID) -> list[McpServer]:
    result = await db.execute(
        select(McpServer).where(McpServer.tenant_id == tenant_id).order_by(McpServer.created_at.desc())
    )
    return list(result.scalars().all())


async def get_mcp_server(db: AsyncSession, tenant_id: UUID, server_id: UUID) -> McpServer | None:
    result = await db.execute(
        select(McpServer).where(
            McpServer.id == server_id,
            McpServer.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


def _get_default_mcp_servers() -> list[tuple[str, str]]:
    """Список MCP-серверов по умолчанию из .env (default_mcp_servers — JSON-массив пар [название, url])."""
    try:
        raw = json.loads(app_settings.default_mcp_servers or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    result: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            name = str(item[0]).strip()
            url = str(item[1]).strip()
            if name and url:
                result.append((name, url))
    return result


async def create_default_mcp_servers_for_tenant(db: AsyncSession, tenant_id: UUID) -> None:
    """Создать для тенанта MCP-серверы по умолчанию из .env (default_mcp_servers)."""
    for name, base_url in _get_default_mcp_servers():
        s = McpServer(tenant_id=tenant_id, name=name, base_url=base_url, enabled=True)
        db.add(s)
    await db.flush()


async def create_mcp_server(
    db: AsyncSession,
    tenant_id: UUID,
    name: str,
    base_url: str,
    enabled: bool = True,
) -> McpServer:
    s = McpServer(tenant_id=tenant_id, name=name.strip(), base_url=base_url.strip(), enabled=enabled)
    db.add(s)
    await db.flush()
    return s


async def update_mcp_server(
    db: AsyncSession,
    server: McpServer,
    name: str | None = None,
    base_url: str | None = None,
    enabled: bool | None = None,
) -> McpServer:
    if name is not None:
        server.name = name.strip()
    if base_url is not None:
        server.base_url = base_url.strip()
    if enabled is not None:
        server.enabled = enabled
    await db.flush()
    return server


async def delete_mcp_server(db: AsyncSession, server: McpServer) -> None:
    await db.delete(server)
    await db.flush()
