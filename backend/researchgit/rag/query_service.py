import json
from researchgit.retrieval.hybrid_search import search
from researchgit.versioning.commits import branch_state
from researchgit.models import Branch, Artifact, ArtifactVersion
from sqlalchemy import select
from researchgit.rag.generation import get_llm_provider, ConciseExtractiveProvider

async def answer(session, workspace_id, chat_id, branch_id, message, context):
    branch=await session.get(Branch,branch_id)
    if not branch or branch.workspace_id != workspace_id:
        return "The selected branch is unavailable in this workspace.", []
    # Before the first commit, the working corpus is the latest version of every
    # workspace artifact. After committing, retrieval is strictly pinned to the
    # immutable snapshot at the current branch head.
    visible=list((await branch_state(session,branch.head_commit_id)).values())
    if not visible:
        latest=(await session.execute(
            select(ArtifactVersion.id).join(Artifact).where(Artifact.workspace_id==workspace_id, Artifact.deleted_at==None)
        )).scalars().all()
        visible=list(latest)
    enabled=[]
    if context.get("documents", True): enabled.append("DOCUMENT")
    if context.get("pdfs", True): enabled.append("PDF")
    if context.get("chat_exports", True): enabled.append("CHAT_EXPORT")
    rows=await search(session,workspace_id,visible,message,chat_id,types=enabled or None,limit=8)
    citations=[]; excerpts=[]
    for i,(_,chunk,artifact) in enumerate(rows,1):
        citations.append({"source_id":f"SOURCE_{i}","artifact_id":str(artifact.id),"artifact_name":artifact.name,"artifact_version_id":str(chunk.artifact_version_id),"page":chunk.page_number,"chunk_id":str(chunk.id)})
        excerpts.append(f"[SOURCE_{i}] {artifact.name}"+(f", page {chunk.page_number}" if chunk.page_number else "")+f"\n{chunk.content}")
    if not excerpts: return "I couldn't find evidence in the versions visible on this branch.", citations
    try:
        return await get_llm_provider().generate(message, excerpts), citations
    except Exception:
        return await ConciseExtractiveProvider().generate(message,excerpts), citations
