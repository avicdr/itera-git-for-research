import hashlib, json, re, uuid
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from researchgit.core.db import get_session
from researchgit.core.config import settings
from researchgit.models import *
from researchgit.ingestion.processing import process
from researchgit.versioning.commits import branch_state, create_commit
from researchgit.versioning.diff import structural_diff
from researchgit.versioning.merge import plan_merge
from researchgit.rag.query_service import answer

router=APIRouter(prefix="/api")
def err(code,msg,status=400): raise HTTPException(status,detail={"error":{"code":code,"message":msg}})
async def user(session):
    u=(await session.execute(select(User).limit(1))).scalar_one_or_none()
    if not u: u=User(name="Demo Researcher",email="demo@researchgit.local"); session.add(u); await session.flush()
    return u
async def workspace_or_404(session,id):
    w=await session.get(Workspace,id)
    if not w: err("WORKSPACE_NOT_FOUND","Workspace not found",404)
    return w
class WorkspaceIn(BaseModel): name:str; description:str|None=None
class BranchIn(BaseModel): name:str; source_branch_id:uuid.UUID|None=None
class CommitIn(BaseModel): message:str; artifact_version_ids:dict[uuid.UUID,uuid.UUID]|None=None
class DocIn(BaseModel): text:str; editor_json:dict|None=None
class MergeIn(BaseModel): source_branch_id:uuid.UUID; target_branch_id:uuid.UUID
class ResolveIn(BaseModel): resolution:str; text:str|None=None
class ChatIn(BaseModel): title:str; branch_id:uuid.UUID|None=None
class QueryIn(BaseModel): message:str; branch_id:uuid.UUID; context:dict=Field(default_factory=dict); commit_id:uuid.UUID|None=None

@router.post("/workspaces")
async def create_workspace(data:WorkspaceIn, session:AsyncSession=Depends(get_session)):
    u=await user(session); w=Workspace(**data.model_dump(),created_by=u.id); session.add(w); await session.flush(); session.add(WorkspaceMember(workspace_id=w.id,user_id=u.id)); session.add(Branch(workspace_id=w.id,name="main",created_by=u.id,is_protected=True)); await session.commit(); return {"id":w.id,"name":w.name,"description":w.description}
@router.get("/workspaces")
async def list_workspaces(session:AsyncSession=Depends(get_session)):
    rows=(await session.execute(select(Workspace).where(Workspace.archived==False).order_by(desc(Workspace.updated_at)))).scalars(); return [{"id":x.id,"name":x.name,"description":x.description,"updated_at":x.updated_at} for x in rows]
@router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    w=await workspace_or_404(session,workspace_id); branches=(await session.execute(select(Branch).where(Branch.workspace_id==w.id))).scalars().all(); return {"id":w.id,"name":w.name,"description":w.description,"branches":[{"id":b.id,"name":b.name,"head_commit_id":b.head_commit_id} for b in branches]}
@router.patch("/workspaces/{workspace_id}")
async def patch_workspace(workspace_id:uuid.UUID,data:WorkspaceIn,session:AsyncSession=Depends(get_session)):
    w=await workspace_or_404(session,workspace_id); w.name=data.name;w.description=data.description;await session.commit();return {"id":w.id,"name":w.name}
