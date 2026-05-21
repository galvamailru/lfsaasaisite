"""Configuration from .env. DATABASE_URL переопределяется в docker-compose."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/cip"
    app_host: str = "0.0.0.0"
    app_port: int = 8010


settings = Settings()
