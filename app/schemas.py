"""Pydantic schemas for API."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# Auth
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class RegisterResponse(BaseModel):
    message: str = "Письмо с подтверждением отправлено на указанный email."
    user_id: str
    tenant_id: str | None = None  # при регистрации «один тенант на пользователя»
    tenant_slug: str | None = None  # ссылка на вход: /{tenant_slug}/login


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    tenant_id: str
    tenant_slug: str | None = None  # для редиректа после входа без slug (/login)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class ImpersonateRedeemRequest(BaseModel):
    ticket: str = Field(..., min_length=1)


# Chat (tenant_id from path)
class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1)
    dialog_id: UUID | None = None
    is_test: bool = False  # режим теста в админке — не сохранять диалоги/сообщения в БД


class ChatMessageResponse(BaseModel):
    """Ответ одним сообщением (для клиентов без SSE)."""
    reply: str


# Cabinet: dialogs
class DialogListItem(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    viewed_at: datetime | None = None
    preview: str | None = None
    user_id: str | None = None
    message_count: int = 0
    has_lead: bool = False
    archived: bool = False

    class Config:
        from_attributes = True


class DialogListResponse(BaseModel):
    total: int
    items: list[DialogListItem]


class MessageInDialog(BaseModel):
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class DialogDetailResponse(BaseModel):
    id: UUID
    messages: list[MessageInDialog]
    viewed_at: datetime | None = None
    archived: bool = False


# Cabinet: saved
class SavedItemCreate(BaseModel):
    type: str = Field(..., min_length=1, max_length=32)
    reference_id: str = Field(..., min_length=1, max_length=256)


class SavedItemResponse(BaseModel):
    id: UUID
    type: str
    reference_id: str
    created_at: datetime

    class Config:
        from_attributes = True


# Cabinet: profile
class ProfileResponse(BaseModel):
    user_id: str
    role: str | None = None  # admin | user, для отображения в шапке кабинета
    display_name: str | None = None
    contact: str | None = None
    system_prompt: str | None = None
    chat_theme: str | None = None
    quick_reply_buttons: list[str] | None = None
    # Ограничения тенанта (просмотр в профиле, редактирование в отдельном разделе)
    chat_max_user_message_chars: int | None = None
    user_prompt_max_chars: int | None = None
    rag_max_documents: int | None = None
    gallery_max_groups: int | None = None
    gallery_max_images_per_group: int | None = None
    # Ссылка для регистрации webhook бота в Telegram (POST сюда получает обновления)
    telegram_webhook_url: str | None = None
    # True, если токен бота уже сохранён (сам токен в API не отдаётся)
    telegram_bot_token_set: bool = False

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=256)
    contact: str | None = Field(None, max_length=256)
    system_prompt: str | None = None
    chat_theme: str | None = Field(None, max_length=64)
    quick_reply_buttons: list[str] | None = None
    telegram_bot_token: str | None = Field(None, max_length=256)  # токен от BotFather; сохраняется в tenant.settings


# Ограничения (per-tenant), для отдельного раздела управления
class LimitsResponse(BaseModel):
    chat_max_user_message_chars: int
    user_prompt_max_chars: int
    rag_max_documents: int
    gallery_max_groups: int
    gallery_max_images_per_group: int


class LimitsUpdate(BaseModel):
    # Ограничения, которые можно редактировать в разделе «Пользователи»
    user_prompt_max_chars: int | None = Field(None, ge=1, le=100000)
    rag_max_documents: int | None = Field(None, ge=1, le=100)
    gallery_max_groups: int | None = Field(None, ge=1, le=100)
    gallery_max_images_per_group: int | None = Field(None, ge=1, le=100)


class TenantWithLimitsItem(BaseModel):
    """Строка таблицы пользователей (тенант + его ограничения) для администратора."""
    id: UUID
    slug: str
    name: str
    blocked: bool
    chat_max_user_message_chars: int
    user_prompt_max_chars: int
    rag_max_documents: int
    gallery_max_groups: int
    gallery_max_images_per_group: int


class BlockTenantUpdate(BaseModel):
    blocked: bool


# Cabinet: admin/user bot prompt responses
class AdminPromptResponse(BaseModel):
    """
    Ответ для работы с промптами.
    Для пользовательского бота:
      - system_prompt / test_system_prompt — тестовый промпт (чат в кабинете);
      - prod_system_prompt — боевой промпт (iframe);
      - prev_prod_system_prompt — предыдущая версия боевого промпта (для отката).

    Три промпта: test_system_prompt — тестовый чат-бот; prod (system_prompt) — iframe-бот; admin_system_prompt — бот администратора.
    """
    system_prompt: str | None = None
    prod_system_prompt: str | None = None
    prev_prod_system_prompt: str | None = None
    test_system_prompt: str | None = None
    welcome_message: str | None = None


class AdminPromptUpdate(BaseModel):
    system_prompt: str | None = None


class WelcomeMessageUpdate(BaseModel):
    welcome_message: str | None = None


# Cabinet: leads (contacts from dialogs)
class LeadResponse(BaseModel):
    id: UUID
    user_id: str
    dialog_id: UUID
    contact_text: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Cabinet: embed code for iframe
class EmbedCodeResponse(BaseModel):
    """URL чата для iframe и готовые HTML-коды для вставки."""
    chat_url: str
    iframe_code: str
    popup_code: str


# Admin chat
class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., max_length=8192)


class AdminChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)
    history: list[ChatMessage] = Field(default_factory=list, max_length=30)
    session_id: str | None = None  # идентификатор сессии; если нет — создаётся новая сессия (новый файл лога)


class AdminChatResponse(BaseModel):
    reply: str
    validation: bool | None = None  # результат валидации промпта (true — ок, false — нужна доработка)
    validation_reason: str | None = None
    prompt_saved: bool = False  # True, если в этом ответе промпт бота-пользователя был сохранён через [SAVE_PROMPT]
    session_id: str | None = None  # идентификатор сессии (передаётся при создании новой сессии для последующих запросов)


# MCP servers (dynamic connections)
class McpServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    base_url: str = Field(..., min_length=1, max_length=2048)
    enabled: bool = True


class McpServerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    base_url: str | None = Field(None, min_length=1, max_length=2048)
    enabled: bool | None = None


class McpToolInfo(BaseModel):
    name: str
    description: str = ""
    inputSchema: dict | None = None


class McpServerResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    base_url: str
    enabled: bool
    created_at: datetime
    tools: list[McpToolInfo] | None = None  # заполняется при with_tools=true

    class Config:
        from_attributes = True