@router.post("/workspaces/{workspace_id}/artifacts")
async def upload(workspace_id:uuid.UUID,file:UploadFile=File(...),scope:str=Form("WORKSPACE"),chat_id:uuid.UUID|None=Form(None),session:AsyncSession=Depends(get_session)):
    w=await workspace_or_404(session,workspace_id); u=await user(session); suffix=Path(file.filename or "").suffix.lower(); allowed={".md":"DOCUMENT",".txt":"DOCUMENT",".pdf":"PDF",".json":"CHAT_EXPORT"}
    if suffix not in allowed: err("UNSUPPORTED_FILE","Supported: .md, .txt, .pdf, .json",415)
    content=await file.read()
    if len(content)>settings.max_upload_bytes: err("FILE_TOO_LARGE","Upload exceeds configured limit",413)
    safe=re.sub(r"[^A-Za-z0-9._-]","_",Path(file.filename or "artifact").name); a=Artifact(workspace_id=w.id,name=Path(safe).stem,original_filename=safe,artifact_type=allowed[suffix],mime_type=file.content_type or ("application/pdf" if suffix==".pdf" else "text/plain"),scope=scope,chat_id=chat_id,created_by=u.id,status="PROCESSING");session.add(a);await session.flush()
    rel=Path("workspaces")/str(w.id)/"artifacts"/str(a.id)/"versions"/"v1"/safe; target=settings.storage_root/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content);v=ArtifactVersion(artifact_id=a.id,version_number=1,storage_path=str(rel),content_hash=hashlib.sha256(content).hexdigest(),created_by=u.id);session.add(v);await session.flush(); await process(session,a,v,settings.storage_root);session.add(ActivityEvent(workspace_id=w.id,actor_id=u.id,event_type="file_imported",payload={"artifact_id":str(a.id)}));await session.commit();return {"id":a.id,"status":a.status,"version_id":v.id}
@router.get("/workspaces/{workspace_id}/artifacts")
async def artifacts(workspace_id:uuid.UUID,branch_id:uuid.UUID|None=None,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); q=select(Artifact).where(Artifact.workspace_id==workspace_id,Artifact.deleted_at==None); rows=(await session.execute(q)).scalars().all(); visible={}
    if branch_id: visible=await branch_state(session,(await session.get(Branch,branch_id)).head_commit_id)
    return [{"id":a.id,"name":a.name,"type":a.artifact_type,"status":a.status,"scope":a.scope,"version_id":visible.get(a.id)} for a in rows if not visible or a.id in visible]
@router.get("/workspaces/{workspace_id}/working-changes")
async def working_changes(workspace_id:uuid.UUID,branch_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); branch=await session.get(Branch,branch_id)
    if not branch or branch.workspace_id!=workspace_id: err("BRANCH_NOT_FOUND","Branch not found",404)
    head=await branch_state(session,branch.head_commit_id); results=[]
    artifacts=(await session.execute(select(Artifact).where(Artifact.workspace_id==workspace_id,Artifact.deleted_at==None))).scalars().all()
    for artifact in artifacts:
        latest=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id==artifact.id).order_by(desc(ArtifactVersion.version_number)))).scalars().first()
        previous=head.get(artifact.id)
        if previous != latest.id:
            old=await session.get(ArtifactVersion,previous) if previous else None
            results.append({"artifact_id":artifact.id,"name":artifact.name,"kind":"A" if not previous else "M","latest_version_id":latest.id,"diff":structural_diff(old.canonical_text if old else "",latest.canonical_text)})
    return {"branch_id":branch.id,"changes":results}
@router.get("/artifacts/{artifact_id}")
async def artifact(artifact_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    a=await session.get(Artifact,artifact_id)
    if not a:err("ARTIFACT_NOT_FOUND","Artifact not found",404)
    v=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id==a.id).order_by(desc(ArtifactVersion.version_number)))).scalars().first();return {"id":a.id,"workspace_id":a.workspace_id,"name":a.name,"type":a.artifact_type,"status":a.status,"version": {"id":v.id,"text":v.canonical_text,"editor_json":v.editor_json,"number":v.version_number}}
@router.post("/workspaces/{workspace_id}/documents")
async def create_document(workspace_id:uuid.UUID,data:DocIn, name:str="untitled.md",session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id);u=await user(session);safe=re.sub(r"[^A-Za-z0-9._-]","_",Path(name).name)
    if not safe.endswith((".md",".txt")): safe += ".md"
    a=Artifact(workspace_id=workspace_id,name=Path(safe).stem,original_filename=safe,artifact_type="DOCUMENT",mime_type="text/markdown",created_by=u.id,status="PROCESSING");session.add(a);await session.flush()
    rel=Path("workspaces")/str(workspace_id)/"artifacts"/str(a.id)/"versions"/"v1"/safe;p=settings.storage_root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data.text)
    v=ArtifactVersion(artifact_id=a.id,version_number=1,storage_path=str(rel),content_hash=hashlib.sha256(data.text.encode()).hexdigest(),editor_json=data.editor_json,created_by=u.id);session.add(v);await session.flush();await process(session,a,v,settings.storage_root);await session.commit();return {"id":a.id,"version_id":v.id}
