"""Feeds de atualização automática de leis — fontes oficiais GRATUITAS.

Cada feed tem um fetcher (rede → lista normalizada) + um orquestrador `run_*` que
ingere na knowledge base (reusa `ingest.upsert_document`). Tudo é defensivo: falha de
rede/credencial → loga e devolve resumo, NUNCA levanta pro caller (graceful degradation).

Feeds:
- DOU via INLABS (Imprensa Nacional): full text de toda norma nova publicada no Diário
  Oficial da União. É o motor do "sempre atualizado". Requer conta grátis (INLABS_EMAIL/SENHA).
- LexML SRU: legislação + jurisprudência (STF/STJ) federal/estadual/municipal — metadados +
  ementa. Sem auth, padrão Library of Congress (SRU/CQL).
- Querido Diário (Open Knowledge Brasil): diários oficiais MUNICIPAIS (ISS) — REST público.
- Câmara dos Deputados: radar de PLs/PLPs tributários (discovery; não é lei em vigor).
"""
import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

from src.core.config import settings
from src.crawler.ingest import update_search_vectors, upsert_document

logger = logging.getLogger(__name__)

_UA = "Murdock/1.0 (+https://murdock.hovio.com.br; tributario-ai)"


def _http(**kw) -> httpx.AsyncClient:
    """AsyncClient com proxy opcional (FEEDS_HTTP_PROXY) — válvula p/ geo-block gov.br."""
    proxy = (settings.FEEDS_HTTP_PROXY or "").strip() or None
    return httpx.AsyncClient(verify=False, follow_redirects=True, proxy=proxy, **kw)


def _keywords() -> list[str]:
    return [k.strip().lower() for k in (settings.FEEDS_TAX_KEYWORDS or "").split(",") if k.strip()]


def _matches_tax(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in _keywords())


def _strip_html(html: str) -> str:
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)
    except Exception:
        import re

        return re.sub(r"<[^>]+>", " ", html)


