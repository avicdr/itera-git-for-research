from abc import ABC, abstractmethod
import re
import httpx
from researchgit.core.config import settings

class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, question: str, sources: list[str]) -> str: ...

class ConciseExtractiveProvider(LLMProvider):
    async def generate(self, question, sources):
        """Useful local fallback: answers briefly rather than dumping context."""
        points=[]
        for source in sources[:3]:
            label=source.split("\n",1)[0].split("]",1)[0]+"]"
            body=source.split("\n",1)[-1].replace("\n"," ").strip()
            sentence=next((x.strip() for x in re.split(r"(?<=[.!?])\s+",body) if len(x.strip())>30), body[:280])
            points.append(f"- {sentence[:420]} {label}")
        return "Here is the evidence most relevant to your question:\n\n"+"\n".join(points)+"\n\nI can compare these sources or look for counter-evidence if you want."

class OpenAICompatibleProvider(LLMProvider):
    async def generate(self, question, sources):
        prompt="""You are ResearchGit, a careful research collaborator. Answer ONLY from the supplied sources. Be concise (maximum 220 words), synthesize rather than copy, distinguish evidence from inference, and cite every factual claim with one or more exact [SOURCE_n] identifiers. If evidence is missing or contradictory, say so.\n\nQuestion:\n"""+question+"\n\nSources:\n"+"\n\n".join(sources)
        headers={"Authorization":f"Bearer {settings.openai_api_key}","Content-Type":"application/json"}
        payload={"model":settings.chat_model,"messages":[{"role":"system","content":"You provide source-grounded research assistance."},{"role":"user","content":prompt}],"temperature":0.2,"max_tokens":500}
        async with httpx.AsyncClient(timeout=45) as client:
            response=await client.post(settings.openai_base_url.rstrip("/")+"/chat/completions",headers=headers,json=payload)
            response.raise_for_status(); return response.json()["choices"][0]["message"]["content"]

class OllamaProvider(LLMProvider):
    """Local model provider. Ollama runs beside the API on the hosted server."""
    async def generate(self, question, sources):
        prompt="""You are ResearchGit, a careful research collaborator. Answer ONLY from the supplied sources. Be concise (maximum 220 words), synthesize rather than copy, distinguish evidence from inference, and cite every factual claim with exact [SOURCE_n] identifiers. If evidence is missing or contradictory, say so.\n\nQuestion:\n"""+question+"\n\nSources:\n"+"\n\n".join(sources)
        body={"model":settings.ollama_model,"stream":False,"options":{"temperature":0.2,"num_predict":420},"messages":[{"role":"system","content":"You provide precise source-grounded research assistance."},{"role":"user","content":prompt}]}
        async with httpx.AsyncClient(timeout=90) as client:
            response=await client.post(settings.ollama_base_url.rstrip("/")+"/api/chat",json=body)
            response.raise_for_status(); return response.json()["message"]["content"]

def get_llm_provider() -> LLMProvider:
    if settings.llm_provider.lower() == "ollama": return OllamaProvider()
    return OpenAICompatibleProvider() if settings.llm_provider.lower() in {"openai","openai_compatible"} and settings.openai_api_key else ConciseExtractiveProvider()
