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
    # Login com Google (Google Identity Services). Vazio = botão Google não aparece.
    # Criar OAuth Client ID (Web) no Google Cloud Console com origem https://specter.hovio.com.br.
    GOOGLE_CLIENT_ID: Optional[str] = None

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

    # ── Feeds (atualização automática de leis — todas fontes GRATUITAS) ──
    ENABLE_FEEDS_SCHEDULER: bool = True   # liga os crons (DOU diário, LexML/jurisprudência semanal)

    # DOU via INLABS (Imprensa Nacional) — full text de TODA norma nova. Requer conta grátis.
    INLABS_EMAIL: Optional[str] = None
    INLABS_PASSWORD: Optional[str] = None
    FEEDS_DOU_SECOES: str = "DO1"          # DO1 = Seção 1 (atos normativos). Espaço-separado.
    FEEDS_DOU_MAX_ARTIGOS: int = 150       # teto/dia após filtro (controla custo de embedding)
    FEEDS_TAX_KEYWORDS: str = (
        "tributár,tributo,imposto,ICMS,ISS,PIS,Cofins,IRPJ,CSLL,IRRF,"
        "Simples Nacional,MEI,CBS,IBS,IPI,DIFAL,substituição tributária,"
        "Receita Federal,CONFAZ,CGSN,solução de consulta,instrução normativa,"
        "NCM,SPED,reforma tributária,crédito tributário"
    )

    # LexML SRU — ⚠️ endpoint /busca/SRU verificado FORA DO AR (jun/2026, retorna 404; o
    # wrapper de 2019 usava esse path). Mantido como parâmetro: se o LexML restaurar o SRU
    # (ou expuser outro), basta apontar LEXML_SRU_URL pra ele que o feed volta a funcionar.
    # Por isso NÃO está no scheduler (não roda job que sempre falha); só na rota manual.
    LEXML_SRU_URL: str = "https://www.lexml.gov.br/busca/SRU"
    FEEDS_LEXML_MAX: int = 80              # teto de registros por consulta

    # Querido Diário (ISS municipal) — CSV de territory_ids IBGE; vazio = não roda
    QUERIDO_DIARIO_API: str = "https://api.queridodiario.ok.org.br"
    FEEDS_MUNICIPIOS_IBGE: str = ""

    # Câmara dos Deputados (radar de PLs/PLPs tributários — discovery, não lei em vigor)
    CAMARA_API: str = "https://dadosabertos.camara.leg.br/api/v2"

    # Proxy de saída opcional (ex: proxy BR) — válvula de escape p/ fontes gov.br que
    # façam geo-block do IP alemão do Hetzner. Vazio = conexão direta. Aplica-se aos feeds.
    FEEDS_HTTP_PROXY: Optional[str] = None

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