def _ln(tag: str) -> str:
    """Local name de um tag XML (remove namespace)."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


# ═══════════════════════════════════════════════════════════════════════════
# DOU via INLABS — Diário Oficial da União (full text de toda norma nova)
# ═══════════════════════════════════════════════════════════════════════════

INLABS_LOGIN_URL = "https://inlabs.in.gov.br/logar.php"
INLABS_DOWNLOAD_URL = "https://inlabs.in.gov.br/index.php?p="


async def fetch_dou_inlabs(dia: Optional[date] = None, secoes: Optional[list[str]] = None) -> list[dict]:
    """Baixa e parseia os artigos do DOU de um dia via INLABS.

    Retorna [{source_id, identifica, ementa, texto, art_type, art_category, pub_name,
    pub_date, url}]. Lista vazia se sem credenciais, edição inexistente (fim de semana)
    ou falha — nunca levanta.
    """
    if not (settings.INLABS_EMAIL and settings.INLABS_PASSWORD):
        logger.warning("[DOU] INLABS_EMAIL/PASSWORD ausentes — feed do DOU desativado")
        return []

    dia = dia or datetime.now(timezone.utc).date()
    secoes = secoes or [s for s in (settings.FEEDS_DOU_SECOES or "DO1").split() if s]
    data_str = dia.strftime("%Y-%m-%d")
    artigos: list[dict] = []

    try:
        async with _http(timeout=180) as cli:
            # 1. Login → cookie inlabs_session_cookie
            await cli.post(
                INLABS_LOGIN_URL,
                data={"email": settings.INLABS_EMAIL, "password": settings.INLABS_PASSWORD},
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": _UA},
            )
            cookie = cli.cookies.get("inlabs_session_cookie")
            if not cookie:
                logger.error("[DOU] login INLABS falhou (sem cookie) — checar credenciais")
                return []

            # 2. Download do ZIP por seção
            for secao in secoes:
                arq = f"{data_str}-{secao}.zip"
                url = f"{INLABS_DOWNLOAD_URL}{data_str}&dl={arq}"
                r = await cli.get(
                    url,
                    headers={
                        "Cookie": f"inlabs_session_cookie={cookie}",
                        "origem": "736372697074",
                        "User-Agent": _UA,
                    },
                )
                if r.status_code != 200 or not r.content:
                    logger.info("[DOU] %s indisponível (HTTP %s)", arq, r.status_code)
                    continue
                artigos.extend(_parse_dou_zip(r.content, secao, data_str))
    except Exception as e:  # noqa: BLE001
        logger.error("[DOU] erro ao buscar INLABS: %s", e)
        return artigos

    logger.info("[DOU] %s: %d artigos brutos baixados", data_str, len(artigos))
    return artigos


def _parse_dou_zip(content: bytes, secao: str, data_str: str) -> list[dict]:
    out: list[dict] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except Exception as e:  # noqa: BLE001
        logger.error("[DOU] zip inválido (%s): %s", secao, e)
        return out

    for name in zf.namelist():
        if not name.lower().endswith(".xml"):
            continue
        try:
            raw = zf.read(name)
            root = ET.fromstring(raw)
        except Exception:
            continue
        # root pode ser <article> ou conter <article>
        art = root if _ln(root.tag) == "article" else next(
            (e for e in root.iter() if _ln(e.tag) == "article"), None
        )
        if art is None:
            continue
        attrs = art.attrib
        body = next((e for e in art.iter() if _ln(e.tag) == "body"), None)

        def _field(tag: str) -> str:
            if body is None:
                return ""
            el = next((e for e in body.iter() if _ln(e.tag) == tag), None)
            return (el.text or "").strip() if el is not None and el.text else ""

        identifica = _field("Identifica")
        ementa = _field("Ementa")
        texto = _strip_html(_field("Texto"))
        out.append({
            "source_id": f"dou_{secao}_{data_str}_{attrs.get('idMateria') or attrs.get('id') or name}",
            "identifica": identifica,
            "ementa": ementa,
            "texto": texto,
            "art_type": attrs.get("artType", ""),
            "art_category": attrs.get("artCategory", ""),
            "pub_name": attrs.get("pubName", secao),
            "pub_date": attrs.get("pubDate", data_str),
            "url": "https://www.in.gov.br/leiturajornal",
        })
    return out


async def run_dou_daily(db, dia: Optional[date] = None) -> dict:
    """Ingere as normas tributárias do DOU do dia (filtra por palavras-chave fiscais)."""
    artigos = await fetch_dou_inlabs(dia)
    if not artigos:
        return {"feed": "dou", "status": "vazio", "ingeridos": 0}

    relevantes = [
        a for a in artigos
        if _matches_tax(f"{a['identifica']} {a['ementa']} {a['art_category']} {a['texto'][:2000]}")
    ]
    capped = relevantes[: settings.FEEDS_DOU_MAX_ARTIGOS]
    if len(relevantes) > len(capped):
        logger.warning("[DOU] %d relevantes, ingerindo só %d (teto)", len(relevantes), len(capped))

    ingeridos = 0
    for a in capped:
        corpo = "\n\n".join(filter(None, [a["identifica"], a["ementa"], a["texto"]]))
        if not corpo.strip():
            continue
        try:
            res = await upsert_document(
                db,
                source_id=a["source_id"],
                title=(a["identifica"] or a["ementa"] or a["source_id"])[:480],
                url=a["url"],
                source_type="dou_norma",
                orgao=a["art_category"][:200],
                fundamentacao=f"DOU {a['pub_name']} {a['pub_date']} — {a['art_type']}"[:480],
                text=corpo,
                metadata={"feed": "dou", "art_type": a["art_type"], "pub_date": a["pub_date"]},
                commit=False,
            )
            if res["status"] in ("ok", "inalterado"):
                ingeridos += 1 if res["status"] == "ok" else 0
        except Exception as e:  # noqa: BLE001
            logger.warning("[DOU] falha ao ingerir %s: %s", a["source_id"], e)

    await db.commit()
    await update_search_vectors(db)
    logger.info("[DOU] dia ingerido: %d/%d relevantes", ingeridos, len(relevantes))
    return {"feed": "dou", "status": "ok", "brutos": len(artigos), "relevantes": len(relevantes), "ingeridos": ingeridos}


# ═══════════════════════════════════════════════════════════════════════════
# LexML SRU — legislação + jurisprudência (federal/estadual/municipal)
# ═══════════════════════════════════════════════════════════════════════════

async def search_lexml(cql: str, max_records: Optional[int] = None) -> list[dict]:
    """Consulta a API SRU do LexML (CQL). Retorna registros com metadados + ementa."""
    max_records = max_records or settings.FEEDS_LEXML_MAX
    params = {
        "operation": "searchRetrieve",
        "version": "1.1",
        "query": cql,
        "startRecord": "1",
        "maximumRecords": str(min(max_records, 100)),
    }
    try:
        async with _http(timeout=90) as cli:
            r = await cli.get(settings.LEXML_SRU_URL, params=params, headers={"User-Agent": _UA})
            r.raise_for_status()
        return _parse_sru(r.text)
    except Exception as e:  # noqa: BLE001
        logger.error("[LexML] erro SRU (%s): %s", cql, e)
        return []


def _parse_sru(xml_str: str) -> list[dict]:
    out: list[dict] = []
    try:
        root = ET.fromstring(xml_str)
    except Exception as e:  # noqa: BLE001
        logger.error("[LexML] XML inválido: %s", e)
        return out

    wanted = {"tipoDocumento", "urn", "localidade", "autoridade", "title",
              "description", "subject", "type", "identifier", "date"}
    for rd in root.iter():
        if _ln(rd.tag) != "recordData":
            continue
        fields: dict = {}
        for el in rd.iter():
            ln = _ln(el.tag)
            if ln in wanted and el.text and el.text.strip():
                fields.setdefault(ln, el.text.strip())
        if fields.get("urn") or fields.get("title"):
            out.append(fields)
    return out


async def run_lexml_query(db, cql: str, source_type: str = "lexml", max_records: Optional[int] = None) -> dict:
    """Ingere os metadados+ementa de uma consulta LexML como chunks (citáveis na busca)."""
    registros = await search_lexml(cql, max_records)
    if not registros:
        return {"feed": "lexml", "status": "vazio", "ingeridos": 0, "query": cql}

    ingeridos = 0
    for reg in registros:
        urn = reg.get("urn", "")
        title = reg.get("title", "") or urn
        desc = reg.get("description", "")
        corpo = "\n".join(filter(None, [
            title,
            f"Ementa: {desc}" if desc else "",
            f"Tipo: {reg.get('tipoDocumento', '')}" if reg.get("tipoDocumento") else "",
            f"Localidade: {reg.get('localidade', '')}" if reg.get("localidade") else "",
            f"Autoridade: {reg.get('autoridade', '')}" if reg.get("autoridade") else "",
            f"Data: {reg.get('date', '')}" if reg.get("date") else "",
            f"URN: {urn}" if urn else "",
        ]))
        sid = f"lexml_{urn}" if urn else f"lexml_{reg.get('identifier', title)[:80]}"
        url = f"https://www.lexml.gov.br/urn/{urn}" if urn else settings.LEXML_SRU_URL
        try:
            res = await upsert_document(
                db, source_id=sid, title=title[:480], url=url, source_type=source_type,
                orgao=reg.get("autoridade", "")[:200], fundamentacao=reg.get("tipoDocumento", "")[:480],
                text=corpo, metadata={"feed": "lexml", "urn": urn, "localidade": reg.get("localidade", "")},
                commit=False,
            )
            if res["status"] == "ok":
                ingeridos += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("[LexML] falha ao ingerir %s: %s", sid, e)

    await db.commit()
    await update_search_vectors(db)
    logger.info("[LexML] '%s': %d/%d ingeridos", cql, ingeridos, len(registros))
    return {"feed": "lexml", "status": "ok", "encontrados": len(registros), "ingeridos": ingeridos, "query": cql}


async def run_lexml_recentes(db, dias: int = 30) -> dict:
    """Re-ingere legislação federal recente (últimos N dias) — descobre o que mudou."""
    desde = (datetime.now(timezone.utc).date() - timedelta(days=dias)).isoformat()
    cql = f'date >= "{desde}" and tipoDocumento any "Lei Decreto Medida"'
    return await run_lexml_query(db, cql, source_type="lexml_legislacao")


# ═══════════════════════════════════════════════════════════════════════════
# Querido Diário — diários oficiais MUNICIPAIS (ISS)
# ═══════════════════════════════════════════════════════════════════════════

async def fetch_querido_diario(
    territory_ids: list[str], querystring: str = "ISS imposto sobre serviços",
    published_since: Optional[str] = None, size: int = 10,
) -> list[dict]:
    """Busca diários municipais no Querido Diário. territory_ids = códigos IBGE."""
    results: list[dict] = []
    try:
        async with _http(timeout=90) as cli:
            for tid in territory_ids:
                params = {
                    "territory_ids": tid,
                    "querystring": querystring,
                    "size": str(size),
                    "excerpt_size": "500",
                    "number_of_excerpts": "3",
                }
                if published_since:
                    params["published_since"] = published_since
                r = await cli.get(f"{settings.QUERIDO_DIARIO_API}/gazettes", params=params,
                                  headers={"User-Agent": _UA, "Accept": "application/json"})
                if r.status_code != 200:
                    logger.info("[QD] territory %s HTTP %s", tid, r.status_code)
                    continue
                data = r.json()
                results.extend(data.get("gazettes", []))
    except Exception as e:  # noqa: BLE001
        logger.error("[QD] erro: %s", e)
    return results


async def run_querido_diario(db, territory_ids: Optional[list[str]] = None, since: Optional[str] = None) -> dict:
    """Ingere diários municipais (ISS) dos territórios configurados."""
    if territory_ids is None:
        territory_ids = [t.strip() for t in (settings.FEEDS_MUNICIPIOS_IBGE or "").split(",") if t.strip()]
    if not territory_ids:
        return {"feed": "querido_diario", "status": "sem_municipios", "ingeridos": 0}

    gazettes = await fetch_querido_diario(territory_ids, published_since=since)
    ingeridos = 0
    for g in gazettes:
        excerpts = "\n\n".join(g.get("excerpts", []) or [])
        if not excerpts.strip():
            continue
        tid = g.get("territory_id", "")
        gdate = g.get("date", "")
        sid = f"qd_{tid}_{gdate}_{g.get('edition', '')}"
        try:
            res = await upsert_document(
                db, source_id=sid,
                title=f"Diário Oficial {g.get('territory_name', tid)}/{g.get('state_code', '')} — {gdate}"[:480],
                url=g.get("url") or g.get("txt_url") or settings.QUERIDO_DIARIO_API,
                source_type="diario_municipal", orgao=g.get("territory_name", "")[:200],
                fundamentacao=f"Diário municipal {gdate}"[:480], text=excerpts,
                metadata={"feed": "querido_diario", "territory_id": tid, "date": gdate},
                commit=False,
            )
            if res["status"] == "ok":
                ingeridos += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("[QD] falha %s: %s", sid, e)

    await db.commit()
    await update_search_vectors(db)
    return {"feed": "querido_diario", "status": "ok", "encontrados": len(gazettes), "ingeridos": ingeridos}


# ═══════════════════════════════════════════════════════════════════════════
# Câmara dos Deputados — radar de PLs/PLPs tributários (discovery)
# ═══════════════════════════════════════════════════════════════════════════

async def fetch_camara_proposicoes(keywords: str = "tributário", ano: Optional[int] = None) -> list[dict]:
    """Lista proposições (PL/PLP) por palavra-chave — radar do que pode virar lei."""
    ano = ano or datetime.now(timezone.utc).year
    params = {"keywords": keywords, "ano": str(ano), "siglaTipo": "PL,PLP",
              "ordem": "DESC", "ordenarPor": "id", "itens": "50"}
    try:
        async with _http(timeout=60) as cli:
            r = await cli.get(f"{settings.CAMARA_API}/proposicoes", params=params,
                              headers={"User-Agent": _UA, "Accept": "application/json"})
            r.raise_for_status()
            return r.json().get("dados", [])
    except Exception as e:  # noqa: BLE001
        logger.error("[Camara] erro: %s", e)
        return []


async def run_camara_radar(db, keywords: str = "reforma tributária") -> dict:
    """Ingere ementas de proposições tributárias recentes (radar, não lei em vigor)."""
    props = await fetch_camara_proposicoes(keywords)
    ingeridos = 0
    for p in props:
        ementa = p.get("ementa", "")
        if not ementa:
            continue
        sid = f"camara_{p.get('id')}"
        title = f"{p.get('siglaTipo', '')} {p.get('numero', '')}/{p.get('ano', '')}"
        try:
            res = await upsert_document(
                db, source_id=sid, title=title[:480],
                url=p.get("uri", settings.CAMARA_API), source_type="proposicao_camara",
                orgao="Câmara dos Deputados", fundamentacao="Proposição em tramitação (radar)",
                text=f"{title}\nEmenta: {ementa}", metadata={"feed": "camara", "id": p.get("id")},
                commit=False,
            )
            if res["status"] == "ok":
                ingeridos += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("[Camara] falha %s: %s", sid, e)

    await db.commit()
    await update_search_vectors(db)
    return {"feed": "camara", "status": "ok", "encontrados": len(props), "ingeridos": ingeridos}
