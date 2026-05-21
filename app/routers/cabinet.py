"""Cabinet: только для зарегистрированных (JWT). Диалоги, чанки промпта, вставка на сайт, админ-чат, галерея, RAG, профиль."""
import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings as app_settings
from app.services.auth_service import decode_jwt, get_tenant_user_by_id, get_tenant_user_by_primary_key
from app.services.test_chat_history import clear_tenant_test_history
from app.services.chat_service import clear_tenant_prod_history
from app.schemas import (
    DialogDetailResponse,
    DialogListResponse,
    DialogListItem,
    LeadResponse,
    MessageInDialog,
    ProfileResponse,
    ProfileUpdate,
    SavedItemCreate,
    SavedItemResponse,
    AdminPromptResponse,
    AdminPromptUpdate,
    EmbedCodeResponse,
    AdminChatRequest,
    AdminChatResponse,
    McpServerCreate,
    McpServerUpdate,
    McpServerResponse,
    McpToolInfo,
    LimitsResponse,
    LimitsUpdate,
    TenantWithLimitsItem,
    BlockTenantUpdate,
    WelcomeMessageUpdate,
)
from app.services.auth_service import create_impersonation_ticket
from app.services.cabinet_service import (
    archive_dialog,
    delete_dialog,
    get_dialog_by_id,
    get_dialog_messages,
    get_dialog_messages_for_tenant,
    get_profile,
    get_saved_by_id,
    get_tenant_by_id,
    get_tenant_by_slug,
    is_user_admin_for_tenant,
    list_all_tenants,
    list_dialogs,
    list_leads,
    list_mcp_servers,
    get_mcp_server,
    create_mcp_server,
    update_mcp_server,
    delete_mcp_server,
    list_saved,
    list_tenant_dialogs,
    mark_dialog_viewed,
    upsert_profile,
)
from app.services.mcp_client import fetch_tools_from_url
from app.models import SavedItem
from app.services.prompt_loader import load_prompt, load_admin_prompt
from app.services.admin_prompt_service import get_admin_system_prompt, set_admin_system_prompt
from app.services.admin_chat_service import handle_admin_message
from app.services.admin_chat_logger import append_admin_chat_exchange

router = APIRouter(prefix="/api/v1/tenants", tags=["cabinet"])

# Значения лимитов по умолчанию (могут быть переопределены в tenant.settings)
DEFAULT_CHAT_MAX_USER_MESSAGE_CHARS = 500
DEFAULT_USER_PROMPT_MAX_CHARS = 10000
DEFAULT_RAG_MAX_DOCUMENTS = 3
DEFAULT_GALLERY_MAX_GROUPS = 3
DEFAULT_GALLERY_MAX_IMAGES_PER_GROUP = 3


def _get_limits_from_settings(settings: dict | None) -> dict:
    """Возвращает словарь лимитов с подстановкой значений по умолчанию."""
    s = settings or {}
    return {
        "chat_max_user_message_chars": int(s.get("chat_max_user_message_chars") or DEFAULT_CHAT_MAX_USER_MESSAGE_CHARS),
        "user_prompt_max_chars": int(s.get("user_prompt_max_chars") or DEFAULT_USER_PROMPT_MAX_CHARS),
        "rag_max_documents": int(s.get("rag_max_documents") or DEFAULT_RAG_MAX_DOCUMENTS),
        "gallery_max_groups": int(s.get("gallery_max_groups") or DEFAULT_GALLERY_MAX_GROUPS),
        "gallery_max_images_per_group": int(
            s.get("gallery_max_images_per_group") or DEFAULT_GALLERY_MAX_IMAGES_PER_GROUP
        ),
    }


