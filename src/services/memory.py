"""Client Memory — extrai e persiste perfil do cliente a partir das conversas."""
import logging
import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tables import ClientProfile

logger = logging.getLogger(__name__)

# Mapeamento de termos para valores normalizados
REGIME_MAP = {
    "simples": "simples", "simples nacional": "simples",
    "lucro presumido": "lucro_presumido", "presumido": "lucro_presumido", "lp": "lucro_presumido",
    "lucro real": "lucro_real", "real": "lucro_real", "lr": "lucro_real",
    "mei": "mei", "microempreendedor": "mei",
}

REGIME_DISPLAY = {
    "simples": "Simples Nacional",
    "lucro_presumido": "Lucro Presumido",
    "lucro_real": "Lucro Real",
    "mei": "MEI",
}


async def get_or_create_profile(db: AsyncSession, client_id: str) -> ClientProfile:
    """Obtém ou cria perfil do cliente."""
    profile = (await db.execute(
        select(ClientProfile).where(ClientProfile.client_id == client_id)
    )).scalar_one_or_none()

    if not profile:
        profile = ClientProfile(client_id=client_id)
        db.add(profile)
        await db.flush()

    return profile


async def get_profile(db: AsyncSession, client_id: str) -> Optional[ClientProfile]:
    """Obtém perfil do cliente (sem criar)."""
    return (await db.execute(
        select(ClientProfile).where(ClientProfile.client_id == client_id)
    )).scalar_one_or_none()


async def update_profile(db: AsyncSession, client_id: str, updates: dict) -> ClientProfile:
    """Atualiza perfil do cliente com novos dados."""
    profile = await get_or_create_profile(db, client_id)

    for key, value in updates.items():
        if value is not None and hasattr(profile, key):
            setattr(profile, key, value)

    await db.flush()
    return profile


def extract_profile_from_message(text: str) -> dict:
    """Extrai dados de perfil fiscal a partir de texto da conversa."""
    import re
    extracted = {}
    text_lower = text.lower()

    # Regime tributário
    for term, regime in REGIME_MAP.items():
        if term in text_lower:
            extracted["regime_tributario"] = regime
            break

    # CNPJ
    cnpj_match = re.search(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", text)
    if cnpj_match:
        extracted["cnpj"] = re.sub(r"[^\d]", "", cnpj_match.group())

    # CNAE
    cnae_match = re.search(r"(?:cnae|CNAE)[:\s]*(\d{4}-?\d/?\d{2})", text)
    if cnae_match:
        extracted["cnae_principal"] = cnae_match.group(1)

    # UF (quando explícito)
    uf_match = re.search(r"(?:uf|estado|sediada? (?:em|no|na))\s*[:=]?\s*([A-Z]{2})\b", text, re.I)
    if uf_match:
        uf = uf_match.group(1).upper()
        if len(uf) == 2:
            extracted["uf"] = uf

    # Faturamento
    fat_match = re.search(
        r"(?:faturamento|receita|fatura)[^0-9]*(?:R\$\s*)?([\d.,]+)\s*(?:mil|k|reais|por\s*(?:mês|mes|ano))?",
        text, re.I
    )
    if fat_match:
        valor = fat_match.group(1).replace(".", "").replace(",", ".")
        try:
            valor_f = float(valor)
            # Se parece valor mensal (< 500k), multiplica por 12
            if "ano" not in text_lower and "anual" not in text_lower and valor_f < 500000:
                # Heurística: valores em "mil" ou "k"
                if "mil" in text_lower or "k" in text_lower:
                    valor_f *= 1000
            extracted["faturamento_12m"] = valor_f
        except ValueError:
            pass

    # Tipo de atividade
    atividade_keywords = {
        "software": "software", "tecnologia": "software", "ti ": "software", "saas": "software",
        "comércio": "comercio", "comercio": "comercio", "revenda": "comercio", "loja": "comercio",
        "serviço": "servicos", "servico": "servicos", "consultoria": "servicos",
        "indústria": "industria", "industria": "industria", "fabricação": "industria",
    }
    for keyword, tipo in atividade_keywords.items():
        if keyword in text_lower:
            extracted["tipo_atividade"] = tipo
            break

    # Funcionários
    func_match = re.search(r"(\d+)\s*(?:funcionários|funcionarios|empregados|colaboradores)", text, re.I)
    if func_match:
        extracted["funcionarios"] = int(func_match.group(1))

    return extracted


async def process_message_for_profile(
    db: AsyncSession, client_id: str, user_message: str
) -> dict:
    """Processa uma mensagem do usuário e atualiza o perfil se encontrar dados novos."""
    extracted = extract_profile_from_message(user_message)

    if not extracted:
        return {}

    profile = await get_or_create_profile(db, client_id)

    # Só atualizar campos que ainda não têm valor ou que são mais completos
    updates = {}
    for key, value in extracted.items():
        current = getattr(profile, key, None)
        if current is None or current == 0:
            updates[key] = value

    if updates:
        await update_profile(db, client_id, updates)
        logger.info(f"[MEMORY] Perfil {client_id} atualizado: {list(updates.keys())}")

    return updates


def build_profile_context(profile: ClientProfile) -> str:
    """Constrói bloco de contexto do cliente para injetar no system prompt."""
    if not profile:
        return ""

    parts = []

    if profile.nome:
        parts.append(f"Nome: {profile.nome}")
    if profile.cnpj:
        parts.append(f"CNPJ: {profile.cnpj}")
    if profile.regime_tributario:
        parts.append(f"Regime: {REGIME_DISPLAY.get(profile.regime_tributario, profile.regime_tributario)}")
    if profile.cnae_principal:
        parts.append(f"CNAE: {profile.cnae_principal}")
    if profile.uf:
        parts.append(f"UF: {profile.uf}")
    if profile.municipio:
        parts.append(f"Município: {profile.municipio}")
    if profile.tipo_atividade:
        parts.append(f"Atividade: {profile.tipo_atividade}")
    if profile.faturamento_12m:
        fat = profile.faturamento_12m
        if fat >= 1_000_000:
            parts.append(f"Faturamento 12m: R${fat/1_000_000:.1f}M")
        elif fat >= 1_000:
            parts.append(f"Faturamento 12m: R${fat/1_000:.0f}k")
        else:
            parts.append(f"Faturamento 12m: R${fat:,.2f}")
    if profile.funcionarios:
        parts.append(f"Funcionários: {profile.funcionarios}")
    if profile.folha_pagamento:
        parts.append(f"Folha: R${profile.folha_pagamento:,.2f}")
    if profile.porte:
        parts.append(f"Porte: {profile.porte}")

    if not parts:
        return ""

    return "## Perfil do Cliente (dados já fornecidos — NÃO pergunte novamente)\n" + " · ".join(parts)
