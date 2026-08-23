from sqlalchemy import select, or_
from researchgit.models import ArtifactChunk, Artifact
from researchgit.embeddings.provider import provider

async def search(session, workspace_id, visible_versions, query, chat_id=None, types=None, limit=8):
    if not visible_versions: return []
    qv=(await provider.embed_texts([query]))[0]
    rows=(await session.execute(select(ArtifactChunk,Artifact).join(Artifact).where(ArtifactChunk.workspace_id==workspace_id,ArtifactChunk.artifact_version_id.in_(visible_versions),or_(ArtifactChunk.scope=="WORKSPACE",ArtifactChunk.chat_id==chat_id)))).all()
    terms=set(query.lower().split())
    scored=[]
    for c,a in rows:
        if types and a.artifact_type not in types: continue
        vec=sum(x*y for x,y in zip(c.embedding or [],qv)); lex=len(terms & set(c.content.lower().split()))/(len(terms) or 1)
        scored.append((.7*vec+.3*lex,c,a))
    return sorted(scored,key=lambda x:x[0],reverse=True)[:limit]
