"""Modelos do Murdock — PostgreSQL + pgvector."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, Boolean,
    ForeignKey, Index, func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, TSVECTOR
from pgvector.sqlalchemy import Vector
from src.core.database import Base
from src.core.config import settings


def utcnow():
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════
# Documentos e Chunks (Knowledge Base)
# ═══════════════════════════════════════════════════════════════════════════

class Document(Base):
    """Documento fonte oficial ingerido."""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(String(100), unique=True, nullable=False, index=True)  # ex: "lc_123_2006"
    title = Column(String(500), nullable=False)
    url = Column(String(2000), nullable=False)
    source_type = Column(String(50), nullable=False, index=True)  # fiscal_legislacao, fiscal_stf, etc.
    orgao = Column(String(200))
    fundamentacao = Column(String(500))
    content_hash = Column(String(64))  # SHA-256 para deduplicação
    total_chunks = Column(Integer, default=0)
    raw_size = Column(Integer, default=0)  # tamanho do texto original
    crawled_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        Index("ix_documents_type_active", "source_type", "is_active"),
    )


class Chunk(Base):
    """Chunk de texto com embedding vetorial + busca full-text."""
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(settings.EMBEDDING_DIMENSIONS), nullable=False)

    # Full-text search (tsvector para busca BM25-like)
    search_vector = Column(TSVECTOR)

    # Metadata
    chunk_index = Column(Integer, default=0)  # posição no documento
    section = Column(String(500))  # seção/artigo da lei
    metadata_ = Column("metadata", JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        # HNSW index para busca vetorial rápida
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # GIN index para full-text search
        Index("ix_chunks_search_vector", "search_vector", postgresql_using="gin"),
        # Index para filtro por documento
        Index("ix_chunks_document_idx", "document_id", "chunk_index"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Conversas e Mensagens
# ═══════════════════════════════════════════════════════════════════════════

class Conversation(Base):
    """Sessão de conversa com o Murdock."""
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(300))
    client_id = Column(String(100), index=True)  # identificador do cliente/usuário
    model_used = Column(String(100))
    total_messages = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Message(Base):
    """Mensagem individual na conversa."""
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant, system, tool
    content = Column(Text, nullable=False)

    # RAG metadata
    sources_used = Column(JSONB)  # [{url, title, similarity}]
    tools_called = Column(JSONB)  # [{tool_name, args, result_summary}]
    model_used = Column(String(100))
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
    )


class Feedback(Base):
    """Feedback do usuário sobre resposta."""
    __tablename__ = "feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer)  # 1-5 ou thumbs up/down (1/0)
    comment = Column(Text)
    learned = Column(Boolean, default=False)  # se já foi processado pelo learning loop
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ═══════════════════════════════════════════════════════════════════════════
# Client Memory — perfil persistente do cliente
# ═══════════════════════════════════════════════════════════════════════════

class ClientProfile(Base):
    """Perfil persistente do cliente — o agente nunca mais pede info que já tem."""
    __tablename__ = "client_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(100), unique=True, nullable=False, index=True)

    # Dados fiscais extraídos das conversas
    nome = Column(String(300))
    regime_tributario = Column(String(50))       # simples, lucro_presumido, lucro_real, mei
    cnae_principal = Column(String(20))
    cnaes_secundarios = Column(JSONB)            # ["6201-5/01", ...]
    uf = Column(String(2))
    municipio = Column(String(200))
    faturamento_12m = Column(Float)              # faturamento últimos 12 meses
    tipo_atividade = Column(String(100))         # software, comercio, servicos, industria
    cnpj = Column(String(20))
    porte = Column(String(20))                   # mei, me, epp, medio, grande
    funcionarios = Column(Integer)
    folha_pagamento = Column(Float)

    # Contexto adicional (livre)
    notas = Column(JSONB, default=list)          # notas livres extraídas das conversas

    # Metadata
    total_conversas = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
