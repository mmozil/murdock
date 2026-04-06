"""Serviço de embeddings — Gemini embedding-001 com cache."""
import logging
import hashlib
from typing import Optional
from functools import lru_cache

from src.core.config import settings

logger = logging.getLogger(__name__)

# Cliente Gemini (new SDK)
_genai_client = None


def _get_client():
    """Lazy init do cliente Gemini."""
    global _genai_client
    if _genai_client is None:
        try:
            from google import genai
            _genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        except Exception as e:
            logger.error(f"Falha ao inicializar Gemini client: {e}")
    return _genai_client


@lru_cache(maxsize=1000)
def _cached_embed(text_hash: str, text: str, task: str) -> Optional[tuple]:
    """Gera embedding com cache LRU."""
    client = _get_client()
    if not client:
        return None
    try:
        result = client.models.embed_content(
            model=settings.EMBEDDING_MODEL,
            contents=text,
            config={
                "task_type": task,
                "output_dimensionality": settings.EMBEDDING_DIMENSIONS,
            },
        )
        return tuple(result.embeddings[0].values)
    except Exception as e:
        logger.error(f"Erro embedding: {e}")
        return None


def generate_embedding(text: str, task: str = "RETRIEVAL_DOCUMENT") -> Optional[list[float]]:
    """Gera embedding para um texto."""
    if not text or not text.strip():
        return None
    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    result = _cached_embed(text_hash, text[:8000], task)  # Limitar a 8k chars
    return list(result) if result else None


def generate_query_embedding(query: str) -> Optional[list[float]]:
    """Gera embedding otimizado para query de busca."""
    return generate_embedding(query, task="RETRIEVAL_QUERY")


def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> list[str]:
    """Divide texto em chunks com overlap, quebrando em pontos naturais."""
    chunk_size = chunk_size or settings.CHUNK_SIZE
    overlap = overlap or settings.CHUNK_OVERLAP

    if not text or len(text) < 100:
        return [text] if text else []

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            # Quebra natural: artigo de lei, parágrafo, ponto final
            for sep in ["\nArt. ", "\n§ ", "\n\n", "\n", ". "]:
                pos = text.rfind(sep, start + chunk_size // 2, end)
                if pos != -1:
                    end = pos + len(sep)
                    break

        chunk = text[start:end].strip()
        if chunk and len(chunk) > 30:
            chunks.append(chunk)

        start = end - overlap

    return chunks
