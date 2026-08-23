from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite+aiosqlite:///./researchgit.db"
    storage_root: Path = Path("./storage")
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    max_upload_bytes: int = 26_214_400
    embedding_provider: str = "deterministic"
    llm_provider: str = "extractive"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4o-mini"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"

settings = Settings()
