from sqlalchemy import select
from researchgit.models import ArtifactVersion
from .commits import branch_state, common_ancestor

async def plan_merge(session, target, source):
    base_id=await common_ancestor(session,target.head_commit_id,source.head_commit_id)
    base=await branch_state(session,base_id); ours=await branch_state(session,target.head_commit_id); theirs=await branch_state(session,source.head_commit_id)
    result=dict(ours); conflicts=[]
    for artifact_id in set(base)|set(ours)|set(theirs):
        b,o,t=base.get(artifact_id),ours.get(artifact_id),theirs.get(artifact_id)
        if o==t or t==b: result[artifact_id]=o
        elif o==b: result[artifact_id]=t
        else:
            versions=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.id.in_([x for x in [b,o,t] if x])))).scalars().all(); text={x.id:x.canonical_text for x in versions}
            conflicts.append({"artifact_id":artifact_id,"base":text.get(b,""),"target":text.get(o,""),"source":text.get(t,"")})
    return result,conflicts,base_id
