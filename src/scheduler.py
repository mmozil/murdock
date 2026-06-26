"""Scheduler de feeds — atualização automática da knowledge base de leis.

APScheduler (AsyncIO). Cada job abre sua própria sessão e é isolado em try/except —
um feed que falha não derruba os outros nem o app. Crons em UTC.

IMPORTANTE: CronTrigger é importado no TOPO (importá-lo dentro de uma função torna o nome
local e quebra o scheduler com UnboundLocalError — lição aprendida no Tier).
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.config import settings
from src.core.database import async_session
from src.crawler import feeds

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None


async def _job_dou_daily():
    async with async_session() as db:
        try:
            logger.info("[SCHED] DOU diário: %s", await feeds.run_dou_daily(db))
        except Exception as e:  # noqa: BLE001
            logger.error("[SCHED] DOU diário falhou: %s", e)


async def _job_camara_weekly():
    async with async_session() as db:
        try:
            logger.info("[SCHED] Câmara radar tributário: %s",
                        await feeds.run_camara_radar(db, keywords="reforma tributária"))
        except Exception as e:  # noqa: BLE001
            logger.error("[SCHED] Câmara radar falhou: %s", e)


async def _job_querido_diario_weekly():
    async with async_session() as db:
        try:
            logger.info("[SCHED] Querido Diário: %s", await feeds.run_querido_diario(db))
        except Exception as e:  # noqa: BLE001
            logger.error("[SCHED] Querido Diário falhou: %s", e)


def init_scheduler():
    """Inicia o scheduler de feeds (chamado no lifespan do app)."""
    global scheduler
    if not settings.ENABLE_FEEDS_SCHEDULER:
        logger.info("[SCHED] desativado (ENABLE_FEEDS_SCHEDULER=False)")
        return

    scheduler = AsyncIOScheduler(timezone="UTC")

    # DOU diário às 10:30 UTC (~07:30 BRT) — só se houver credenciais INLABS
    if settings.INLABS_EMAIL and settings.INLABS_PASSWORD:
        scheduler.add_job(_job_dou_daily, CronTrigger(hour=10, minute=30),
                          id="dou_daily", replace_existing=True)
    else:
        logger.warning("[SCHED] DOU diário NÃO agendado (faltam INLABS_EMAIL/PASSWORD)")

    # Câmara — radar de PLs/PLPs tributários, segunda 11:00 UTC
    # (LexML SRU está fora do ar — ver config; só roda via rota manual se restaurarem.)
    scheduler.add_job(_job_camara_weekly, CronTrigger(day_of_week="mon", hour=11, minute=0),
                      id="camara_weekly", replace_existing=True)

    # Querido Diário semanal — só se houver municípios configurados
    if (settings.FEEDS_MUNICIPIOS_IBGE or "").strip():
        scheduler.add_job(_job_querido_diario_weekly, CronTrigger(day_of_week="mon", hour=11, minute=30),
                          id="querido_diario_weekly", replace_existing=True)

    scheduler.start()
    logger.info("[SCHED] iniciado — jobs: %s", [j.id for j in scheduler.get_jobs()])


def shutdown_scheduler():
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        scheduler = None
        logger.info("[SCHED] encerrado")
