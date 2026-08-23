from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from researchgit.core.db import engine
from researchgit.models import Base
from researchgit.core.config import settings
from researchgit.api.routes import router
rooms:dict[str,dict[WebSocket,str]]={}
@asynccontextmanager
async def lifespan(app):
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql": await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    settings.storage_root.mkdir(parents=True,exist_ok=True); yield
app=FastAPI(title="ResearchGit API",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origins.split(","),allow_methods=["*"],allow_headers=["*"],allow_credentials=True)
app.include_router(router)
@app.websocket("/api/collaboration/{room}")
async def collaboration(ws:WebSocket,room:str):
    await ws.accept();rooms.setdefault(room,{})[ws]="Researcher"
    async def broadcast(payload):
        dead=[]
        for peer in rooms.get(room,{}):
            try: await peer.send_text(payload)
            except: dead.append(peer)
        for peer in dead: rooms.get(room,{}).pop(peer,None)
    async def presence(): await broadcast(__import__('json').dumps({"type":"presence","people":list(rooms.get(room,{}).values())}))
    try:
        while True:
            msg=await ws.receive_text()
            try:
                data=__import__('json').loads(msg)
                if data.get("type")=="presence.join": rooms[room][ws]=str(data.get("name","Researcher")); await presence(); continue
            except: pass
            for peer in list(rooms.get(room,{})):
                if peer != ws: await peer.send_text(msg)
    except WebSocketDisconnect:
        rooms.get(room,{}).pop(ws,None); await presence()
