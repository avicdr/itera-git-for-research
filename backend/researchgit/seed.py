import asyncio
from researchgit.core.db import engine,SessionLocal
from researchgit.models import Base,User,Workspace,WorkspaceMember,Branch,Artifact,ArtifactVersion
from researchgit.versioning.commits import create_commit
from researchgit.core.auth import hash_password
async def seed():
 async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
 async with SessionLocal() as s:
  u=User(name="Anoushka",email="anoushka@example.test",password_hash=hash_password("researchgit-demo"));s.add(u);await s.flush();w=Workspace(name="Autonomous systems evidence",description="Demo research corpus",created_by=u.id);s.add(w);await s.flush();s.add(WorkspaceMember(workspace_id=w.id,user_id=u.id,role="OWNER"));main=Branch(workspace_id=w.id,name="main",created_by=u.id,is_protected=True);s.add(main);await s.flush()
  state={}
  for name,text in [("hypothesis.md","Autonomous systems require continuous human oversight."),("literature-review.md","Evidence is mixed across evaluation settings.")]:
   a=Artifact(workspace_id=w.id,name=name[:-3],original_filename=name,artifact_type="DOCUMENT",mime_type="text/markdown",created_by=u.id,status="READY");s.add(a);await s.flush();v=ArtifactVersion(artifact_id=a.id,version_number=1,storage_path="",content_hash="seed",canonical_text=text,created_by=u.id);s.add(v);await s.flush();state[a.id]=v.id
  await create_commit(s,w.id,main,u.id,"Initial research corpus",state);branch=Branch(workspace_id=w.id,name="counter-hypothesis",head_commit_id=main.head_commit_id,created_by=u.id);s.add(branch);await s.commit();print(w.id)
def main(): asyncio.run(seed())