@router.get("/by-slug/{slug}")
async def get_tenant_by_slug_endpoint(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    settings = tenant.settings or {}
    limits = _get_limits_from_settings(settings)
    return {
        "id": str(tenant.id),
        "slug": tenant.slug,
        "name": tenant.name,
        "chat_theme": settings.get("chat_theme") or "cyan",
        "quick_reply_buttons": settings.get("quick_reply_buttons") or ["Расскажи о вас", "Какие услуги?", "Контакты"],
        "chat_max_user_message_chars": limits["chat_max_user_message_chars"],
    }


def get_cabinet_user_id(
    request: Request,
    authorization: str | None = Header(None),
) -> str:
    """Личный кабинет только для зарегистрированных. Требуется JWT."""
    tenant_id = request.path_params.get("tenant_id")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация. Войдите в личный кабинет.")
    token = authorization[7:].strip()
    payload = decode_jwt(token)
    if not payload or str(payload.get("tenant_id")) != str(tenant_id):
        raise HTTPException(status_code=401, detail="Неверный или истёкший токен")
    return str(payload["sub"])


async def get_cabinet_user(
    request: Request,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Личный кабинет только для зарегистрированных. Возвращает user_id после проверки TenantUser."""
    tenant_id_raw = request.path_params.get("tenant_id")
    if not tenant_id_raw:
        raise HTTPException(status_code=400, detail="tenant_id required")
    tenant_id = tenant_id_raw if isinstance(tenant_id_raw, UUID) else UUID(str(tenant_id_raw))
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация. Войдите в личный кабинет.")
    token = authorization[7:].strip()
    payload = decode_jwt(token)
    if not payload or str(payload.get("tenant_id")) != str(tenant_id):
        raise HTTPException(status_code=401, detail="Неверный или истёкший токен")
    user_id = str(payload["sub"])
    tenant = await get_tenant_by_id(db, tenant_id)
    if tenant and (tenant.settings or {}).get("blocked"):
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    user = await get_tenant_user_by_id(db, tenant_id, user_id)
    if not user:
        try:
            uid = UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=403, detail="Доступ только для зарегистрированных пользователей")
        home_user = await get_tenant_user_by_primary_key(db, uid)
        if not home_user or not home_user.email_confirmed_at:
            raise HTTPException(status_code=403, detail="Доступ только для зарегистрированных пользователей")
        home_tenant = await get_tenant_by_id(db, home_user.tenant_id)
        admin_slug = (app_settings.admin_tenant_slug or "").strip()
        if not admin_slug or not home_tenant or home_tenant.slug != admin_slug:
            raise HTTPException(status_code=403, detail="Доступ только для зарегистрированных пользователей")
    elif not user.email_confirmed_at:
        raise HTTPException(status_code=403, detail="Доступ только для зарегистрированных пользователей")
    return user_id


# Dialogs (все диалоги тенанта — посетители iframe; админ видит все)
@router.get("/{tenant_id:uuid}/me/tenant/dialogs", response_model=DialogListResponse)
async def list_tenant_dialogs_endpoint(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    only_new: bool = Query(False, description="Только непросмотренные диалоги"),
    only_leads: bool = Query(False, description="Только диалоги с лидом"),
    include_archived: bool = Query(False, description="Показать архивные диалоги"),
):
    from datetime import datetime as dt
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    d_from = dt.strptime(date_from, "%Y-%m-%d").date() if date_from else None
    d_to = dt.strptime(date_to, "%Y-%m-%d").date() if date_to else None
    total, items = await list_tenant_dialogs(
        db, tenant_id, cabinet_user_id=user_id, limit=limit, offset=offset,
        date_from=d_from, date_to=d_to, only_new=only_new, only_leads=only_leads,
        include_archived=include_archived,
    )
    return DialogListResponse(
        total=total,
        items=[
            DialogListItem(
                id=d["dialog"].id,
                created_at=d["dialog"].created_at,
                updated_at=d["dialog"].updated_at,
                viewed_at=d.get("viewed_at"),
                preview=d["preview"],
                user_id=d["dialog"].user_id,
                message_count=d.get("message_count", 0),
                has_lead=d.get("has_lead", False),
                archived=getattr(d["dialog"], "archived", False),
            )
            for d in items
        ],
    )


@router.get("/{tenant_id:uuid}/me/tenant/dialogs/{dialog_id:uuid}", response_model=DialogDetailResponse)
async def get_tenant_dialog(
    tenant_id: UUID,
    dialog_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    dialog = await get_dialog_by_id(db, tenant_id, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="dialog not found")
    messages = await get_dialog_messages_for_tenant(db, tenant_id, dialog_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="dialog not found")
    viewed_at = await mark_dialog_viewed(db, tenant_id, cabinet_user_id=user_id, dialog_id=dialog_id)
    return DialogDetailResponse(
        id=dialog_id,
        messages=[MessageInDialog(role=m.role, content=m.content, created_at=m.created_at) for m in messages],
        viewed_at=viewed_at,
        archived=getattr(dialog, "archived", False),
    )


@router.patch("/{tenant_id:uuid}/me/tenant/dialogs/{dialog_id:uuid}/archive")
async def archive_tenant_dialog(
    tenant_id: UUID,
    dialog_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    ok = await archive_dialog(db, tenant_id, dialog_id)
    if not ok:
        raise HTTPException(status_code=404, detail="dialog not found")
    await db.commit()
    return {"ok": True, "archived": True}


@router.delete("/{tenant_id:uuid}/me/tenant/dialogs/{dialog_id:uuid}")
async def delete_tenant_dialog(
    tenant_id: UUID,
    dialog_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    ok = await delete_dialog(db, tenant_id, dialog_id)
    if not ok:
        raise HTTPException(status_code=404, detail="dialog not found")
    await db.commit()
    return {"ok": True}


# Dialogs (только свои — оставлено для совместимости, в UI используем tenant/dialogs)
@router.get("/{tenant_id:uuid}/me/dialogs", response_model=DialogListResponse)
async def list_user_dialogs(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    total, items = await list_dialogs(db, tenant_id, user_id, limit=limit, offset=offset)
    return DialogListResponse(
        total=total,
        items=[
            DialogListItem(
                id=d["dialog"].id,
                created_at=d["dialog"].created_at,
                updated_at=d["dialog"].updated_at,
                preview=d["preview"],
            )
            for d in items
        ],
    )


@router.get("/{tenant_id:uuid}/me/dialogs/{dialog_id:uuid}", response_model=DialogDetailResponse)
async def get_user_dialog(
    tenant_id: UUID,
    dialog_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    messages = await get_dialog_messages(db, tenant_id, user_id, dialog_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="dialog not found")
    return DialogDetailResponse(
        id=dialog_id,
        messages=[MessageInDialog(role=m.role, content=m.content, created_at=m.created_at) for m in messages],
    )


# Saved
@router.get("/{tenant_id:uuid}/me/saved", response_model=list[SavedItemResponse])
async def list_user_saved(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    _, items = await list_saved(db, tenant_id, user_id, limit=limit, offset=offset)
    return [SavedItemResponse.model_validate(i) for i in items]


@router.post("/{tenant_id:uuid}/me/saved", response_model=SavedItemResponse, status_code=201)
async def create_saved(
    tenant_id: UUID,
    body: SavedItemCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    item = SavedItem(
        tenant_id=tenant_id,
        user_id=user_id,
        type=body.type,
        reference_id=body.reference_id,
    )
    db.add(item)
    await db.flush()
    return SavedItemResponse.model_validate(item)


@router.delete("/{tenant_id:uuid}/me/saved/{saved_id:uuid}", status_code=204)
async def delete_saved(
    tenant_id: UUID,
    saved_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    item = await get_saved_by_id(db, tenant_id, user_id, saved_id)
    if not item:
        raise HTTPException(status_code=404, detail="saved item not found")
    await db.delete(item)
    await db.flush()


# Текущий пользователь: является ли админом (текущий тенант или «домашний» тенант = ADMIN_TENANT_SLUG)
@router.get("/{tenant_id:uuid}/me/is-admin")
async def get_me_is_admin(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    admin_slug = (app_settings.admin_tenant_slug or "").strip()
    if not admin_slug:
        return {"is_admin": False}
    if tenant.slug == admin_slug:
        return {"is_admin": True}
    try:
        uid = UUID(user_id)
    except ValueError:
        return {"is_admin": False}
    home_user = await get_tenant_user_by_primary_key(db, uid)
    if not home_user:
        return {"is_admin": False}
    home_tenant = await get_tenant_by_id(db, home_user.tenant_id)
    return {"is_admin": bool(home_tenant and home_tenant.slug == admin_slug)}


# Profile
@router.get("/{tenant_id:uuid}/me/profile", response_model=ProfileResponse)
async def get_user_profile(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    user = await get_tenant_user_by_id(db, tenant_id, user_id)
    if not user:
        try:
            uid = UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="user not found")
        user = await get_tenant_user_by_primary_key(db, uid)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
        profile_tenant_id = user.tenant_id
        profile_user_id = str(user.id)
    else:
        profile_tenant_id = tenant_id
        profile_user_id = user_id
    profile = await get_profile(db, profile_tenant_id, profile_user_id)
    system_prompt = tenant.system_prompt if getattr(tenant, "system_prompt", None) else None
    settings = getattr(tenant, "settings", None) or {}
    chat_theme = settings.get("chat_theme")
    quick_reply_buttons = settings.get("quick_reply_buttons")
    limits = _get_limits_from_settings(settings)
    role = getattr(user, "role", None) or None
    display_name = profile.display_name if profile else None
    contact = profile.contact if profile else None
    from app.config import settings as _settings
    _base = (_settings.public_api_base_url or _settings.frontend_base_url or "").strip().rstrip("/")
    _slug = (getattr(tenant, "slug", None) or "").strip()
    telegram_webhook_url = f"{_base}/api/v1/tenants/by-slug/{_slug}/telegram/webhook" if _base and _slug else (f"{_base}/api/v1/tenants/{tenant_id}/telegram/webhook" if _base else None)
    telegram_bot_token_set = bool((settings.get("telegram_bot_token") or "").strip())
    if not profile:
        return ProfileResponse(
            user_id=user_id,
            role=role,
            display_name=display_name,
            contact=contact,
            system_prompt=system_prompt,
            chat_theme=chat_theme,
            quick_reply_buttons=quick_reply_buttons,
            chat_max_user_message_chars=limits["chat_max_user_message_chars"],
            user_prompt_max_chars=limits["user_prompt_max_chars"],
            rag_max_documents=limits["rag_max_documents"],
            gallery_max_groups=limits["gallery_max_groups"],
            gallery_max_images_per_group=limits["gallery_max_images_per_group"],
            telegram_webhook_url=telegram_webhook_url,
            telegram_bot_token_set=telegram_bot_token_set,
        )
    return ProfileResponse(
        user_id=profile.user_id,
        role=role,
        display_name=profile.display_name,
        contact=profile.contact,
        system_prompt=system_prompt,
        chat_theme=chat_theme,
        quick_reply_buttons=quick_reply_buttons,
        chat_max_user_message_chars=limits["chat_max_user_message_chars"],
        user_prompt_max_chars=limits["user_prompt_max_chars"],
        rag_max_documents=limits["rag_max_documents"],
        gallery_max_groups=limits["gallery_max_groups"],
        gallery_max_images_per_group=limits["gallery_max_images_per_group"],
        telegram_webhook_url=telegram_webhook_url,
        telegram_bot_token_set=telegram_bot_token_set,
    )


@router.patch("/{tenant_id:uuid}/me/profile", response_model=ProfileResponse)
async def update_user_profile(
    tenant_id: UUID,
    body: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    profile = await upsert_profile(
        db, tenant_id, user_id,
        display_name=body.display_name,
        contact=body.contact,
    )
    if body.system_prompt is not None:
        tenant.system_prompt = (body.system_prompt or "").strip() or None
    if body.chat_theme is not None or body.quick_reply_buttons is not None or body.telegram_bot_token is not None:
        settings = dict(tenant.settings or {})
        if body.chat_theme is not None:
            settings["chat_theme"] = (body.chat_theme or "").strip() or None
        if body.quick_reply_buttons is not None:
            settings["quick_reply_buttons"] = [str(s).strip() for s in body.quick_reply_buttons if str(s).strip()]
        if body.telegram_bot_token is not None:
            settings["telegram_bot_token"] = (body.telegram_bot_token or "").strip() or None
        tenant.settings = settings
        flag_modified(tenant, "settings")
    await db.flush()
    settings = tenant.settings or {}
    _base = (app_settings.public_api_base_url or app_settings.frontend_base_url or "").strip().rstrip("/")
    _slug = (getattr(tenant, "slug", None) or "").strip()
    telegram_webhook_url = f"{_base}/api/v1/tenants/by-slug/{_slug}/telegram/webhook" if _base and _slug else (f"{_base}/api/v1/tenants/{tenant_id}/telegram/webhook" if _base else None)
    limits = _get_limits_from_settings(settings)
    telegram_bot_token_set = bool((settings.get("telegram_bot_token") or "").strip())
    return ProfileResponse(
        user_id=profile.user_id,
        role=None,
        display_name=profile.display_name,
        contact=profile.contact,
        system_prompt=tenant.system_prompt,
        chat_theme=settings.get("chat_theme"),
        quick_reply_buttons=settings.get("quick_reply_buttons"),
        telegram_webhook_url=telegram_webhook_url,
        telegram_bot_token_set=telegram_bot_token_set,
        chat_max_user_message_chars=limits["chat_max_user_message_chars"],
        user_prompt_max_chars=limits["user_prompt_max_chars"],
        rag_max_documents=limits["rag_max_documents"],
        gallery_max_groups=limits["gallery_max_groups"],
        gallery_max_images_per_group=limits["gallery_max_images_per_group"],
    )


# Промпт пользовательского бота (единый системный промпт): текущее значение и обновление
def _build_user_prompt_response(tenant) -> AdminPromptResponse:
    settings = getattr(tenant, "settings", None) or {}
    prod = (getattr(tenant, "system_prompt", None) or "").strip() or None
    test = (settings.get("test_system_prompt") or "").strip()
    if not test:
        test = prod or None
    prev_prod = (settings.get("prod_system_prompt_prev") or "").strip() or None
    welcome = (getattr(tenant, "welcome_message", None) or "").strip() or None
    return AdminPromptResponse(
        system_prompt=test,
        test_system_prompt=test,
        prod_system_prompt=prod,
        prev_prod_system_prompt=prev_prod,
        welcome_message=welcome,
    )


@router.get("/{tenant_id:uuid}/me/prompt", response_model=AdminPromptResponse)
async def get_user_prompt(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    return _build_user_prompt_response(tenant)


@router.patch("/{tenant_id:uuid}/me/prompt", response_model=AdminPromptResponse)
async def patch_user_prompt(
    tenant_id: UUID,
    body: AdminPromptUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    if body.system_prompt is not None:
        text = (body.system_prompt or "").strip()
        limits = _get_limits_from_settings(tenant.settings or {})
        max_len = limits["user_prompt_max_chars"]
        if len(text) > max_len:
            raise HTTPException(
                status_code=400,
                detail=f"Промпт слишком длинный. Максимум {max_len} символов.",
            )
        settings = dict(tenant.settings or {})
        settings["test_system_prompt"] = text or None
        tenant.settings = settings
        flag_modified(tenant, "settings")
        clear_tenant_test_history(tenant_id)
    await db.flush()
    return _build_user_prompt_response(tenant)


@router.patch("/{tenant_id:uuid}/me/prompt/welcome", response_model=AdminPromptResponse)
async def patch_welcome_message(
    tenant_id: UUID,
    body: WelcomeMessageUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    if body.welcome_message is not None:
        tenant.welcome_message = (body.welcome_message or "").strip() or None
    await db.flush()
    return _build_user_prompt_response(tenant)


# Промпт пользовательского бота: значение по умолчанию из файла (для кнопки «Восстановить из файла»)
@router.get("/{tenant_id:uuid}/me/prompt/default", response_model=AdminPromptResponse)
async def get_user_prompt_default(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    try:
        system_prompt = load_prompt()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Default prompt file not found")
    # Этот endpoint используется как источник шаблона для тестового промпта
    return AdminPromptResponse(system_prompt=system_prompt, test_system_prompt=system_prompt)


@router.patch("/{tenant_id:uuid}/me/prompt/prod", response_model=AdminPromptResponse)
async def patch_user_prompt_prod(
    tenant_id: UUID,
    body: AdminPromptUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    if body.system_prompt is not None:
        text = (body.system_prompt or "").strip()
        settings = dict(tenant.settings or {})
        prev = (getattr(tenant, "system_prompt", None) or "").strip() or None
        if prev and prev != text:
            settings["prod_system_prompt_prev"] = prev
        tenant.system_prompt = text or None
        tenant.settings = settings
        flag_modified(tenant, "settings")
        await clear_tenant_prod_history(db, tenant_id)
    await db.flush()
    return _build_user_prompt_response(tenant)


@router.post("/{tenant_id:uuid}/me/prompt/copy-test-to-prod", response_model=AdminPromptResponse)
async def copy_test_prompt_to_prod(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    settings = dict(tenant.settings or {})
    test = (settings.get("test_system_prompt") or "").strip()
    if not test:
        raise HTTPException(status_code=400, detail="Тестовый промпт пуст. Сначала задайте его.")
    prev = (getattr(tenant, "system_prompt", None) or "").strip() or None
    if prev:
        settings["prod_system_prompt_prev"] = prev
    tenant.system_prompt = test
    tenant.settings = settings
    flag_modified(tenant, "settings")
    await clear_tenant_prod_history(db, tenant_id)
    await db.flush()
    return _build_user_prompt_response(tenant)


@router.post("/{tenant_id:uuid}/me/prompt/rollback-prod", response_model=AdminPromptResponse)
async def rollback_prod_prompt(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    settings = dict(tenant.settings or {})
    prev = (settings.get("prod_system_prompt_prev") or "").strip()
    if not prev:
        raise HTTPException(status_code=400, detail="Нет сохранённой предыдущей версии промпта для отката.")
    current = (getattr(tenant, "system_prompt", None) or "").strip() or None
    # Меняем местами текущий и предыдущий, чтобы можно было откатиться обратно при необходимости
    tenant.system_prompt = prev
    settings["prod_system_prompt_prev"] = current
    tenant.settings = settings
    flag_modified(tenant, "settings")
    await clear_tenant_prod_history(db, tenant_id)
    await db.flush()
    return _build_user_prompt_response(tenant)


# Admin bot prompt (единый системный промпт) — только для тенанта-администратора
@router.get("/{tenant_id:uuid}/me/admin-prompt", response_model=AdminPromptResponse)
async def get_admin_prompt(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await _require_admin_tenant(tenant.slug, db, user_id)
    system_prompt = await get_admin_system_prompt(db, tenant_id)
    return AdminPromptResponse(system_prompt=system_prompt)


@router.patch("/{tenant_id:uuid}/me/admin-prompt", response_model=AdminPromptResponse)
async def patch_admin_prompt(
    tenant_id: UUID,
    body: AdminPromptUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await _require_admin_tenant(tenant.slug, db, user_id)
    await set_admin_system_prompt(db, tenant_id, body.system_prompt)
    system_prompt = await get_admin_system_prompt(db, tenant_id)
    return AdminPromptResponse(system_prompt=system_prompt)


# Промпт админ-бота по умолчанию из файла (admin_chat_prompt.txt)
@router.get("/{tenant_id:uuid}/me/admin-prompt/default", response_model=AdminPromptResponse)
async def get_admin_prompt_default(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await _require_admin_tenant(tenant.slug, db, user_id)
    try:
        system_prompt = load_admin_prompt()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Default admin prompt file not found")
    return AdminPromptResponse(system_prompt=system_prompt)


# Лиды (контакты из диалогов)
@router.get("/{tenant_id:uuid}/me/leads", response_model=list[LeadResponse])
async def list_user_leads(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
):
    from datetime import datetime as dt
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    d_from = dt.strptime(date_from, "%Y-%m-%d").date() if date_from else None
    d_to = dt.strptime(date_to, "%Y-%m-%d").date() if date_to else None
    _, items = await list_leads(
        db, tenant_id, limit=limit, offset=offset, date_from=d_from, date_to=d_to
    )
    return [LeadResponse.model_validate(l) for l in items]


# Embed: код iframe для вставки чата на сайт (URL из FRONTEND_BASE_URL, в пути — slug тенанта)
@router.get("/{tenant_id:uuid}/me/embed", response_model=EmbedCodeResponse)
async def get_embed_code(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    from app.config import settings
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    base_url = (settings.frontend_base_url or "").strip().rstrip("/")
    if not base_url:
        base_url = "https://YOUR_DOMAIN"
    chat_url = f"{base_url}/{tenant.slug}/chat/embed"
    iframe_code = (
        f'<iframe src="{chat_url}" '
        f'data-tenant-id="{tenant.id}" data-tenant-slug="{tenant.slug}" '
        f'width="400" height="600" frameborder="0" title="Чат"></iframe>'
    )
    popup_code = (
        "<button id=\"chatWidgetButton\" type=\"button\" "
        "style=\"position:fixed;bottom:24px;right:24px;z-index:9999;padding:0.6rem 1rem;border-radius:999px;"
        "border:none;background:#00acc1;color:#fff;font-size:0.9rem;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,0.18);\">"
        "Открыть чат"
        "</button>\n"
        "<div id=\"chatWidgetOverlay\" "
        "style=\"position:fixed;inset:0;display:none;align-items:center;justify-content:center;"
        "background:rgba(0,0,0,0.45);z-index:9998;\">\n"
        "  <div style=\"width:100%;max-width:420px;height:80vh;max-height:640px;background:#fff;border-radius:16px;"
        "overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,0.35);position:relative;\">\n"
        "    <button id=\"chatWidgetClose\" type=\"button\" "
        "style=\"position:absolute;top:8px;right:10px;border:none;background:none;font-size:20px;"
        "cursor:pointer;z-index:2;\">×</button>\n"
        f"    <iframe src=\"{chat_url}\" title=\"Чат\" "
        "style=\"border:0;width:100%;height:100%;\"></iframe>\n"
        "  </div>\n"
        "</div>\n"
        "<script>\n"
        "(function(){\n"
        "  var btn = document.getElementById('chatWidgetButton');\n"
        "  var overlay = document.getElementById('chatWidgetOverlay');\n"
        "  var closeBtn = document.getElementById('chatWidgetClose');\n"
        "  if (!btn || !overlay || !closeBtn) return;\n"
        "  btn.addEventListener('click', function(){ overlay.style.display = 'flex'; });\n"
        "  closeBtn.addEventListener('click', function(){ overlay.style.display = 'none'; });\n"
        "  overlay.addEventListener('click', function(e){ if (e.target === overlay) overlay.style.display = 'none'; });\n"
        "})();\n"
        "</script>"
    )
    return EmbedCodeResponse(chat_url=chat_url, iframe_code=iframe_code, popup_code=popup_code)


# --- Прокси к микросервисам: Галерея и RAG (редактирование через UI кабинета) ---
from app.services.microservices_client import gallery_get_file, gallery_request, rag_request


@router.get("/{tenant_id:uuid}/me/gallery/groups")
async def gallery_list_groups(
    tenant_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await gallery_request("GET", f"/api/v1/groups?tenant_id={tenant_id}", tenant_id)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text))


@router.get("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}")
async def gallery_get_group(
    tenant_id: UUID,
    group_id: UUID,
    request: Request,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await gallery_request("GET", f"/api/v1/groups/{group_id}", tenant_id)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    data = json.loads(text)
    base = str(request.base_url).rstrip("/")
    for img in data.get("images") or []:
        img["url"] = f"{base}/api/v1/tenants/{tenant_id}/me/gallery/groups/{group_id}/images/{img['id']}/file"
    return JSONResponse(content=data)


@router.post("/{tenant_id:uuid}/me/gallery/groups")
async def gallery_create_group(
    tenant_id: UUID,
    body: dict,
    user_id: str = Depends(get_cabinet_user),
    db: AsyncSession = Depends(get_db),
):
    body["tenant_id"] = str(tenant_id)
    # Проверка лимита количества галерей
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    limits = _get_limits_from_settings(getattr(tenant, "settings", None) or {})
    max_groups = limits["gallery_max_groups"]
    cur_status, cur_text = await gallery_request("GET", f"/api/v1/groups?tenant_id={tenant_id}", tenant_id)
    if cur_status == 200 and cur_text:
        try:
            data = json.loads(cur_text)
            items = data if isinstance(data, list) else (data.get("items") or data.get("groups") or [])
            if isinstance(items, list) and len(items) >= max_groups:
                return JSONResponse(
                    content={"detail": f"Достигнут лимит по количеству галерей ({max_groups})."},
                    status_code=400,
                )
        except json.JSONDecodeError:
            pass
    status, text = await gallery_request("POST", "/api/v1/groups", tenant_id, json_body=body)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text), status_code=201)


@router.patch("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}")
async def gallery_update_group(
    tenant_id: UUID,
    group_id: UUID,
    body: dict,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await gallery_request("PATCH", f"/api/v1/groups/{group_id}", tenant_id, json_body=body)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text))


@router.delete("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}")
async def gallery_delete_group(
    tenant_id: UUID,
    group_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await gallery_request("DELETE", f"/api/v1/groups/{group_id}", tenant_id)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return Response(status_code=204)


@router.post("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}/images")
async def gallery_add_image(
    tenant_id: UUID,
    group_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(get_cabinet_user),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    files = {"file": (file.filename or "image", content, file.content_type or "application/octet-stream")}
    # Проверка лимита количества изображений в галерее
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    limits = _get_limits_from_settings(getattr(tenant, "settings", None) or {})
    max_images = limits["gallery_max_images_per_group"]
    cur_status, cur_text = await gallery_request("GET", f"/api/v1/groups/{group_id}", tenant_id)
    if cur_status == 200 and cur_text:
        try:
            data = json.loads(cur_text)
            images = data.get("images") or []
            if isinstance(images, list) and len(images) >= max_images:
                return JSONResponse(
                    content={"detail": f"Достигнут лимит по количеству изображений в галерее ({max_images})."},
                    status_code=400,
                )
        except json.JSONDecodeError:
            pass
    status, text = await gallery_request(
        "POST", f"/api/v1/groups/{group_id}/images", tenant_id, files=files
    )
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    data = json.loads(text)
    base = str(request.base_url).rstrip("/")
    data["url"] = f"{base}/api/v1/tenants/{tenant_id}/me/gallery/groups/{group_id}/images/{data['id']}/file"
    return JSONResponse(content=data, status_code=201)


@router.get("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}/images/{image_id:uuid}/file")
async def gallery_serve_image(
    tenant_id: UUID,
    group_id: UUID,
    image_id: UUID,
):
    """Отдаёт бинарный файл изображения из БД галереи. Без авторизации — URL с uuid непредсказуем."""
    status, content, content_type = await gallery_get_file(
        f"/api/v1/groups/{group_id}/images/{image_id}/file"
    )
    if status != 200:
        return Response(status_code=status)
    return Response(content=content, media_type=content_type or "application/octet-stream")


@router.delete("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}/images/{image_id:uuid}")
async def gallery_delete_image(
    tenant_id: UUID,
    group_id: UUID,
    image_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await gallery_request("DELETE", f"/api/v1/groups/{group_id}/images/{image_id}", tenant_id)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return Response(status_code=204)


@router.get("/{tenant_id:uuid}/me/rag/documents")
async def rag_list_documents(
    tenant_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await rag_request("GET", f"/api/v1/documents", params={"tenant_id": str(tenant_id)})
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text))


@router.get("/{tenant_id:uuid}/me/rag/documents/{document_id:uuid}")
async def rag_get_document(
    tenant_id: UUID,
    document_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await rag_request("GET", f"/api/v1/documents/{document_id}")
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text))


@router.post("/{tenant_id:uuid}/me/rag/documents/preview")
async def rag_preview_document(
    tenant_id: UUID,
    file: UploadFile = File(...),
    user_id: str = Depends(get_cabinet_user),
):
    """Преобразует PDF в markdown, возвращает текст без сохранения (для предпросмотра)."""
    content = await file.read()
    files = {"file": (file.filename or "doc.pdf", content, file.content_type or "application/pdf")}
    status, text = await rag_request("POST", "/api/v1/documents/preview", files=files)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text))


@router.post("/{tenant_id:uuid}/me/rag/documents/save")
async def rag_save_document(
    tenant_id: UUID,
    body: dict,
    user_id: str = Depends(get_cabinet_user),
    db: AsyncSession = Depends(get_db),
):
    """Сохраняет документ в RAG из markdown (после предпросмотра)."""
    # Проверка лимита количества документов RAG
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    limits = _get_limits_from_settings(getattr(tenant, "settings", None) or {})
    max_docs = limits["rag_max_documents"]
    cur_status, cur_text = await rag_request(
        "GET", "/api/v1/documents", params={"tenant_id": str(tenant_id)}
    )
    if cur_status == 200 and cur_text:
        try:
            data = json.loads(cur_text)
            items = data if isinstance(data, list) else (data.get("items") or data.get("documents") or [])
            if isinstance(items, list) and len(items) >= max_docs:
                return JSONResponse(
                    content={"detail": f"Достигнут лимит по количеству документов RAG ({max_docs})."},
                    status_code=400,
                )
        except json.JSONDecodeError:
            pass
    status, text = await rag_request(
        "POST",
        "/api/v1/documents/save",
        params={"tenant_id": str(tenant_id)},
        data=body,
    )
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text), status_code=201)


@router.post("/{tenant_id:uuid}/me/rag/documents")
async def rag_upload_document(
    tenant_id: UUID,
    file: UploadFile = File(...),
    name: str = Form(""),
    user_id: str = Depends(get_cabinet_user),
    db: AsyncSession = Depends(get_db),
):
    doc_name = (name or (file.filename or "document").replace(".pdf", "")).strip() or "document"
    # Проверка лимита количества документов RAG
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    limits = _get_limits_from_settings(getattr(tenant, "settings", None) or {})
    max_docs = limits["rag_max_documents"]
    cur_status, cur_text = await rag_request(
        "GET", "/api/v1/documents", params={"tenant_id": str(tenant_id)}
    )
    if cur_status == 200 and cur_text:
        try:
            data = json.loads(cur_text)
            items = data if isinstance(data, list) else (data.get("items") or data.get("documents") or [])
            if isinstance(items, list) and len(items) >= max_docs:
                return JSONResponse(
                    content={"detail": f"Достигнут лимит по количеству документов RAG ({max_docs})."},
                    status_code=400,
                )
        except json.JSONDecodeError:
            pass
    params = {"tenant_id": str(tenant_id), "name": doc_name}
    content = await file.read()
    files = {"file": (file.filename or "doc.pdf", content, file.content_type or "application/pdf")}
    status, text = await rag_request("POST", "/api/v1/documents", params=params, files=files)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text), status_code=201)


@router.delete("/{tenant_id:uuid}/me/rag/documents/{document_id:uuid}")
async def rag_delete_document(
    tenant_id: UUID,
    document_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await rag_request("DELETE", f"/api/v1/documents/{document_id}")
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return Response(status_code=204)


# MCP servers (dynamic connections) — только для тенанта-администратора
@router.get("/{tenant_id:uuid}/me/mcp-servers", response_model=list[McpServerResponse])
async def mcp_servers_list(
    tenant_id: UUID,
    with_tools: bool = Query(True, description="Загрузить список tools с каждого сервера"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await _require_admin_tenant(tenant.slug, db, user_id)
    servers = await list_mcp_servers(db, tenant_id)
    out = []
    for s in servers:
        tools_data = None
        if with_tools:
            try:
                raw = await fetch_tools_from_url(s.base_url)
                tools_data = [
                    McpToolInfo(name=t.get("name", ""), description=t.get("description", ""), inputSchema=t.get("inputSchema"))
                    for t in raw
                ]
            except Exception:
                tools_data = []
        out.append(
            McpServerResponse(
                id=s.id,
                tenant_id=s.tenant_id,
                name=s.name,
                base_url=s.base_url,
                enabled=s.enabled,
                created_at=s.created_at,
                tools=tools_data,
            )
        )
    return out


@router.post("/{tenant_id:uuid}/me/mcp-servers", response_model=McpServerResponse, status_code=201)
async def mcp_server_create(
    tenant_id: UUID,
    body: McpServerCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await _require_admin_tenant(tenant.slug, db, user_id)
    s = await create_mcp_server(
        db, tenant_id, name=body.name, base_url=body.base_url, enabled=body.enabled
    )
    return McpServerResponse(
        id=s.id,
        tenant_id=s.tenant_id,
        name=s.name,
        base_url=s.base_url,
        enabled=s.enabled,
        created_at=s.created_at,
        tools=None,
    )


@router.patch("/{tenant_id:uuid}/me/mcp-servers/{server_id:uuid}", response_model=McpServerResponse)
async def mcp_server_update(
    tenant_id: UUID,
    server_id: UUID,
    body: McpServerUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await _require_admin_tenant(tenant.slug, db, user_id)
    server = await get_mcp_server(db, tenant_id, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await update_mcp_server(
        db, server,
        name=body.name,
        base_url=body.base_url,
        enabled=body.enabled,
    )
    return McpServerResponse(
        id=server.id,
        tenant_id=server.tenant_id,
        name=server.name,
        base_url=server.base_url,
        enabled=server.enabled,
        created_at=server.created_at,
        tools=None,
    )


@router.delete("/{tenant_id:uuid}/me/mcp-servers/{server_id:uuid}", status_code=204)
async def mcp_server_delete(
    tenant_id: UUID,
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await _require_admin_tenant(tenant.slug, db, user_id)
    server = await get_mcp_server(db, tenant_id, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await delete_mcp_server(db, server)
    return Response(status_code=204)


# Лимиты (ограничения) на уровне тенанта
@router.get("/{tenant_id:uuid}/me/limits", response_model=LimitsResponse)
async def get_limits(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    limits = _get_limits_from_settings(tenant.settings or {})
    return LimitsResponse(
        chat_max_user_message_chars=limits["chat_max_user_message_chars"],
        user_prompt_max_chars=limits["user_prompt_max_chars"],
        rag_max_documents=limits["rag_max_documents"],
        gallery_max_groups=limits["gallery_max_groups"],
        gallery_max_images_per_group=limits["gallery_max_images_per_group"],
    )


@router.patch("/{tenant_id:uuid}/me/limits", response_model=LimitsResponse)
async def update_limits(
    tenant_id: UUID,
    body: LimitsUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    settings = dict(tenant.settings or {})
    # Лимит 1 (chat_max_user_message_chars) редактируется только через код, здесь не трогаем.
    current_limits = _get_limits_from_settings(settings)
    if body.user_prompt_max_chars is not None:
        settings["user_prompt_max_chars"] = body.user_prompt_max_chars
        current_limits["user_prompt_max_chars"] = body.user_prompt_max_chars
    if body.rag_max_documents is not None:
        settings["rag_max_documents"] = body.rag_max_documents
        current_limits["rag_max_documents"] = body.rag_max_documents
    if body.gallery_max_groups is not None:
        settings["gallery_max_groups"] = body.gallery_max_groups
        current_limits["gallery_max_groups"] = body.gallery_max_groups
    if body.gallery_max_images_per_group is not None:
        settings["gallery_max_images_per_group"] = body.gallery_max_images_per_group
        current_limits["gallery_max_images_per_group"] = body.gallery_max_images_per_group
    tenant.settings = settings
    flag_modified(tenant, "settings")
    await db.flush()
    return LimitsResponse(
        chat_max_user_message_chars=current_limits["chat_max_user_message_chars"],
        user_prompt_max_chars=current_limits["user_prompt_max_chars"],
        rag_max_documents=current_limits["rag_max_documents"],
        gallery_max_groups=current_limits["gallery_max_groups"],
        gallery_max_images_per_group=current_limits["gallery_max_images_per_group"],
    )


# Вход в кабинет тенанта от имени администратора (без пароля тенанта)
@router.get("/{tenant_id:uuid}/me/admin/tenants/{target_tenant_id:uuid}/impersonate")
async def admin_impersonate_tenant(
    tenant_id: UUID,
    target_tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    """Возвращает билет для открытия кабинета выбранного тенанта. Администратор откроет кабинет от имени первого пользователя тенанта (сессия 30 мин)."""
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await _require_admin_tenant(tenant.slug, db, user_id)
    target = await get_tenant_by_id(db, target_tenant_id)
    if not target:
        raise HTTPException(status_code=404, detail="tenant not found")
    if (target.settings or {}).get("blocked"):
        raise HTTPException(status_code=403, detail="Тенант заблокирован")
    ticket = create_impersonation_ticket(target_tenant_id, user_id)
    return {"ticket": ticket, "tenant_slug": target.slug}


# Блокировка/разблокировка тенанта (администратор)
@router.patch(
    "/{tenant_id:uuid}/me/admin/tenants/{target_tenant_id:uuid}/block",
)
async def admin_block_tenant(
    tenant_id: UUID,
    target_tenant_id: UUID,
    body: BlockTenantUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await _require_admin_tenant(tenant.slug, db, user_id)
    target = await get_tenant_by_id(db, target_tenant_id)
    if not target:
        raise HTTPException(status_code=404, detail="tenant not found")
    settings = dict(target.settings or {})
    settings["blocked"] = body.blocked
    target.settings = settings
    await db.flush()
    return {"blocked": body.blocked}


async def _require_admin_tenant(tenant_slug: str, db: AsyncSession, user_id: str) -> None:
    """Проверка: текущий тенант — администратор ИЛИ пользователь принадлежит тенанту-администратору (вход в чужой тенант)."""
    admin_slug = (app_settings.admin_tenant_slug or "").strip()
    if not admin_slug:
        raise HTTPException(
            status_code=403,
            detail="Доступ только для администратора. Задайте ADMIN_TENANT_SLUG в .env для тенанта-администратора.",
        )
    if tenant_slug == admin_slug:
        return
    try:
        uid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=403, detail="Доступ только для администратора.")
    home_user = await get_tenant_user_by_primary_key(db, uid)
    if not home_user:
        raise HTTPException(status_code=403, detail="Доступ только для администратора.")
    home_tenant = await get_tenant_by_id(db, home_user.tenant_id)
    if home_tenant and home_tenant.slug == admin_slug:
        return
    raise HTTPException(
        status_code=403,
        detail="Доступ только для администратора. Задайте ADMIN_TENANT_SLUG в .env для тенанта-администратора.",
    )


# Список всех тенантов с ограничениями (для страницы «Пользователи» у администратора), с пагинацией
@router.get("/{tenant_id:uuid}/me/admin/tenants")
async def admin_list_tenants_with_limits(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, description="Поиск по slug или названию тенанта"),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await _require_admin_tenant(tenant.slug, db, user_id)
    total, tenants = await list_all_tenants(db, limit=limit, offset=offset, search=search)
    out = []
    for t in tenants:
        settings = t.settings or {}
        limits = _get_limits_from_settings(settings)
        out.append(
            TenantWithLimitsItem(
                id=t.id,
                slug=t.slug,
                name=t.name or t.slug,
                blocked=bool(settings.get("blocked")),
                chat_max_user_message_chars=limits["chat_max_user_message_chars"],
                user_prompt_max_chars=limits["user_prompt_max_chars"],
                rag_max_documents=limits["rag_max_documents"],
                gallery_max_groups=limits["gallery_max_groups"],
                gallery_max_images_per_group=limits["gallery_max_images_per_group"],
            )
        )
    return {"total": total, "items": out}


# Обновление ограничений выбранного тенанта (администратор)
@router.patch(
    "/{tenant_id:uuid}/me/admin/tenants/{target_tenant_id:uuid}/limits",
    response_model=LimitsResponse,
)
async def admin_update_tenant_limits(
    tenant_id: UUID,
    target_tenant_id: UUID,
    body: LimitsUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await _require_admin_tenant(tenant.slug, db, user_id)
    target = await get_tenant_by_id(db, target_tenant_id)
    if not target:
        raise HTTPException(status_code=404, detail="tenant not found")
    settings = dict(target.settings or {})
    current_limits = _get_limits_from_settings(settings)
    if body.user_prompt_max_chars is not None:
        settings["user_prompt_max_chars"] = body.user_prompt_max_chars
        current_limits["user_prompt_max_chars"] = body.user_prompt_max_chars
    if body.rag_max_documents is not None:
        settings["rag_max_documents"] = body.rag_max_documents
        current_limits["rag_max_documents"] = body.rag_max_documents
    if body.gallery_max_groups is not None:
        settings["gallery_max_groups"] = body.gallery_max_groups
        current_limits["gallery_max_groups"] = body.gallery_max_groups
    if body.gallery_max_images_per_group is not None:
        settings["gallery_max_images_per_group"] = body.gallery_max_images_per_group
        current_limits["gallery_max_images_per_group"] = body.gallery_max_images_per_group
    target.settings = settings
    await db.flush()
    return LimitsResponse(
        chat_max_user_message_chars=current_limits["chat_max_user_message_chars"],
        user_prompt_max_chars=current_limits["user_prompt_max_chars"],
        rag_max_documents=current_limits["rag_max_documents"],
        gallery_max_groups=current_limits["gallery_max_groups"],
        gallery_max_images_per_group=current_limits["gallery_max_images_per_group"],
    )


# Admin chat
@router.post("/{tenant_id:uuid}/admin/chat", response_model=AdminChatResponse)
async def admin_chat(
    tenant_id: UUID,
    body: AdminChatRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    session_id = body.session_id or str(uuid4())
    history = [{"role": m.role, "content": m.content} for m in body.history]
    result = await handle_admin_message(
        db, tenant_id, user_id, body.message.strip(), history=history
    )
    if isinstance(result, str):
        reply_text = result
        return AdminChatResponse(
            reply=reply_text,
            validation=None,
            validation_reason=None,
            prompt_saved=False,
            session_id=session_id,
        )
    reply_text = result["reply"]
    # Лог: что ушло в DeepSeek и что вернулось (сырой ответ до постобработки)
    # Отдельно выводим контекст (галереи, документы, промпт бота-пользователя), чтобы он был виден в логе
    request_system_prompt = result.get("request_system_prompt") or ""
    request_context = result.get("request_context") or ""
    request_messages = result.get("request_messages") or []
    request_to_llm_parts = [
        "[system - инструкции админ-боту]\n",
        request_system_prompt,
        "\n\n[system - контекст: галереи, документы RAG, текущий промпт бота-пользователя]\n",
        request_context,
        "\n\n[messages]\n",
    ]
    for m in request_messages:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        request_to_llm_parts.append(f"{role}:\n{content}\n")
    request_to_llm = "".join(request_to_llm_parts)
    raw_reply = result.get("raw_reply") or ""
    is_admin = await is_user_admin_for_tenant(db, tenant_id, user_id)
    append_admin_chat_exchange(
        tenant_id,
        session_id,
        request_to_llm,
        raw_reply,
        is_new_session=not body.history,
        is_admin=is_admin,
    )
    return AdminChatResponse(
        reply=reply_text,
        validation=result.get("validation"),
        validation_reason=result.get("validation_reason"),
        prompt_saved=result.get("prompt_saved", False),
        session_id=session_id,
    )
