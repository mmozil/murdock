"""Configuração centralizada do Murdock."""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://murdock:murdock@localhost:5432/murdock"

    # ── Redis ─────────────────────────────────────
    REDIS_URL: Optional[str] = "redis://localhost:6379/5"

    # ── LLM (env-based, padrão Tier Agent — zero hardcode) ──
    # Provider primário e credenciais vêm 100% do ambiente.
    # Default = MiniMax via endpoint OpenAI-compatible.
    DEFAULT_LLM_PROVIDER: str = "minimax"
    DEFAULT_LLM_MODEL: str = "MiniMax-M2"
    DEFAULT_LLM_BASE_URL: str = "https://api.minimax.io/v1"
    DEFAULT_LLM_API_KEY: Optional[str] = None

    # Fallback (acionado se o provider primário falhar)
    FALLBACK_LLM_PROVIDER: str = "anthropic"
    FALLBACK_LLM_MODEL: str = "claude-sonnet-4-20250514"
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None

    # ── Embeddings ────────────────────────────────
    EMBEDDING_MODEL: str = "gemini-embedding-001"
    EMBEDDING_DIMENSIONS: int = 768

    # ── Auth ──────────────────────────────────────
    SECRET_KEY: str = "change-me-in-production"
    API_KEY: str = "murdock-api-key-change-me"

    # ── Server ────────────────────────────────────
    ENVIRONMENT: str = "development"
    PORT: int = 8010
    APP_NAME: str = "Murdock"
    APP_VERSION: str = "1.0.0"

    # ── RAG ───────────────────────────────────────
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    MIN_SIMILARITY: float = 0.55
    MAX_RESULTS: int = 8
    RRF_K: int = 60

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
