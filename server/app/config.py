from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./data/code-retro.db"
    public_base_url: str = "http://127.0.0.1:8000"
    cookie_secure: bool = False
    session_days: int = 30
    ai_enabled: bool = False
    ai_provider: Literal["gemini", "openai"] = "gemini"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4.1-mini"
    github_token: SecretStr = SecretStr("")
    max_files: int = Field(300, ge=1, le=1000)
    max_file_bytes: int = 262144
    max_total_bytes: int = 5242880
    max_tree_entries: int = 100000
    max_tree_requests: int = 100
    max_history_commits: int = 100
    max_projects_per_session: int = 10
    ai_daily_token_limit: int = 200000
    ai_max_calls_per_job: int = 24
    ai_max_output_tokens: int = 5000
    ai_max_tools_per_job: int = 80
    ai_max_context_tokens: int = 48000
    job_lease_seconds: int = 180
    global_job_limit: int = 2
    public_limits_enabled: bool = False
    trust_proxy_headers: bool = False
    global_project_limit: int = 30
    database_limit_bytes: int = 314572800

    @property
    def origins(self) -> set[str]:
        values = {self.public_base_url.rstrip("/")}
        if self.app_env != "production":
            values |= {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8000)}
        return values

    @property
    def ai_ready(self) -> bool:
        key = self.gemini_api_key if self.ai_provider == "gemini" else self.openai_api_key
        return self.ai_enabled and bool(key.get_secret_value())

    @property
    def ai_model(self) -> str:
        return self.gemini_model if self.ai_provider == "gemini" else self.openai_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
