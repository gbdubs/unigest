from functools import lru_cache
import os


class Settings:
    SERVER_URL: str = os.getenv("SERVER_URL", "http://localhost:8000")
    LLM_ENDPOINT: str = os.getenv("LLM_ENDPOINT", "http://localhost:11434")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemma4")
    POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
    MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "1"))
    SANDBOX_TIMEOUT_SECONDS: int = int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "30"))
    SANDBOX_MEMORY_MB: int = int(os.getenv("SANDBOX_MEMORY_MB", "512"))
    IMPROVEMENT_RATE_LIMIT: int = int(os.getenv("IMPROVEMENT_RATE_LIMIT", "10"))
    WORKER_AUTH_TOKEN: str | None = os.getenv("WORKER_AUTH_TOKEN")


@lru_cache
def get_settings() -> Settings:
    return Settings()