@router.get("/artifacts/{artifact_id}/file")
async def artifact_file(artifact_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    a=await session.get(Artifact,artifact_id);v=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id==artifact_id).order_by(desc(ArtifactVersion.version_number)))).scalars().first()
    if not a or not v:err("ARTIFACT_NOT_FOUND","Artifact not found",404)
    p=(settings.storage_root/v.storage_path).resolve()
    if settings.storage_root.resolve() not in p.parents or not p.is_file():err("FILE_NOT_FOUND","Stored file unavailable",404)
    return FileResponse(p,filename=a.original_filename,media_type=a.mime_type)
@router.put("/artifacts/{artifact_id}/document")
async def save_doc(artifact_id:uuid.UUID,data:DocIn,session:AsyncSession=Depends(get_session)):
    a=await session.get(Artifact,artifact_id)
    if not a or a.artifact_type!="DOCUMENT":err("INVALID_ARTIFACT","Editable document not found",404)
    u=await user(session); last=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id==a.id).order_by(desc(ArtifactVersion.version_number)))).scalars().first();n=last.version_number+1; rel=Path("workspaces")/str(a.workspace_id)/"artifacts"/str(a.id)/"versions"/f"v{n}"/a.original_filename;p=settings.storage_root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data.text);v=ArtifactVersion(artifact_id=a.id,version_number=n,storage_path=str(rel),content_hash=hashlib.sha256(data.text.encode()).hexdigest(),canonical_text=data.text,editor_json=data.editor_json,created_by=u.id);session.add(v);await process(session,a,v,settings.storage_root);await session.commit();return {"version_id":v.id,"number":n}
@router.post("/workspaces/{workspace_id}/commits")
async def commit(workspace_id:uuid.UUID,data:CommitIn,branch_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); b=await session.get(Branch,branch_id);u=await user(session)
    if not b or b.workspace_id!=workspace_id:err("BRANCH_NOT_FOUND","Branch not found",404)
    state=await branch_state(session,b.head_commit_id)
    if data.artifact_version_ids: state.update(data.artifact_version_ids)
    else:
        arts=(await session.execute(select(Artifact.id).where(Artifact.workspace_id==workspace_id,Artifact.deleted_at==None))).scalars()
        for aid in arts:
            v=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id==aid).order_by(desc(ArtifactVersion.version_number)))).scalars().first(); state[aid]=v.id
    c=await create_commit(session,workspace_id,b,u.id,data.message,state);session.add(ActivityEvent(workspace_id=workspace_id,actor_id=u.id,event_type="commit_created",payload={"commit_id":str(c.id)}));await session.commit();return {"id":c.id,"short_hash":c.short_hash}
