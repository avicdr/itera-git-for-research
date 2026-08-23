import hashlib, uuid
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from researchgit.models import Commit, CommitParent, CommitArtifactVersion, ArtifactVersion, Branch

async def branch_state(session: AsyncSession, commit_id):
    if not commit_id: return {}
    rows=(await session.execute(select(CommitArtifactVersion).where(CommitArtifactVersion.commit_id==commit_id))).scalars()
    return {x.artifact_id:x.artifact_version_id for x in rows}
async def create_commit(session, workspace_id, branch: Branch, author_id, message, state: dict, second_parent=None):
    commit=Commit(workspace_id=workspace_id,author_id=author_id,message=message,short_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:10])
    session.add(commit); await session.flush()
    for p in [branch.head_commit_id,second_parent]:
        if p: session.add(CommitParent(commit_id=commit.id,parent_id=p))
    for artifact_id, version_id in state.items(): session.add(CommitArtifactVersion(commit_id=commit.id,artifact_id=artifact_id,artifact_version_id=version_id))
    branch.head_commit_id=commit.id
    return commit
async def common_ancestor(session, left, right):
    async def lineage(start):
        found=set(); queue=[start]
        while queue:
            c=queue.pop()
            if not c or c in found: continue
            found.add(c); queue += list((await session.execute(select(CommitParent.parent_id).where(CommitParent.commit_id==c))).scalars())
        return found
    l=await lineage(left); queue=[right]; seen=set()
    while queue:
        c=queue.pop(0)
        if c in l: return c
        if c and c not in seen:
            seen.add(c); queue += list((await session.execute(select(CommitParent.parent_id).where(CommitParent.commit_id==c))).scalars())
    return None
