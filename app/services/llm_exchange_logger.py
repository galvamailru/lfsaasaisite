"""Единое логирование обменов с DeepSeek: запрос и ответ по типам чата в раздельные директории.
Вызов append_exchange делается вызывающим кодом: prodchat (iframe) и telegramchat (Telegram) логируются всегда,
testchat и adminchat — только для администратора."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.config import PROJECT_ROOT

SEP_LINE = "#" * 60

# Поддиректории под logs/: testchat, prodchat (iframe), telegramchat (Telegram), adminchat
CHAT_TYPE_DIRS = ("testchat", "prodchat", "telegramchat", "adminchat")


def _log_dir(chat_type: str) -> Path:
    """Директория для типа чата: logs/testchat, logs/prodchat, logs/telegramchat, logs/adminchat."""
    if chat_type not in CHAT_TYPE_DIRS:
        chat_type = "prodchat"
    return PROJECT_ROOT / "logs" / chat_type


def _session_log_path(tenant_id: UUID, session_id: str, chat_type: str) -> Path:
    log_dir = _log_dir(chat_type)
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_sid = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return log_dir / f"{tenant_id}_{safe_sid}.log"


def append_exchange(
    chat_type: str,
    tenant_id: UUID,
    session_id: str,
    request_to_llm: str,
    response_from_llm: str,
    *,
    is_new_session: bool = False,
    is_admin: bool = False,
) -> None:
    """
    Пишет в лог один обмен с DeepSeek (запрос и ответ).
    Вызывающий код решает, когда вызывать (prodchat/telegramchat — всегда, testchat/adminchat — при is_admin).
    chat_type: "testchat" | "prodchat" | "telegramchat" | "adminchat" — поддиректория в logs/.
    """
    if chat_type not in CHAT_TYPE_DIRS:
        chat_type = "prodchat"
    path = _session_log_path(tenant_id, session_id, chat_type)
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    block = (
        "=== REQUEST TO DEEPSEEK ===\n"
        f"{request_to_llm}\n"
        f"{SEP_LINE}\n"
        "=== RESPONSE FROM DEEPSEEK ===\n"
        f"{response_from_llm}\n"
    )
    if is_new_session:
        header = f"tenant_id={tenant_id} session_id={session_id} started={ts}\n{SEP_LINE}\n"
        content = header + block
    else:
        content = "\n" + block
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        pass
