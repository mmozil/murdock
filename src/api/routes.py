"""Rotas da API do Murdock."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_db
from src.api.schemas import (
    ChatRequest, ChatResponse, IngestRequest, IngestResponse,
    FeedbackRequest, HealthResponse,
)
from src.services.agent import chat, chat_stream
from src.crawler.ingest import ingest_fonte, ingest_todas, get_status, update_search_vectors
from src.models.tables import Feedback as FeedbackModel

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Auth helper ────────────────────────────────────────────────────────────

def _check_api_key(x_api_key: str = Header(None)):
    """Valida API key para endpoints administrativos."""
    if settings.ENVIRONMENT == "development":
        return True
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida")
    return True


# ═══════════════════════════════════════════════════════════════════════════
# Chat
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/chat", response_model=None)
async def chat_endpoint(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Chat com o Murdock — streaming SSE ou resposta completa."""
    if req.stream:
        async def event_generator():
            async for event in chat_stream(db, req.message, req.conversation_id):
                yield event

        return EventSourceResponse(event_generator())

    result = await chat(db, req.message, req.conversation_id)
    return ChatResponse(**result)


# ═══════════════════════════════════════════════════════════════════════════
# Knowledge Base
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(
    req: IngestRequest,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(_check_api_key),
):
    """Ingere fontes oficiais na knowledge base."""
    if req.fonte_id:
        result = await ingest_fonte(db, req.fonte_id)
    else:
        result = await ingest_todas(db, req.source_type)

    # Atualizar tsvectors após ingestão
    await update_search_vectors(db)

    status = "ok" if result.get("status") == "ok" or "total_fontes" in result else "erro"
    return IngestResponse(status=status, detail=result)


@router.get("/status")
async def status_endpoint(
    db: AsyncSession = Depends(get_db),
):
    """Status da knowledge base."""
    return await get_status(db)


# ═══════════════════════════════════════════════════════════════════════════
# Feedback
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/feedback")
async def feedback_endpoint(
    req: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """Registra feedback sobre uma resposta."""
    fb = FeedbackModel(
        message_id=req.message_id,
        rating=req.rating,
        comment=req.comment,
    )
    db.add(fb)
    await db.commit()
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/health", response_model=HealthResponse)
async def health_endpoint(
    db: AsyncSession = Depends(get_db),
):
    """Health check do Murdock."""
    try:
        from sqlalchemy import text
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    try:
        kb = await get_status(db)
        kb_info = {"total_chunks": kb.get("total_chunks", 0), "documentos": len(kb.get("documentos", []))}
    except Exception:
        kb_info = {"total_chunks": 0, "documentos": 0}

    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        database=db_status,
        knowledge_base=kb_info,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Fontes
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/sources")
async def sources_endpoint():
    """Lista fontes oficiais registradas."""
    from src.crawler.sources import FONTES
    return [
        {
            "id": f.id,
            "nome": f.nome,
            "url": f.url,
            "source_type": f.source_type,
            "orgao": f.orgao,
            "fundamentacao": f.fundamentacao,
        }
        for f in FONTES
    ]
