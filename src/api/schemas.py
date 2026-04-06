"""Schemas Pydantic para a API do Murdock."""
from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    """Request para o endpoint /chat."""
    message: str = Field(..., min_length=1, max_length=5000, description="Mensagem do usuário")
    conversation_id: Optional[str] = Field(None, description="ID da conversa (para continuar)")
    stream: bool = Field(True, description="Se True, resposta via SSE streaming")


class ChatResponse(BaseModel):
    """Response do endpoint /chat (modo não-streaming)."""
    conversation_id: str
    response: str
    model: str
    latency_ms: int


class IngestRequest(BaseModel):
    """Request para ingerir uma fonte."""
    fonte_id: Optional[str] = Field(None, description="ID da fonte específica")
    source_type: Optional[str] = Field(None, description="Tipo de fonte para ingestão em batch")


class IngestResponse(BaseModel):
    """Response de ingestão."""
    status: str
    detail: dict


class FeedbackRequest(BaseModel):
    """Feedback sobre uma resposta."""
    message_id: str
    rating: int = Field(..., ge=0, le=5)
    comment: Optional[str] = None


class HealthResponse(BaseModel):
    """Response do health check."""
    status: str
    version: str
    database: str
    knowledge_base: dict


class StatusResponse(BaseModel):
    """Status da knowledge base."""
    total_chunks: int
    por_tipo: list[dict]
    documentos: list[dict]