@router.get("/workspaces/{workspace_id}/commits")
async def commits(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    rows=(await session.execute(select(Commit).where(Commit.workspace_id==workspace_id).order_by(desc(Commit.created_at)))).scalars();return [{"id":c.id,"message":c.message,"short_hash":c.short_hash,"created_at":c.created_at,"author_id":c.author_id} for c in rows]
@router.get("/commits/{commit_id}")
async def commit_detail(commit_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    c=await session.get(Commit,commit_id)
    if not c:err("COMMIT_NOT_FOUND","Commit not found",404)
    parents=list((await session.execute(select(CommitParent.parent_id).where(CommitParent.commit_id==c.id))).scalars());state=await branch_state(session,c.id);return {"id":c.id,"message":c.message,"parents":parents,"state":state,"created_at":c.created_at}
@router.post("/workspaces/{workspace_id}/branches")
async def create_branch(workspace_id:uuid.UUID,data:BranchIn,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id);u=await user(session); source=await session.get(Branch,data.source_branch_id) if data.source_branch_id else (await session.execute(select(Branch).where(Branch.workspace_id==workspace_id,Branch.name=="main"))).scalar_one()
    if not source or source.workspace_id!=workspace_id:err("BRANCH_NOT_FOUND","Source branch not found",404)
    b=Branch(workspace_id=workspace_id,name=data.name,head_commit_id=source.head_commit_id,created_by=u.id);session.add(b);session.add(ActivityEvent(workspace_id=workspace_id,actor_id=u.id,event_type="branch_created",payload={"branch":data.name}));await session.commit();return {"id":b.id,"name":b.name,"head_commit_id":b.head_commit_id}
@router.get("/workspaces/{workspace_id}/branches")
async def branches(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    rows=(await session.execute(select(Branch).where(Branch.workspace_id==workspace_id))).scalars();return [{"id":b.id,"name":b.name,"head_commit_id":b.head_commit_id,"protected":b.is_protected} for b in rows]
@router.get("/workspaces/{workspace_id}/compare")
async def compare(workspace_id:uuid.UUID,source_branch_id:uuid.UUID,target_branch_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    s=await session.get(Branch,source_branch_id);t=await session.get(Branch,target_branch_id)
    if not s or not t:err("BRANCH_NOT_FOUND","Branch not found",404)
    ss,ts=await branch_state(session,s.head_commit_id),await branch_state(session,t.head_commit_id); changes=[]
    for aid in set(ss)|set(ts):
        if ss.get(aid)!=ts.get(aid):
            vs=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.id.in_([x for x in [ss.get(aid),ts.get(aid)] if x])))).scalars().all(); texts={v.id:v.canonical_text for v in vs};changes.append({"artifact_id":aid,"kind":"ADDED" if aid not in ts else "REMOVED" if aid not in ss else "MODIFIED","diff":structural_diff(texts.get(ts.get(aid),""),texts.get(ss.get(aid),""))})
    return {"source":s.name,"target":t.name,"changes":changes}
@router.post("/workspaces/{workspace_id}/merge")
async def merge(workspace_id:uuid.UUID,data:MergeIn,session:AsyncSession=Depends(get_session)):
    u=await user(session);s=await session.get(Branch,data.source_branch_id);t=await session.get(Branch,data.target_branch_id)
    if not s or not t or s.workspace_id!=workspace_id or t.workspace_id!=workspace_id:err("BRANCH_NOT_FOUND","Branch not found",404)
    result,conflicts,_=await plan_merge(session,t,s);m=Merge(workspace_id=workspace_id,source_branch_id=s.id,target_branch_id=t.id,created_by=u.id);session.add(m);await session.flush()
    for x in conflicts: session.add(MergeConflict(merge_id=m.id,artifact_id=x["artifact_id"],base_text=x["base"],target_text=x["target"],source_text=x["source"]))
    if conflicts: m.status="CONFLICT";await session.commit();return {"merge_id":m.id,"status":"CONFLICT","conflicts":len(conflicts)}
    c=await create_commit(session,workspace_id,t,u.id,f"Merge {s.name} into {t.name}",result,s.head_commit_id);m.status="COMPLETED";m.merge_commit_id=c.id;await session.commit();return {"merge_id":m.id,"status":"COMPLETED","commit_id":c.id}
@router.post("/merge-conflicts/{conflict_id}/resolve")
async def resolve(conflict_id:uuid.UUID,data:ResolveIn,session:AsyncSession=Depends(get_session)):
    c=await session.get(MergeConflict,conflict_id)
    if not c:err("CONFLICT_NOT_FOUND","Conflict not found",404)
    c.resolved_text=data.target_text if data.resolution=="TARGET" else c.source_text if data.resolution=="SOURCE" else data.text
    if not c.resolved_text:err("INVALID_RESOLUTION","Manual resolution requires text")
    c.resolved_at=datetime.utcnow();await session.commit();return {"id":c.id,"resolved":True}
@router.post("/workspaces/{workspace_id}/chats")
async def create_chat(workspace_id:uuid.UUID,data:ChatIn,session:AsyncSession=Depends(get_session)):
    u=await user(session);b=await session.get(Branch,data.branch_id) if data.branch_id else (await session.execute(select(Branch).where(Branch.workspace_id==workspace_id,Branch.name=="main"))).scalar_one();c=ResearchChat(workspace_id=workspace_id,title=data.title,created_by=u.id,active_branch_id=b.id);session.add(c);await session.commit();return {"id":c.id,"title":c.title,"branch_id":b.id}
@router.get("/workspaces/{workspace_id}/chats")
async def chats(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    rows=(await session.execute(select(ResearchChat).where(ResearchChat.workspace_id==workspace_id))).scalars();return [{"id":c.id,"title":c.title,"branch_id":c.active_branch_id} for c in rows]
@router.post("/workspaces/{workspace_id}/chats/{chat_id}/query")
async def query(workspace_id:uuid.UUID,chat_id:uuid.UUID,data:QueryIn,session:AsyncSession=Depends(get_session)):
    chat=await session.get(ResearchChat,chat_id)
    if not chat or chat.workspace_id!=workspace_id:err("CHAT_NOT_FOUND","Research chat not found",404)
    session.add(ChatMessage(chat_id=chat_id,role="user",content=data.message)); text,cites=await answer(session,workspace_id,chat_id,data.branch_id,data.message,data.context);session.add(ChatMessage(chat_id=chat_id,role="assistant",content=text,citations=cites));await session.commit()
    async def events():
        yield "event: citations\ndata: "+json.dumps(cites)+"\n\n"
        for piece in text.split(" "): yield "event: token\ndata: "+json.dumps(piece+" ")+"\n\n"
        yield "event: done\ndata: {}\n\n"
    return StreamingResponse(events(),media_type="text/event-stream")
@router.get("/workspaces/{workspace_id}/search")
async def global_search(workspace_id:uuid.UUID,q:str,branch_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    b=await session.get(Branch,branch_id);rows=await answer # re-use retrieval directly
    from researchgit.retrieval.hybrid_search import search
    found=await search(session,workspace_id,list((await branch_state(session,b.head_commit_id)).values()),q)
    return [{"artifact_id":str(a.id),"artifact":a.name,"text":c.content[:300],"page":c.page_number,"version_id":str(c.artifact_version_id)} for _,c,a in found]
@router.get("/workspaces/{workspace_id}/activity")
async def activity(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    rows=(await session.execute(select(ActivityEvent).where(ActivityEvent.workspace_id==workspace_id).order_by(desc(ActivityEvent.created_at)))).scalars();return [{"type":x.event_type,"payload":x.payload,"created_at":x.created_at} for x in rows]
@router.post("/workspaces/{workspace_id}/seen")
async def mark_seen(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    u=await user(session); await workspace_or_404(session,workspace_id);state=(await session.execute(select(UserWorkspaceState).where(UserWorkspaceState.user_id==u.id,UserWorkspaceState.workspace_id==workspace_id))).scalar_one_or_none()
    latest=(await session.execute(select(Commit).where(Commit.workspace_id==workspace_id).order_by(desc(Commit.created_at)))).scalars().first()
    since=state.last_seen_at if state else None; q=select(func.count(Commit.id)).where(Commit.workspace_id==workspace_id)
    if since:q=q.where(Commit.created_at>since)
    count=(await session.execute(q)).scalar_one()
    if not state:state=UserWorkspaceState(user_id=u.id,workspace_id=workspace_id);session.add(state)
    state.last_seen_at=datetime.utcnow();state.last_seen_commit_id=latest.id if latest else None;await session.commit();return {"commits_since_last_seen":count,"last_seen_at":since}
