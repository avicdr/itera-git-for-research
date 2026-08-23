from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy import text, select
from fastapi.middleware.cors import CORSMiddleware
from researchgit.core.db import engine, SessionLocal
from researchgit.models import Base, User, UserSession, Artifact, WorkspaceMember
from researchgit.core.config import settings
from researchgit.api.routes import auth_router, public_router, router
from researchgit.core.auth import SESSION_COOKIE, token_hash, utcnow
rooms:dict[str,dict[WebSocket,str]]={}
@asynccontextmanager
async def lifespan(app):
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql": await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    settings.storage_root.mkdir(parents=True,exist_ok=True); yield
app=FastAPI(title="ResearchGit API",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origins.split(","),allow_methods=["*"],allow_headers=["*"],allow_credentials=True)
app.include_router(auth_router)
app.include_router(public_router)
app.include_router(router)
@app.websocket("/api/collaboration/{room}")
async def collaboration(ws:WebSocket,room:str):
    token=ws.cookies.get(SESSION_COOKIE)
    if not token:
        await ws.close(code=4401); return
    async with SessionLocal() as session:
        person=(await session.execute(select(User).join(UserSession).where(UserSession.token_hash==token_hash(token),UserSession.revoked_at.is_(None),UserSession.expires_at>utcnow()))).scalar_one_or_none()
        if not person:
            await ws.close(code=4401); return
        if room.startswith("document-"):
            try: artifact=await session.get(Artifact,room.removeprefix("document-"))
            except ValueError: artifact=None
            member = (await session.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id==artifact.workspace_id,WorkspaceMember.user_id==person.id))).scalar_one_or_none() if artifact else None
            if not artifact or not member:
                await ws.close(code=4403); return
    await ws.accept();rooms.setdefault(room,{})[ws]=person.name
    async def broadcast(payload):
        dead=[]
        for peer in rooms.get(room,{}):
            try:
                if isinstance(payload, bytes): await peer.send_bytes(payload)
                else: await peer.send_text(payload)
            except: dead.append(peer)
        for peer in dead: rooms.get(room,{}).pop(peer,None)
    async def presence(): await broadcast(__import__('json').dumps({"type":"presence","people":list(rooms.get(room,{}).values())}))
    try:
        while True:
            incoming=await ws.receive()
            if incoming.get("type")=="websocket.disconnect": break
            msg=incoming.get("text") if incoming.get("text") is not None else incoming.get("bytes")
            if msg is None: continue
            try:
                data=__import__('json').loads(msg) if isinstance(msg,str) else {}
                if data.get("type")=="presence.join": rooms[room][ws]=str(data.get("name","Researcher")); await presence(); continue
            except: pass
            for peer in list(rooms.get(room,{})):
                if peer != ws: await peer.send_text(msg)
    except WebSocketDisconnect:
        rooms.get(room,{}).pop(ws,None); await presence()
