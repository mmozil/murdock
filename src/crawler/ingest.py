"""Crawler + Ingestão — busca fontes oficiais, chunka, embeda, salva."""
import logging
import re
import hashlib
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy import text as sql_text, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.tables import Document, Chunk
from src.rag.embeddings import generate_embedding, chunk_text
from src.crawler.sources import FonteOficial, get_fonte, get_fontes_ativas

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

DOMINIOS_PERMITIDOS = {".gov.br", ".jus.br", ".leg.br", ".ibpt.org.br"}


def _dominio_ok(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return any(host.endswith(d) for d in DOMINIOS_PERMITIDOS)


async def ingest_fonte(db: AsyncSession, fonte_id: str) -> dict:
    """Ingere uma fonte oficial: fetch → parse → chunk → embed → save."""
    fonte = get_fonte(fonte_id)
    if not fonte:
        return {"erro": f"Fonte '{fonte_id}' não encontrada"}
    if not _dominio_ok(fonte.url):
        return {"erro": f"Domínio não permitido: {fonte.url}"}

    logger.info(f"[INGEST] {fonte.nome}")

    # 1. Fetch
    raw = await _fetch(fonte.url, fonte.parser)
    if not raw or len(raw.strip()) < 100:
        return {"fonte_id": fonte_id, "status": "vazio", "erro": "Conteúdo vazio"}

    cleaned = _clean(raw)
    content_hash = hashlib.sha256(cleaned.encode()).hexdigest()[:16]

    # 2. Upsert document
    doc = (await db.execute(
        select(Document).where(Document.source_id == fonte_id)
    )).scalar_one_or_none()

    if doc and doc.content_hash == content_hash:
        return {"fonte_id": fonte_id, "status": "inalterado", "chunks": doc.total_chunks}

    if doc:
        # Remover chunks antigos
        await db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        doc.content_hash = content_hash
        doc.raw_size = len(cleaned)
        doc.crawled_at = datetime.now(timezone.utc)
    else:
        doc = Document(
            source_id=fonte_id,
            title=fonte.nome,
            url=fonte.url,
            source_type=fonte.source_type,
            orgao=fonte.orgao,
            fundamentacao=fonte.fundamentacao,
            content_hash=content_hash,
            raw_size=len(cleaned),
        )
        db.add(doc)
        await db.flush()

    # 3. Chunk + embed
    chunks = chunk_text(cleaned)
    count = 0

    for i, chunk_text_ in enumerate(chunks):
        embedding = generate_embedding(chunk_text_)
        if not embedding:
            continue

        chunk = Chunk(
            document_id=doc.id,
            content=chunk_text_,
            embedding=embedding,
            chunk_index=i,
            section=_detect_section(chunk_text_),
            metadata_={"fonte_id": fonte_id, "url": fonte.url},
        )
        db.add(chunk)
        count += 1

        # Flush a cada 50 chunks para não acumular memória
        if count % 50 == 0:
            await db.flush()

    doc.total_chunks = count
    await db.commit()

    logger.info(f"[INGEST] {fonte.nome}: {count} chunks ({len(cleaned):,} chars)")
    return {
        "fonte_id": fonte_id,
        "status": "ok",
        "chunks": count,
        "tamanho": len(cleaned),
    }


async def ingest_todas(db: AsyncSession, source_type: str = None) -> dict:
    """Ingere todas as fontes ativas."""
    fontes = get_fontes_ativas()
    if source_type:
        fontes = [f for f in fontes if f.source_type == source_type]

    resultados = []
    total = 0
    erros = 0

    for fonte in fontes:
        r = await ingest_fonte(db, fonte.id)
        resultados.append(r)
        if r.get("status") == "ok":
            total += r.get("chunks", 0)
        elif r.get("status") != "inalterado":
            erros += 1
        # Rate limiting
        await __import__("asyncio").sleep(2)

    return {
        "total_fontes": len(fontes),
        "sucesso": len(fontes) - erros,
        "erros": erros,
        "total_chunks": total,
        "resultados": resultados,
    }


async def update_search_vectors(db: AsyncSession):
    """Popula tsvector para busca full-text (rodar após ingestão)."""
    await db.execute(sql_text("""
        UPDATE chunks
        SET search_vector = to_tsvector('portuguese', content)
        WHERE search_vector IS NULL
    """))
    await db.commit()
    logger.info("[TSVECTOR] Vetores de busca full-text atualizados")


async def get_status(db: AsyncSession) -> dict:
    """Retorna status da knowledge base."""
    total = (await db.execute(sql_text("SELECT COUNT(*) FROM chunks"))).scalar() or 0

    por_tipo = (await db.execute(sql_text("""
        SELECT d.source_type, COUNT(c.id) as total, MAX(d.crawled_at) as ultimo
        FROM chunks c JOIN documents d ON d.id = c.document_id
        GROUP BY d.source_type ORDER BY total DESC
    """))).fetchall()

    docs = (await db.execute(
        select(Document).order_by(Document.source_type)
    )).scalars().all()

    return {
        "total_chunks": total,
        "por_tipo": [{"type": r[0], "chunks": r[1], "ultimo_crawl": r[2].isoformat() if r[2] else None} for r in por_tipo],
        "documentos": [
            {"id": d.source_id, "titulo": d.title, "chunks": d.total_chunks, "tipo": d.source_type, "url": d.url}
            for d in docs
        ],
    }


# ── Fetchers ────────────────────────────────────────────────────────────

async def _fetch(url: str, parser: str) -> Optional[str]:
    if parser == "html":
        return await _fetch_html(url)
    elif parser == "api_json":
        return await _fetch_json(url)
    return None


async def _fetch_html(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(verify=False, timeout=180, follow_redirects=True) as client:
            r = await client.get(url, headers=BROWSER_HEADERS)
            r.raise_for_status()

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            main = (
                soup.find("main")
                or soup.find("article")
                or soup.find("div", {"id": "conteudo"})
                or soup.find("div", {"id": "textoNorma"})
                or soup.find("div", {"class": "textoNorma"})
                or soup.body
            )
            return (main or soup).get_text(separator="\n", strip=True)
        except ImportError:
            text = re.sub(r"<script[^>]*>.*?</script>", "", r.text, flags=re.DOTALL | re.I)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.I)
            return re.sub(r"<[^>]+>", " ", text).strip()

    except Exception as e:
        logger.error(f"Fetch HTML {url}: {e}")
        return None


async def _fetch_json(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(verify=False, timeout=120, follow_redirects=True) as client:
            r = await client.get(url, headers={**BROWSER_HEADERS, "Accept": "application/json"})
            r.raise_for_status()

        data = r.json()
        if isinstance(data, list):
            lines = []
            for item in data[:5000]:
                if isinstance(item, dict):
                    lines.append(" | ".join(f"{k}: {v}" for k, v in item.items() if v))
            return "\n".join(lines)
        return __import__("json").dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Fetch JSON {url}: {e}")
        return None


def _clean(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{3,}", " ", text)
    return text.strip()


def _detect_section(text: str) -> Optional[str]:
    """Detecta artigo/seção da legislação no chunk."""
    m = re.search(r"(Art\.\s*\d+[\w-]*)", text[:200])
    if m:
        return m.group(1)
    m = re.search(r"(§\s*\d+[º°]?)", text[:200])
    if m:
        return m.group(1)
    return None
