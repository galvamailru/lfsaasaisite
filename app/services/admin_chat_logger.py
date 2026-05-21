"""Логирование диалогов админ-бота: делегирует в единый логгер (adminchat, только для админов)."""
from uuid import UUID

from app.services.llm_exchange_logger import append_exchange


def append_admin_chat_exchange(
    tenant_id: UUID,
    session_id: str,
    request_to_llm: str,
    response_from_llm: str,
    *,
    is_new_session: bool = False,
    is_admin: bool = True,
) -> None:
    """
    Пишет в лог-файл сессии один обмен админ-чата (директория adminchat).
    Вызов только из админ-чата, поэтому по умолчанию is_admin=True.
    """
    append_exchange(
        "adminchat",
        tenant_id,
        session_id,
        request_to_llm,
        response_from_llm,
        is_new_session=is_new_session,
        is_admin=is_admin,
    )
