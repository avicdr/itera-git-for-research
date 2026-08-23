import hashlib, json, re, fitz
from pathlib import Path
from sqlalchemy import delete
from researchgit.models import Artifact, ArtifactVersion, ArtifactChunk, ArtifactStatus
from researchgit.embeddings.provider import provider

def extract(path: Path, mime: str):
    if mime=="application/pdf":
        doc=fitz.open(path); return "\n\n".join(f"[Page {i+1}]\n{p.get_text()}" for i,p in enumerate(doc))
    raw=path.read_text(encoding="utf-8",errors="replace")
    if path.suffix.lower()==".json":
        try:
            data=json.loads(raw); return _chat_text(data)
        except json.JSONDecodeError: pass
    return raw
def _chat_text(data):
    if isinstance(data,list): return "\n\n".join(_chat_text(x) for x in data)
    if isinstance(data,dict):
        if "mapping" in data: return "\n\n".join(str(x.get("message",{}).get("content",{}).get("parts",[""])[0]) for x in data["mapping"].values() if x.get("message"))
        return "\n".join(str(v) for k,v in data.items() if k in {"text","content","prompt","completion","human","assistant"})
    return str(data)
def chunk(text, size=3000, overlap=400):
    sections=re.split(r"\n(?=#|\[Page )",text); out=[]; carry=""
    for section in sections:
        words=section.split(); current=carry.split()
        for word in words:
            current.append(word)
            if len(" ".join(current))>=size:
                out.append(" ".join(current)); current=current[-overlap//6:]
        carry=" ".join(current)
    if carry.strip(): out.append(carry)
    return out
async def process(session, artifact: Artifact, version: ArtifactVersion, root: Path):
    artifact.status=ArtifactStatus.PROCESSING.value
    path=(root/version.storage_path).resolve()
    text=extract(path,artifact.mime_type); version.canonical_text=text
    extracted=root/f"workspaces/{artifact.workspace_id}/artifacts/{artifact.id}/extracted/v{version.version_number}.json"; extracted.parent.mkdir(parents=True,exist_ok=True); extracted.write_text(json.dumps({"text":text}))
    artifact.status=ArtifactStatus.INDEXING.value
    parts=chunk(text); vectors=await provider.embed_texts(parts)
    await session.execute(delete(ArtifactChunk).where(ArtifactChunk.artifact_version_id==version.id))
    for i,(part,vector) in enumerate(zip(parts,vectors)):
        page=re.search(r"\[Page (\d+)\]",part)
        session.add(ArtifactChunk(workspace_id=artifact.workspace_id,artifact_id=artifact.id,artifact_version_id=version.id,scope=artifact.scope,chat_id=artifact.chat_id,content=part,chunk_index=i,page_number=int(page.group(1)) if page else None,section_title=None,embedding=vector))
    artifact.status=ArtifactStatus.READY.value
