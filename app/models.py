"""SQLAlchemy models: tenant, dialog, message, saved_item, user_profile, prompt_chunk, lead.

Мультитенантность: все сущности, кроме Tenant и TenantUser, содержат tenant_id.
Все выборки и записи должны фильтроваться по tenant_id для изоляции данных тенанта."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    dialogs = relationship("Dialog", back_populates="tenant")
    messages = relationship("Message", back_populates="tenant")
    saved_items = relationship("SavedItem", back_populates="tenant")
    user_profiles = relationship("UserProfile", back_populates="tenant")
    tenant_users = relationship("TenantUser", back_populates="tenant")
    prompt_chunks = relationship("PromptChunk", back_populates="tenant", order_by="PromptChunk.position")
    # Системный промпт пользовательского бота (основной), поверх него добавляются чанки prompt_chunk.
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Приветствие в чате пользователя (показывается при открытии; если пусто — из файла по умолчанию).
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Системный промпт админ-бота (кабинет).
    admin_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_prompt_chunks = relationship(
        "AdminPromptChunk", back_populates="tenant", order_by="AdminPromptChunk.position"
    )
    leads = relationship("Lead", back_populates="tenant")
    mcp_servers = relationship("McpServer", back_populates="tenant", cascade="all, delete-orphan")


class TenantUser(Base):
    """Зарегистрированный пользователь тенанта (email + пароль, подтверждение по почте). По умолчанию роль admin."""
    __tablename__ = "tenant_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    email_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmation_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmation_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reset_password_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reset_password_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="tenant_users")

    __table_args__ = (
        Index("ix_tenant_user_tenant_email", "tenant_id", "email", unique=True),
    )


class Dialog(Base):
    __tablename__ = "dialog"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    archived: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="dialogs")
    messages = relationship("Message", back_populates="dialog", order_by="Message.created_at")

    __table_args__ = (
        Index("ix_dialog_tenant_user_updated", "tenant_id", "user_id", "updated_at"),
    )


class DialogView(Base):
    """Просмотры диалогов пользователем кабинета: каждый диалог, который админ открыл, помечается для этого пользователя (все такие диалоги считаются прочитанными)."""
    __tablename__ = "dialog_view"
    __table_args__ = (
        UniqueConstraint("tenant_id", "cabinet_user_id", "dialog_id", name="uq_dialog_view_tenant_user_dialog"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    cabinet_user_id: Mapped[str] = mapped_column(String(64), nullable=False)  # id пользователя кабинета (TenantUser.id)
    dialog_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dialog.id", ondelete="CASCADE"), nullable=False
    )
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Message(Base):
    __tablename__ = "message"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dialog_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dialog.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="messages")
    dialog = relationship("Dialog", back_populates="messages")

    __table_args__ = (
        Index("ix_message_tenant_user", "tenant_id", "user_id"),
    )


class SavedItem(Base):
    __tablename__ = "saved_item"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="saved_items")

    __table_args__ = (
        Index("ix_saved_item_tenant_user", "tenant_id", "user_id"),
    )


class UserProfile(Base):
    __tablename__ = "user_profile"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="user_profiles")


class PromptChunk(Base):
    """Чанк системного промпта чат-бота: вопрос админа (question) и ответ пользователя (content).
    Порядок по position. В дальнейшем возможны type/metadata для MCP или триггеров галереи."""
    __tablename__ = "prompt_chunk"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # вопрос, на который пользователь ответил этим чанком
    content: Mapped[str] = mapped_column(String(2000), nullable=False)

    tenant = relationship("Tenant", back_populates="prompt_chunks")

    __table_args__ = (
        Index("ix_prompt_chunk_tenant_position", "tenant_id", "position"),
    )


class AdminPromptChunk(Base):
    """Чанк промпта админ-бота: вопрос пользователю (question) и детальное описание (content). Порядок по position."""
    __tablename__ = "admin_prompt_chunk"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    tenant = relationship("Tenant", back_populates="admin_prompt_chunks")

    __table_args__ = (
        Index("ix_admin_prompt_chunk_tenant_position", "tenant_id", "position"),
    )


class McpServer(Base):
    """Динамически подключаемый MCP-сервер тенанта (URL + название). Tools запрашиваются по tools/list."""
    __tablename__ = "mcp_server"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)  # e.g. http://host:8010, путь /mcp добавляется при вызове
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="mcp_servers")

    __table_args__ = (Index("ix_mcp_server_tenant_id", "tenant_id"),)


class Lead(Base):
    """Лиды: контакты из диалогов (email, телефон). Один лид на сессию (tenant_id, user_id, dialog_id)."""
    __tablename__ = "lead"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "dialog_id", name="uq_lead_tenant_user_dialog"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dialog_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dialog.id", ondelete="CASCADE"), nullable=False
    )
    contact_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="leads")
