from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"
    database_url: str = "sqlite+aiosqlite:///./data/avito.db"
    bot_token: str = ""
    allow_fixture_poll: bool = True
    fetch_live: bool = True
    run_worker: bool = True
    min_interval_seconds: int = 45
    request_gap_seconds: float = 2.0
    request_timeout_seconds: float = 20.0
    host: str = "127.0.0.1"
    port: int = 8080

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.bot_token.strip())


def get_settings() -> Settings:
    return Settings()
