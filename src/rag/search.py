"""Hybrid Search — pgvector (dense) + tsvector (sparse) + RRF fusion."""
import logging
from typing import Optional
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.rag.embeddings import generate_query_embedding

logger = logging.getLogger(__name__)


async def hybrid_search(
    db: AsyncSession,
    query: str,
    limit: int = None,
    source_type: str = None,
    min_similarity: float = None,
) -> list[dict]:
    """
    Busca híbrida: dense (pgvector cosine) + sparse (tsvector ts_rank) + RRF fusion.

    1. Dense search: embedding query → pgvector <=> cosine distance → top-20
    2. Sparse search: tsvector @@ plainto_tsquery('portuguese', query) → top-20
    3. RRF fusion: score = sum(1/(k + rank_i)) para cada resultado
    4. Retorna top-N com score RRF, conteúdo e metadata

    Args:
        db: Sessão async do banco
        query: Texto da consulta
        limit: Máximo de resultados (default: settings.MAX_RESULTS)
        source_type: Filtrar por tipo de fonte (opcional)
        min_similarity: Similaridade mínima vetorial (default: settings.MIN_SIMILARITY)

    Returns:
        Lista de dicts com content, similarity, url, title, source_type, rrf_score
    """
    limit = limit or settings.MAX_RESULTS
    min_sim = min_similarity or settings.MIN_SIMILARITY
    k = settings.RRF_K

    # Gerar embedding da query
    query_embedding = generate_query_embedding(query)
    if not query_embedding:
        logger.warning("Falha ao gerar embedding da query — fallback para sparse only")
        return await _sparse_search(db, query, limit, source_type)

    vector_str = f"[{','.join(map(str, query_embedding))}]"

    # Query SQL com RRF fusion
    type_filter = "AND d.source_type = :source_type" if source_type else ""

    sql = sql_text(f"""
        WITH dense AS (
            SELECT
                c.id,
                c.content,
                c.section,
                c.metadata,
                d.title AS doc_title,
                d.url AS doc_url,
                d.source_type,
                d.fundamentacao,
                1 - (c.embedding <=> :query_vector) AS similarity,
                ROW_NUMBER() OVER (ORDER BY c.embedding <=> :query_vector) AS rank
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.is_active = true
                AND 1 - (c.embedding <=> :query_vector) > :min_sim
                {type_filter}
            ORDER BY c.embedding <=> :query_vector
            LIMIT 20
        ),
        sparse AS (
            SELECT
                c.id,
                c.content,
                c.section,
                c.metadata,
                d.title AS doc_title,
                d.url AS doc_url,
                d.source_type,
                d.fundamentacao,
                ts_rank_cd(c.search_vector, plainto_tsquery('portuguese', :query)) AS text_rank,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank_cd(c.search_vector, plainto_tsquery('portuguese', :query)) DESC
                ) AS rank
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.is_active = true
                AND c.search_vector @@ plainto_tsquery('portuguese', :query)
                {type_filter}
            ORDER BY text_rank DESC
            LIMIT 20
        ),
        fused AS (
            SELECT
                COALESCE(dense.id, sparse.id) AS id,
                COALESCE(dense.content, sparse.content) AS content,
                COALESCE(dense.section, sparse.section) AS section,
                COALESCE(dense.metadata, sparse.metadata) AS metadata,
                COALESCE(dense.doc_title, sparse.doc_title) AS doc_title,
                COALESCE(dense.doc_url, sparse.doc_url) AS doc_url,
                COALESCE(dense.source_type, sparse.source_type) AS source_type,
                COALESCE(dense.fundamentacao, sparse.fundamentacao) AS fundamentacao,
                COALESCE(dense.similarity, 0) AS similarity,
                -- RRF Score
                COALESCE(1.0 / (:k + dense.rank), 0) +
                COALESCE(1.0 / (:k + sparse.rank), 0) AS rrf_score
            FROM dense
            FULL OUTER JOIN sparse ON dense.id = sparse.id
        )
        SELECT * FROM fused
        ORDER BY rrf_score DESC
        LIMIT :limit
    """)

    params = {
        "query_vector": vector_str,
        "query": query,
        "min_sim": min_sim,
        "k": k,
        "limit": limit,
    }
    if source_type:
        params["source_type"] = source_type

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()

        return [
            {
                "content": row.content,
                "section": row.section or "",
                "similarity": round(float(row.similarity), 4),
                "rrf_score": round(float(row.rrf_score), 6),
                "source": {
                    "title": row.doc_title,
                    "url": row.doc_url,
                    "type": row.source_type,
                    "fundamentacao": row.fundamentacao or "",
                },
                "metadata": row.metadata or {},
            }
            for row in rows
        ]

    except Exception as e:
        logger.error(f"Erro hybrid search: {e}")
        return []


async def _sparse_search(
    db: AsyncSession, query: str, limit: int, source_type: str = None
) -> list[dict]:
    """Fallback: busca full-text pura (sem vetores)."""
    type_filter = "AND d.source_type = :source_type" if source_type else ""

    sql = sql_text(f"""
        SELECT
            c.content,
            c.section,
            c.metadata,
            d.title AS doc_title,
            d.url AS doc_url,
            d.source_type,
            d.fundamentacao,
            ts_rank_cd(c.search_vector, plainto_tsquery('portuguese', :query)) AS text_rank
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.is_active = true
            AND c.search_vector @@ plainto_tsquery('portuguese', :query)
            {type_filter}
        ORDER BY text_rank DESC
        LIMIT :limit
    """)

    params = {"query": query, "limit": limit}
    if source_type:
        params["source_type"] = source_type

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()
        return [
            {
                "content": row.content,
                "section": row.section or "",
                "similarity": 0.0,
                "rrf_score": round(float(row.text_rank), 6),
                "source": {
                    "title": row.doc_title,
                    "url": row.doc_url,
                    "type": row.source_type,
                    "fundamentacao": row.fundamentacao or "",
                },
                "metadata": row.metadata or {},
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Erro sparse search: {e}")
        return []
