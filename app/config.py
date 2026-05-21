"""Configuration from .env only."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/cip"
    deepseek_api_url: str = "https://api.deepseek.com/v1"
    deepseek_api_key: str = ""
    prompt_file: str = "prompts/system_prompt.txt"
    admin_prompt_file: str = "prompts/admin_chat_prompt.txt"
    welcome_message_file: str = "prompts/welcome_message.txt"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Auth & email
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@example.com"
    frontend_base_url: str = "http://localhost:8000"  # for confirmation link
    # Публичный URL API (для webhook Telegram). Если пусто — используется frontend_base_url.
    public_api_base_url: str = ""

    # Микросервисы (вызов из пользовательского чата по EXECUTE)
    gallery_service_url: str = "http://localhost:8010"
    rag_service_url: str = "http://localhost:8020"

    # MinIO (файлы пользователя в личном кабинете)
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "cip-files"
    minio_secure: bool = False

    # Логи диалогов админ-бота (каждая сессия — отдельный файл)
    admin_chat_log_dir: str = "logs/admin_chat"

    # Тенант-администратор: slug тенанта, пользователи которого могут видеть список всех тенантов и редактировать их ограничения (страница «Пользователи»). Пусто — доступ к списку только у этого тенанта отключён.
    admin_tenant_slug: str = ""

    # Суперадминистратор: вход по логину и паролю из .env (страница входа — как у тенанта: /{admin_tenant_slug}/login, логин = SUPERADMIN_LOGIN).
    superadmin_login: str = ""
    superadmin_password: str = ""

    # MCP-серверы по умолчанию для новых тенантов: JSON-массив пар [название, url], например [["RAG","http://rag:8020"],["Gallery","http://gallery:8010"]]
    default_mcp_servers: str = '[["RAG","http://rag:8020"],["Gallery","http://gallery:8010"]]'

    # LangFuse (observability LLM + MCP)
    langfuse_enabled: bool = True
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    def get_prompt_path(self, base_dir: Path | None = None) -> Path:
        p = Path(self.prompt_file)
        if not p.is_absolute():
            base = base_dir if base_dir is not None else PROJECT_ROOT
            p = base / p
        return p

    def get_admin_prompt_path(self, base_dir: Path | None = None) -> Path:
        p = Path(self.admin_prompt_file)
        if not p.is_absolute():
            base = base_dir if base_dir is not None else PROJECT_ROOT
            p = base / p
        return p

    def get_welcome_message_path(self, base_dir: Path | None = None) -> Path:
        p = Path(self.welcome_message_file)
        if not p.is_absolute():
            base = base_dir if base_dir is not None else PROJECT_ROOT
            p = base / p
        return p


settings = Settings()
