"""Rotas admin dos feeds de atualização de leis (disparo manual + status).

Gated por X-API-Key (= API_KEY; liberado em dev). Permite rodar cada feed sob demanda
pra validar em produção e ver contagens reais, além do agendamento automático.
"""
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes import _check_api_key
from src.core.config import settings
from src.core.database import get_db
from src.crawler import feeds

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feeds", tags=["feeds"])


class DouIn(BaseModel):
    data: Optional[str] = None   # YYYY-MM-DD; default = hoje


class LexmlIn(BaseModel):
    query: str                   # CQL (ex: 'date >= "2026-01-01" and tipoDocumento any "Lei"')
    source_type: str = "lexml"
    max_records: Optional[int] = None


class QueridoDiarioIn(BaseModel):
    territory_ids: Optional[list[str]] = None   # códigos IBGE; default = config
    since: Optional[str] = None                 # YYYY-MM-DD


class CamaraIn(BaseModel):
    keywords: str = "reforma tributária"


@router.get("/status")
async def feeds_status(_auth: bool = Depends(_check_api_key)):
    """Estado dos feeds: quais estão habilitados e os jobs agendados."""
    try:
        from src.scheduler import scheduler

        jobs = [
            {"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
            for j in (scheduler.get_jobs() if scheduler else [])
        ]
    except Exception:
        jobs = []
    return {
        "scheduler_ativo": settings.ENABLE_FEEDS_SCHEDULER,
        "dou_habilitado": bool(settings.INLABS_EMAIL and settings.INLABS_PASSWORD),
        "municipios_querido_diario": [t for t in (settings.FEEDS_MUNICIPIOS_IBGE or "").split(",") if t.strip()],
        "jobs_agendados": jobs,
    }


@router.post("/dou")
async def trigger_dou(payload: DouIn, db: AsyncSession = Depends(get_db), _auth: bool = Depends(_check_api_key)):
    """Ingere o DOU de um dia (default hoje) via INLABS — só normas tributárias."""
    if not (settings.INLABS_EMAIL and settings.INLABS_PASSWORD):
        raise HTTPException(400, "INLABS_EMAIL/PASSWORD não configurados (registre-se grátis em inlabs.in.gov.br)")
    dia = date.fromisoformat(payload.data) if payload.data else None
    return await feeds.run_dou_daily(db, dia)


@router.post("/lexml")
async def trigger_lexml(payload: LexmlIn, db: AsyncSession = Depends(get_db), _auth: bool = Depends(_check_api_key)):
    """Ingere uma consulta LexML SRU (CQL) — legislação ou jurisprudência."""
    return await feeds.run_lexml_query(db, payload.query, payload.source_type, payload.max_records)


@router.post("/lexml/recentes")
async def trigger_lexml_recentes(dias: int = 30, db: AsyncSession = Depends(get_db), _auth: bool = Depends(_check_api_key)):
    """Re-ingere legislação federal dos últimos N dias (descobre o que mudou)."""
    return await feeds.run_lexml_recentes(db, dias)


@router.post("/querido-diario")
async def trigger_querido_diario(payload: QueridoDiarioIn, db: AsyncSession = Depends(get_db), _auth: bool = Depends(_check_api_key)):
    """Ingere diários municipais (ISS) dos territórios IBGE informados (ou da config)."""
    return await feeds.run_querido_diario(db, payload.territory_ids, payload.since)


@router.post("/camara")
async def trigger_camara(payload: CamaraIn, db: AsyncSession = Depends(get_db), _auth: bool = Depends(_check_api_key)):
    """Ingere ementas de proposições tributárias (radar de PLs/PLPs)."""
    return await feeds.run_camara_radar(db, payload.keywords)
