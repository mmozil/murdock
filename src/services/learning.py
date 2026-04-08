"""Learning Loop — aprende com conversas boas e indexa no RAG."""
import logging
import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tables import Document, Chunk, Message, Feedback, Conversation
from src.rag.embeddings import generate_embedding

logger = logging.getLogger(__name__)

SOURCE_TYPE_LEARNED = "learned_qa"
MIN_ANSWER_LENGTH = 200  # respostas muito curtas não vale aprender
MAX_ANSWER_LENGTH = 3000  # truncar respostas gigantes


async def learn_from_feedback(db: AsyncSession, message_id: str, rating: int) -> dict:
    """Quando feedback positivo (rating >= 4), embeda o Q+A no RAG."""
    if rating < 4:
        return {"learned": False, "reason": "rating_baixo"}

    # Buscar a mensagem do assistant
    assistant_msg = (await db.execute(
        select(Message).where(Message.id == message_id)
    )).scalar_one_or_none()

    if not assistant_msg or assistant_msg.role != "assistant":
        return {"learned": False, "reason": "mensagem_nao_encontrada"}

    if len(assistant_msg.content) < MIN_ANSWER_LENGTH:
        return {"learned": False, "reason": "resposta_curta"}

    # Buscar a mensagem do user imediatamente antes
    user_msg = (await db.execute(
        select(Message)
        .where(
            Message.conversation_id == assistant_msg.conversation_id,
            Message.role == "user",
            Message.created_at < assistant_msg.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not user_msg:
        return {"learned": False, "reason": "user_msg_nao_encontrada"}

    # Construir o par Q+A para indexação
    qa_text = f"Pergunta: {user_msg.content}\n\nResposta validada: {assistant_msg.content[:MAX_ANSWER_LENGTH]}"
    content_hash = hashlib.sha256(qa_text.encode()).hexdigest()[:16]

    # Verificar se já aprendeu isso
    existing = (await db.execute(
        select(Document).where(Document.content_hash == content_hash)
    )).scalar_one_or_none()

    if existing:
        return {"learned": False, "reason": "ja_aprendido"}

    # Criar documento + chunk
    doc = Document(
        source_id=f"learned_{str(uuid.uuid4())[:8]}",
        title=f"Q&A: {user_msg.content[:100]}",
        url=f"conversation:{assistant_msg.conversation_id}",
        source_type=SOURCE_TYPE_LEARNED,
        orgao="Murdock AI",
        fundamentacao="Resposta validada por feedback positivo do usuário",
        content_hash=content_hash,
        raw_size=len(qa_text),
    )
    db.add(doc)
    await db.flush()

    embedding = generate_embedding(qa_text)
    if not embedding:
        return {"learned": False, "reason": "embedding_falhou"}

    chunk = Chunk(
        document_id=doc.id,
        content=qa_text,
        embedding=embedding,
        chunk_index=0,
        section="Q&A validado",
        metadata_={
            "conversation_id": str(assistant_msg.conversation_id),
            "message_id": str(message_id),
            "rating": rating,
            "user_question": user_msg.content[:200],
        },
    )
    db.add(chunk)

    # Atualizar tsvector
    doc.total_chunks = 1
    await db.flush()

    # Marcar feedback como processado
    await db.execute(
        update(Feedback)
        .where(Feedback.message_id == message_id)
        .values(learned=True)
    )

    await db.commit()

    logger.info(f"[LEARN] Aprendido Q&A de conversa {assistant_msg.conversation_id}")
    return {"learned": True, "document_id": str(doc.id), "question": user_msg.content[:100]}


async def learn_from_engaged_conversation(db: AsyncSession, conversation_id: str) -> dict:
    """Aprende de conversas longas e engajadas (6+ mensagens) mesmo sem feedback explícito."""
    msgs = (await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )).scalars().all()

    if len(msgs) < 6:
        return {"learned": False, "reason": "conversa_curta"}

    # Pegar os pares Q+A mais substanciais
    learned_count = 0
    for i in range(len(msgs) - 1):
        if msgs[i].role == "user" and msgs[i + 1].role == "assistant":
            answer = msgs[i + 1].content
            if len(answer) >= MIN_ANSWER_LENGTH:
                qa_text = f"Pergunta: {msgs[i].content}\n\nResposta: {answer[:MAX_ANSWER_LENGTH]}"
                content_hash = hashlib.sha256(qa_text.encode()).hexdigest()[:16]

                # Verificar duplicata
                existing = (await db.execute(
                    select(Document).where(Document.content_hash == content_hash)
                )).scalar_one_or_none()

                if existing:
                    continue

                embedding = generate_embedding(qa_text)
                if not embedding:
                    continue

                doc = Document(
                    source_id=f"learned_{str(uuid.uuid4())[:8]}",
                    title=f"Q&A: {msgs[i].content[:100]}",
                    url=f"conversation:{conversation_id}",
                    source_type=SOURCE_TYPE_LEARNED,
                    orgao="Murdock AI",
                    fundamentacao="Extraído de conversa engajada",
                    content_hash=content_hash,
                    raw_size=len(qa_text),
                    total_chunks=1,
                )
                db.add(doc)
                await db.flush()

                chunk = Chunk(
                    document_id=doc.id,
                    content=qa_text,
                    embedding=embedding,
                    chunk_index=0,
                    section="Q&A engajado",
                    metadata_={
                        "conversation_id": str(conversation_id),
                        "user_question": msgs[i].content[:200],
                    },
                )
                db.add(chunk)
                learned_count += 1

    if learned_count > 0:
        await db.commit()
        logger.info(f"[LEARN] {learned_count} Q&As de conversa engajada {conversation_id}")

    return {"learned": learned_count > 0, "count": learned_count}


async def get_learning_stats(db: AsyncSession) -> dict:
    """Estatísticas do learning loop."""
    from sqlalchemy import func, text as sql_text

    total_learned = (await db.execute(
        select(func.count(Document.id)).where(Document.source_type == SOURCE_TYPE_LEARNED)
    )).scalar() or 0

    total_chunks = (await db.execute(
        select(func.count(Chunk.id))
        .join(Document)
        .where(Document.source_type == SOURCE_TYPE_LEARNED)
    )).scalar() or 0

    total_feedback_positive = (await db.execute(
        select(func.count(Feedback.id)).where(Feedback.rating >= 4)
    )).scalar() or 0

    return {
        "total_learned_docs": total_learned,
        "total_learned_chunks": total_chunks,
        "total_positive_feedback": total_feedback_positive,
    }
