"""Регистрация, подтверждение по email, логин, JWT."""
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from uuid import UUID

import bcrypt
import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Tenant, TenantUser
from app.services.email_service import send_confirmation_email

CONFIRM_TOKEN_EXPIRE_HOURS = 24
BCRYPT_MAX_PASSWORD_BYTES = 72


def _password_bytes(password: str) -> bytes:
    """Bcrypt accepts at most 72 bytes; truncate to avoid error."""
    return password.encode("utf-8")[:BCRYPT_MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    raw = _password_bytes(password)
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    raw = _password_bytes(plain)
    return bcrypt.checkpw(raw, hashed.encode("ascii"))


def create_jwt(user_id: str, tenant_id: str, expire_minutes: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    minutes = expire_minutes if expire_minutes is not None else settings.jwt_expire_minutes
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


# Вход в кабинет тенанта от имени администратора: короткоживущий токен (30 мин)
IMPERSONATE_EXPIRE_MINUTES = 30


def create_impersonation_ticket(tenant_id: UUID, user_id: str) -> str:
    """Билет для входа в кабинет другого тенанта (передаётся в URL, затем обменивается на JWT)."""
    now = datetime.now(timezone.utc)
    payload = {
        "purpose": "impersonate",
        "tenant_id": str(tenant_id),
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=IMPERSONATE_EXPIRE_MINUTES),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_impersonation_ticket(ticket: str) -> dict | None:
    try:
        payload = jwt.decode(
            ticket,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("purpose") != "impersonate":
            return None
        return payload
    except jwt.PyJWTError:
        return None


def decode_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError:
        return None


async def register_new_user_with_tenant(
    db: AsyncSession,
    email: str,
    password: str,
) -> tuple[TenantUser, Tenant]:
    """
    Регистрация «один тенант на пользователя»: создаёт новый тенант и пользователя в нём.
    Email должен быть уникален глобально (не занят ни в одном тенанте).
    """
    email_norm = email.lower().strip()
    existing = (
        await db.execute(select(TenantUser).where(TenantUser.email == email_norm))
    ).scalar_one_or_none()
    if existing:
        raise ValueError("email_already_registered")
    slug = "u" + uuid.uuid4().hex[:12]
    name = email_norm.split("@")[0] if "@" in email_norm else "Моё пространство"
    tenant = Tenant(slug=slug, name=name or "Моё пространство")
    db.add(tenant)
    await db.flush()
    from app.services.cabinet_service import create_default_mcp_servers_for_tenant
    await create_default_mcp_servers_for_tenant(db, tenant.id)
    user = await register_user(db, tenant.id, email, password, tenant.slug)
    return user, tenant


async def register_user(
    db: AsyncSession,
    tenant_id: UUID,
    email: str,
    password: str,
    tenant_slug: str,
) -> TenantUser:
    existing = (
        await db.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.email == email.lower().strip(),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise ValueError("email_already_registered")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=CONFIRM_TOKEN_EXPIRE_HOURS)
    user = TenantUser(
        tenant_id=tenant_id,
        email=email.lower().strip(),
        password_hash=hash_password(password),
        confirmation_token=token,
        confirmation_token_expires_at=expires,
    )
    db.add(user)
    await db.flush()
    await send_confirmation_email(user.email, tenant_slug, token)
    return user


async def confirm_email(db: AsyncSession, tenant_id: UUID, token: str) -> TenantUser | None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.confirmation_token == token,
            TenantUser.confirmation_token_expires_at > now,
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        return None
    user.email_confirmed_at = now
    user.confirmation_token = None
    user.confirmation_token_expires_at = None
    await db.flush()
    return user


async def login_user(
    db: AsyncSession,
    tenant_id: UUID,
    email: str,
    password: str,
) -> TenantUser | None:
    result = await db.execute(
        select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.email == email.lower().strip(),
        )
    )
    user = result.scalar_one_or_none()
    if not user or not user.email_confirmed_at:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def login_user_by_email(
    db: AsyncSession,
    email: str,
    password: str,
) -> tuple[TenantUser, Tenant] | None:
    """Вход по email и паролю без указания тенанта. Возвращает (user, tenant) или None.
    Если пользователь с таким email есть в нескольких тенантах — берётся первый по дате создания."""
    email_norm = email.lower().strip()
    result = await db.execute(
        select(TenantUser, Tenant)
        .join(Tenant, TenantUser.tenant_id == Tenant.id)
        .where(func.lower(TenantUser.email) == email_norm)
        .order_by(TenantUser.created_at)
        .limit(1)
    )
    row = result.one_or_none()
    if not row:
        return None
    user, tenant = row
    if not user.email_confirmed_at:
        return None
    if not verify_password(password, user.password_hash):
        return None
    if (tenant.settings or {}).get("blocked"):
        return None
    return (user, tenant)


async def get_or_create_superadmin_user(
    db: AsyncSession,
    tenant_id: UUID,
    email: str,
    password: str,
) -> TenantUser:
    """Находит или создаёт пользователя с данным email в тенанте (для входа суперадмина по учётке из .env)."""
    email_norm = email.lower().strip()
    result = await db.execute(
        select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.email == email_norm,
        )
    )
    user = result.scalar_one_or_none()
    if user:
        if not user.email_confirmed_at:
            user.email_confirmed_at = datetime.now(timezone.utc)
            await db.flush()
        return user
    user = TenantUser(
        tenant_id=tenant_id,
        email=email_norm,
        password_hash=hash_password(password),
        email_confirmed_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()
    return user


RESET_PASSWORD_EXPIRE_HOURS = 2


async def request_password_reset(db: AsyncSession, tenant_id: UUID, email: str) -> TenantUser | None:
    """Генерирует токен сброса пароля и сохраняет в пользователе. Возвращает пользователя или None.
    Письмо отправляется и для неподтверждённых пользователей (можно восстановить пароль, затем войти)."""
    email_norm = email.lower().strip()
    # Поиск без учёта регистра email; подтверждение email не требуется — письмо высылаем в любом случае
    result = await db.execute(
        select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            func.lower(TenantUser.email) == email_norm,
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        return None
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=RESET_PASSWORD_EXPIRE_HOURS)
    user.reset_password_token = token
    user.reset_password_expires_at = expires
    await db.flush()
    return user


async def get_user_by_reset_token(db: AsyncSession, tenant_id: UUID, token: str) -> TenantUser | None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.reset_password_token == token,
            TenantUser.reset_password_expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def set_password_by_reset_token(
    db: AsyncSession,
    tenant_id: UUID,
    token: str,
    new_password: str,
) -> TenantUser | None:
    user = await get_user_by_reset_token(db, tenant_id, token)
    if not user:
        return None
    user.password_hash = hash_password(new_password)
    user.reset_password_token = None
    user.reset_password_expires_at = None
    if user.email_confirmed_at is None:
        user.email_confirmed_at = datetime.now(timezone.utc)
    await db.flush()
    return user


async def get_tenant_user_by_id(db: AsyncSession, tenant_id: UUID, user_id: str) -> TenantUser | None:
    try:
        uid = UUID(user_id)
    except ValueError:
        return None
    result = await db.execute(
        select(TenantUser).where(
            TenantUser.id == uid,
            TenantUser.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_tenant_user_by_primary_key(db: AsyncSession, user_id: UUID) -> TenantUser | None:
    """Найти TenantUser по первичному ключу (id). Нужно для проверки «домашнего» тенанта при имперсонации."""
    result = await db.execute(select(TenantUser).where(TenantUser.id == user_id))
    return result.scalar_one_or_none()
