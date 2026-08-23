"""Small, server-side session and workspace authorization helpers."""
import hashlib
import secrets
from contextvars import ContextVar
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from researchgit.core.db import get_session
from researchgit.models import User, UserSession, WorkspaceMember

SESSION_COOKIE = "researchgit_session"
SESSION_DAYS = 14
ROLE_RANK = {"VIEWER": 1, "EDITOR": 2, "OWNER": 3}
active_user: ContextVar[User | None] = ContextVar("active_user", default=None)

def utcnow() -> datetime:
    # The existing schema stores UTC values using datetime.utcnow(), including
    # SQLite development databases which return naive datetime objects.
    return datetime.utcnow()

def hash_password(password: str) -> str:
    if len(password) < 10: raise ValueError("Password must contain at least 10 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"

def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded: return False
    try:
        _, n, r, p, salt, expected = encoded.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
        return secrets.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError): return False

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

async def create_session(session: AsyncSession, user_id) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    record = UserSession(user_id=user_id, token_hash=token_hash(token), expires_at=utcnow() + timedelta(days=SESSION_DAYS))
    session.add(record); await session.flush()
    return token, record

async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer "): token = authorization[7:]
    if not token: raise HTTPException(401, detail={"error": {"code": "AUTH_REQUIRED", "message": "Sign in to continue."}})
    statement = select(User).join(UserSession).where(UserSession.token_hash == token_hash(token), UserSession.revoked_at.is_(None), UserSession.expires_at > utcnow())
    user = (await session.execute(statement)).scalar_one_or_none()
    if not user: raise HTTPException(401, detail={"error": {"code": "SESSION_EXPIRED", "message": "Your session has expired. Please sign in again."}})
    active_user.set(user)
    return user

async def require_workspace_member(session: AsyncSession, workspace_id, user_id: object) -> WorkspaceMember:
    member = (await session.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id))).scalar_one_or_none()
    if not member: raise HTTPException(403, detail={"error": {"code": "WORKSPACE_ACCESS_DENIED", "message": "You are not a member of this workspace."}})
    return member

async def require_workspace_role(session: AsyncSession, workspace_id, user_id: object, minimum: str) -> WorkspaceMember:
    member = await require_workspace_member(session, workspace_id, user_id)
    if ROLE_RANK.get(member.role.upper(), 0) < ROLE_RANK[minimum]:
        raise HTTPException(403, detail={"error": {"code": "INSUFFICIENT_ROLE", "message": f"{minimum.title()} access is required."}})
    return member
