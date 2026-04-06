# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Summary

Murdock é um agente IA especializado em direito tributário, contábil e fiscal brasileiro. Deploy em `murdock.hovio.com.br`. Usa Pydantic AI como framework de agente, Gemini 2.5 Flash como LLM primário, PostgreSQL+pgvector para RAG, e knowledge base alimentada exclusivamente por fontes oficiais gov.br.

## Commands

```bash
# Dev (requer PostgreSQL com pgvector + Redis)
uvicorn main:app --reload --port 8010

# Docker (inclui PostgreSQL + Redis)
docker compose up -d

# Ingestão da knowledge base (após subir o servidor)
curl -X POST http://localhost:8010/api/ingest -H "Content-Type: application/json" -d '{}'

# Lint
ruff check src/ --fix && ruff format src/
```

## Architecture

```
main.py                    → FastAPI app (entry point, porta 8010)
src/
  core/
    config.py              → Pydantic Settings (DATABASE_URL, GEMINI_API_KEY, etc.)
    database.py            → AsyncPG engine, session factory, init_db()
  models/
    tables.py              → Document, Chunk (pgvector 768d), Conversation, Message, Feedback
  rag/
    embeddings.py          → Gemini embedding-001 (768d, LRU cache)
    search.py              → Hybrid search: pgvector cosine + tsvector BM25 + RRF fusion
  crawler/
    sources.py             → 15 FonteOficial (gov.br, jus.br, leg.br)
    ingest.py              → Fetch → parse → chunk → embed → save (dedup por content_hash)
  tools/
    tools.py               → 7 tools Pydantic AI (search_law, calculate_tax, check_ncm, reform_2026, credit_recovery, calendar, jurisprudence)
  services/
    agent.py               → Pydantic AI agent (Gemini Flash + fallback Claude), chat + chat_stream
  api/
    schemas.py             → Pydantic request/response models
    routes.py              → POST /chat (SSE), POST /ingest, GET /status, GET /health, GET /sources, POST /feedback
  static/
    index.html             → Chat UI Harvey.ai design (m.murdock, warm neutrals, Source Serif 4, SSE streaming)
```

## Key Patterns

- **Hybrid Search (RRF)**: Dense (pgvector cosine) + Sparse (tsvector ts_rank_cd) + RRF fusion. Score = sum(1/(k + rank_i)), k=60.
- **Agent Framework**: Pydantic AI v0.2+. Tools recebem `RunContext[MurdockDeps]` com sessão DB. Model fallback: Gemini Flash → Claude Sonnet.
- **SSE Streaming**: `sse-starlette` no backend, `EventSource` no frontend. Events: `token`, `done`, `error`.
- **Embeddings**: Gemini embedding-001, 768 dimensões, LRU cache 1000 entries. Task types: RETRIEVAL_DOCUMENT (ingest), RETRIEVAL_QUERY (search).
- **Crawler**: Domain validation (.gov.br, .jus.br, .leg.br, .ibpt.org.br). Browser-like headers. Parsers: HTML (BeautifulSoup), JSON API. Dedup via SHA-256 content hash.
- **Chunking**: 1000 chars, 150 overlap, quebra natural em Art./§/parágrafo.

## Environment

```bash
DATABASE_URL=postgresql+asyncpg://murdock:murdock@localhost:5432/murdock
REDIS_URL=redis://localhost:6379/5
GEMINI_API_KEY=...         # Google AI (embeddings + LLM)
ANTHROPIC_API_KEY=...      # Fallback LLM
API_KEY=...                # Auth para endpoints admin
```

## Design

- **Estilo**: Harvey.ai editorial — warm neutrals, serif headlines, zero decoração
- **Nome visual**: "m.murdock" (Source Serif 4) + "TAX & LEGAL AI" (subtítulo)
- **Paleta**: warm grays (#0f0e0d ink → #fafaf9 ivory)
- **Fontes**: Source Serif 4 (headlines, Google Fonts) + system sans (body)
- **Radius**: 4px, sem cores de acento, espaçamento generoso

## Deploy

- **Repo**: github.com/mmozil/murdock (público)
- **Domínio**: murdock.hovio.com.br
- **Coolify App**: `xw0wks4oo0gcsossss4kowc4`
- **Coolify PostgreSQL**: `sk4csooc8g8owkkk444sckos` (pgvector:pg16)
- **Coolify Redis**: `yg800wc0kws4k8o444g44gg4`
- **Coolify Project**: `s88c48s0kg884ck8s0gow440` (Hovio)
- **Deploy trigger**: `curl -s "https://apps.cloudesneper.com.br/api/v1/deploy?uuid=xw0wks4oo0gcsossss4kowc4&force=false" -H "Authorization: Bearer 5|claude-deploy-token-2026"`
- **Docker build**: Python 3.12-slim, porta 8010
- **DB**: PostgreSQL 16 + pgvector (docker-compose inclui)
