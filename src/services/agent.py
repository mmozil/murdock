"""Agente Matt Murdock — especialista tributário brasileiro com Pydantic AI."""
import logging
import time
import uuid
from typing import Optional

from pydantic_ai import Agent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.tables import Conversation, Message
from src.tools.tools import (
    MurdockDeps,
    search_law,
    calculate_tax,
    check_ncm,
    reform_2026,
    credit_recovery,
    calendar,
    jurisprudence,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# System Prompt — Matt Murdock, Tributarista Brasileiro
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Você é **Matt Murdock**, um especialista tributário, contábil e fiscal brasileiro de altíssimo nível técnico. Seu nome é uma referência ao advogado Matt Murdock (Daredevil) — assim como ele, você tem uma percepção sobre-humana para detectar inconsistências, riscos ocultos e oportunidades que passam despercebidas.

## Missão

1. **Orientar com precisão técnica** — toda resposta deve ter fundamento legal, normativo ou regulamentar. Nunca responda "por alto".
2. **Proteger o contribuinte** — identificar riscos fiscais, erros de enquadramento e obrigações negligenciadas ANTES que virem auto de infração.
3. **Otimizar a carga tributária dentro da lei** — elisão fiscal é dever profissional. Evasão é crime. A linha deve estar sempre clara.
4. **Tornar o complexo executável** — traduzir complexidade tributária brasileira em decisão prática, sem perder rigor.
5. **Manter-se atualizado** — usar a knowledge base de fontes oficiais gov.br para fundamentar respostas.

## Ferramentas Disponíveis

Você tem acesso a 7 ferramentas especializadas. USE-AS SEMPRE que a pergunta exigir:

- **search_law**: Busca legislação na knowledge base (leis, decretos, INs, resoluções)
- **calculate_tax**: Cálculo tributário (Simples Nacional, Lucro Presumido, Lucro Real)
- **check_ncm**: Consulta NCM e classificação fiscal
- **reform_2026**: Reforma Tributária CBS/IBS (cronograma 2026-2033)
- **credit_recovery**: Recuperação de créditos tributários
- **calendar**: Calendário de obrigações fiscais e prazos
- **jurisprudence**: Jurisprudência STF/STJ em matéria tributária

## Regras de Conduta

### NUNCA responda tributário no escuro
Antes de responder sobre tributação, você PRECISA saber:
- Regime tributário (Simples, LP, LR, MEI)
- CNAE principal e secundários
- UF de origem e destino
- Tipo de operação (venda, serviço, revenda, industrialização, importação)
- NCM/NBS quando aplicável
- Faturamento dos últimos 12 meses

Se faltarem 3+ dessas informações e a resposta depender delas, **pergunte antes**.

### SEMPRE separar esferas
- **Federal**: IRPJ, CSLL, PIS, Cofins, IPI, IRRF
- **Estadual**: ICMS (próprio, ST, DIFAL), ITCMD
- **Municipal**: ISS, ITBI
Nunca diga "paga X% de imposto" sem especificar tributo, base de cálculo, alíquota e esfera.

### Hierarquia de Fontes
1. CF/88 → 2. CTN → 3. Leis Complementares (LC 87, 116, 123, 214) → 4. Leis Ordinárias → 5. Decretos → 6. INs RFB → 7. Soluções COSIT → 8. Convênios CONFAZ → 9. Resoluções CGSN

### Simplificações PROIBIDAS
- "MEI paga só DAS fixo" — errado com ICMS-ST e DIFAL
- "Simples é sempre mais barato" — depende de faturamento, atividade, fator R
- "ICMS é 18%" — depende de UF, NCM, operação, benefício, ST
- "PIS/Cofins é 3,65%" — errado no não-cumulativo (1,65% + 7,6%)
- "DIFAL é pago por todo mundo" — Simples é ISENTO (STF ADI 5464)

## Formato de Resposta

- Responda em **português brasileiro** (pt-BR)
- Use Markdown para formatação
- Cite a fonte legal específica (ex: "Art. 13, LC 123/2006")
- Quando usar ferramentas, integre os resultados naturalmente na resposta
- Para cálculos, mostre o passo-a-passo com a fórmula
- Para comparativos de regime, use tabelas Markdown
- Sempre inclua seção "Fontes" no final com links oficiais

## Valores de Referência 2026

- Salário mínimo: R$1.518,00
- Teto INSS: R$8.475,55
- Limite MEI: R$81.000/ano
- Limite Simples Nacional: R$4.800.000/ano
- Sublimite ICMS/ISS: R$3.600.000 (UFs que adotam)
- IRPF: isenção até R$5.000/mês (Lei 15.270/2025)
- Dividendos: isentos até R$50.000/mês, 10% acima (Lei 15.270/2025)
- CBS teste: 0,9% | IBS teste: 0,1% (2026, LC 214/2025)

## Personalidade

Você é direto, preciso e confiante — como um advogado tributarista sênior em consulta particular. Não enrole. Quando não souber, diga claramente e indique onde buscar. Quando identificar risco fiscal, alerte imediatamente. Quando encontrar oportunidade de economia tributária lícita, destaque com entusiasmo técnico.
"""

# ═══════════════════════════════════════════════════════════════════════════
# Agente Pydantic AI
# ═══════════════════════════════════════════════════════════════════════════

murdock_agent = Agent(
    f"google-gla:{settings.PRIMARY_MODEL}",
    deps_type=MurdockDeps,
    system_prompt=SYSTEM_PROMPT,
    tools=[
        search_law,
        calculate_tax,
        check_ncm,
        reform_2026,
        credit_recovery,
        calendar,
        jurisprudence,
    ],
    retries=2,
)


# ═══════════════════════════════════════════════════════════════════════════
# Serviço de Conversa
# ═══════════════════════════════════════════════════════════════════════════

async def get_or_create_conversation(
    db: AsyncSession, conversation_id: Optional[str] = None
) -> Conversation:
    """Obtém ou cria uma conversa."""
    if conversation_id:
        conv = (await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )).scalar_one_or_none()
        if conv:
            return conv

    conv = Conversation(title="Nova consulta tributária")
    db.add(conv)
    await db.flush()
    return conv


async def load_history(db: AsyncSession, conversation_id: str) -> list[dict]:
    """Carrega histórico de mensagens para contexto."""
    msgs = (await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )).scalars().all()

    return [{"role": m.role, "content": m.content} for m in msgs]


async def save_message(
    db: AsyncSession,
    conversation_id: str,
    role: str,
    content: str,
    sources_used: list = None,
    tools_called: list = None,
    model_used: str = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
) -> Message:
    """Salva mensagem no banco."""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        sources_used=sources_used,
        tools_called=tools_called,
        model_used=model_used,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
    )
    db.add(msg)
    return msg


async def chat(
    db: AsyncSession,
    user_message: str,
    conversation_id: Optional[str] = None,
) -> dict:
    """Processa mensagem e retorna resposta completa (sem streaming)."""
    start = time.time()

    # Conversa
    conv = await get_or_create_conversation(db, conversation_id)

    # Salvar mensagem do usuário
    await save_message(db, str(conv.id), "user", user_message)

    # Carregar histórico
    history = await load_history(db, str(conv.id))

    # Construir contexto com histórico
    context_parts = []
    for msg in history[-10:]:  # Últimas 10 mensagens
        if msg["role"] == "user":
            context_parts.append(f"Usuário: {msg['content']}")
        elif msg["role"] == "assistant":
            context_parts.append(f"Murdock: {msg['content']}")

    # Rodar agente
    deps = MurdockDeps(db=db)
    model = f"google-gla:{settings.PRIMARY_MODEL}"
    fallback_model = f"anthropic:{settings.FALLBACK_MODEL}"

    try:
        result = await murdock_agent.run(user_message, deps=deps)
        model_used = model
    except Exception as e:
        logger.warning(f"Gemini falhou ({e}), tentando fallback Claude...")
        try:
            result = await murdock_agent.run(
                user_message, deps=deps, model=fallback_model
            )
            model_used = fallback_model
        except Exception as e2:
            logger.error(f"Fallback também falhou: {e2}")
            raise

    response_text = result.output
    latency = int((time.time() - start) * 1000)

    # Salvar resposta
    await save_message(
        db, str(conv.id), "assistant", response_text,
        model_used=model_used,
        latency_ms=latency,
    )

    # Atualizar conversa
    conv.total_messages = (conv.total_messages or 0) + 2
    conv.model_used = model_used

    # Título automático na primeira interação
    if conv.total_messages <= 2:
        conv.title = user_message[:100]

    await db.commit()

    return {
        "conversation_id": str(conv.id),
        "response": response_text,
        "model": model_used,
        "latency_ms": latency,
    }


async def chat_stream(
    db: AsyncSession,
    user_message: str,
    conversation_id: Optional[str] = None,
):
    """Processa mensagem com streaming SSE (yield de chunks)."""
    start = time.time()

    conv = await get_or_create_conversation(db, conversation_id)
    await save_message(db, str(conv.id), "user", user_message)

    deps = MurdockDeps(db=db)
    model = f"google-gla:{settings.PRIMARY_MODEL}"
    fallback_model = f"anthropic:{settings.FALLBACK_MODEL}"

    full_response = []
    model_used = model

    try:
        async with murdock_agent.run_stream(user_message, deps=deps) as result:
            async for chunk in result.stream_text(delta=True):
                full_response.append(chunk)
                yield {"event": "token", "data": chunk}
    except Exception as e:
        logger.warning(f"Gemini stream falhou ({e}), tentando fallback...")
        model_used = fallback_model
        full_response = []
        try:
            async with murdock_agent.run_stream(
                user_message, deps=deps, model=fallback_model
            ) as result:
                async for chunk in result.stream_text(delta=True):
                    full_response.append(chunk)
                    yield {"event": "token", "data": chunk}
        except Exception as e2:
            logger.error(f"Fallback stream falhou: {e2}")
            yield {"event": "error", "data": f"Erro: {e2}"}
            return

    response_text = "".join(full_response)
    latency = int((time.time() - start) * 1000)

    # Salvar resposta
    await save_message(
        db, str(conv.id), "assistant", response_text,
        model_used=model_used,
        latency_ms=latency,
    )

    conv.total_messages = (conv.total_messages or 0) + 2
    conv.model_used = model_used
    if (conv.total_messages or 0) <= 2:
        conv.title = user_message[:100]

    await db.commit()

    yield {
        "event": "done",
        "data": f'{{"conversation_id": "{conv.id}", "model": "{model_used}", "latency_ms": {latency}}}',
    }
