"""Rotas de autenticação — cadastro, login e usuário atual."""
import logging
import re
import secrets
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_db
from src.core.security import create_token, get_current_user, hash_password, verify_password
from src.models.tables import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterIn(BaseModel):
    name: str = ""
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class GoogleIn(BaseModel):
    credential: str   # ID token (JWT) do Google Identity Services


def _user_out(u: User) -> dict:
    return {"id": str(u.id), "name": u.name, "email": u.email, "is_admin": u.is_admin}


@router.post("/register")
async def register(payload: RegisterIn, db: AsyncSession = Depends(get_db)):
    email = (payload.email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "Email inválido")
    if len(payload.password or "") < 6:
        raise HTTPException(400, "A senha precisa ter ao menos 6 caracteres")

    exists = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "Este email já está cadastrado")

    user = User(
        email=email,
        name=(payload.name or "").strip()[:200] or email.split("@")[0],
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("[AUTH] novo usuário: %s", email)
    return {"token": create_token(user.id), "user": _user_out(user)}


@router.post("/login")
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)):
    email = (payload.email or "").strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user or not verify_password(payload.password or "", user.password_hash):
        raise HTTPException(401, "Email ou senha incorretos")
    if not user.is_active:
        raise HTTPException(403, "Conta desativada")
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    return {"token": create_token(user.id), "user": _user_out(user)}


@router.get("/config")
async def auth_config():
    """Config pública pro frontend (ex: client_id do Google p/ renderizar o botão)."""
    return {"google_client_id": settings.GOOGLE_CLIENT_ID or None}


@router.post("/google")
async def google_login(payload: GoogleIn, db: AsyncSession = Depends(get_db)):
    """Login/cadastro via Google. Verifica o ID token no endpoint oficial do Google."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(400, "Login com Google não está configurado")
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get("https://oauth2.googleapis.com/tokeninfo",
                              params={"id_token": payload.credential})
        info = r.json() if r.status_code == 200 else {}
    except Exception:
        raise HTTPException(503, "Não foi possível validar com o Google")

    if r.status_code != 200:
        raise HTTPException(401, "Token do Google inválido")
    if info.get("aud") != settings.GOOGLE_CLIENT_ID:
        raise HTTPException(401, "Token do Google não é deste aplicativo")
    if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(401, "Emissor do token inválido")
    if str(info.get("email_verified")).lower() != "true":
        raise HTTPException(401, "Email do Google não verificado")
    email = (info.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(401, "Google não retornou um email")

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user:
        user = User(
            email=email,
            name=(info.get("name") or email.split("@")[0])[:200],
            password_hash=hash_password(secrets.token_urlsafe(24)),  # sem senha utilizável
        )
        db.add(user)
        logger.info("[AUTH] novo usuário via Google: %s", email)
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return {"token": create_token(user.id), "user": _user_out(user)}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return _user_out(user)
