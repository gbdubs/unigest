from functools import lru_cache
import os


class Settings:
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://unigest:unigest@localhost:5432/unigest",
    )
    DEV_MODE: bool = os.getenv("DEV_MODE", "true").lower() == "true"
    WEBHOOK_TIMEOUT_SECONDS: int = int(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "10"))
    WORKER_AUTH_TOKEN: str | None = os.getenv("WORKER_AUTH_TOKEN")


@lru_cache
def get_settings() -> Settings:
    return Settings()
