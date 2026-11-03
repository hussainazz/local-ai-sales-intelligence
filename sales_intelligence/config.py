from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SALES_", env_file=".env", extra="ignore")
    api_key: str = Field(min_length=24)
    data_dir: Path = Path("data")
    ollama_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3:8b"
    embedding_model: str = "nomic-embed-text"
    use_llm: bool = False
    max_upload_mb: int = Field(25, ge=1, le=100)
    max_rows: int = Field(200_000, ge=10, le=1_000_000)
    max_columns: int = Field(200, ge=3, le=1000)
    workers: int = Field(1, ge=1, le=2)
    llm_timeout: int = Field(120, ge=5, le=300)
    retention_days: int = Field(30, ge=1)

    @field_validator("ollama_url")
    @classmethod
    def local_only(cls, value):
        url = urlparse(value)
        if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1", "ollama"}:
            raise ValueError("Ollama must use a loopback address or the local Compose service 'ollama'.")
        if url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
            raise ValueError("Use a plain local Ollama origin.")
        return value.rstrip("/")

    @field_validator("llm_model", "embedding_model")
    @classmethod
    def no_cloud(cls, value):
        if not value or "cloud" in value.lower() or "/" in value:
            raise ValueError("Only an explicitly downloaded local model tag is allowed.")
        return value

    def prepare(self):
        self.data_dir = self.data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self
