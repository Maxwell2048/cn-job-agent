"""Settings from environment variables (CN_ prefix) or a .env file in the project root."""
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CN_", env_file=PROJECT_ROOT / ".env",
                                      env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://cn_agent:change-me@127.0.0.1:5433/cn_job_agent"
    job_rag_home: Path = Path("E:/CV/job_rag_starter")
    experiences_dir: Path | None = None
    profile_path: Path = Path("profile.local.yaml")
    seed_path: Path = PROJECT_ROOT / "data" / "seed" / "campus_2027.yaml"
    offline: bool = True
    # Language model: "local" (job_rag_starter's config.local.json) or a mainstream API,
    # see cn_job_agent.llm.PROVIDERS. Cloud providers need CN_LLM_MODEL and an API key.
    llm_provider: str = "local"
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    llm_base_url: str = ""
    llm_response_format: str = ""          # empty: the provider's default
    llm_context_budget: int | None = None
    llm_max_output_tokens: int | None = None
    llm_timeout_seconds: int = 300
    llm_temperature: float = 0.0
    # Local model config in job_rag_starter's format (defaults to its config.local.json)
    llm_config: Path | None = None
    # Chinese base resume (private JSON: name, contact, education, confirmed skills) for the materials agent
    resume_base: Path | None = None                 # env CN_RESUME_BASE
    greeting_max_chars: int = 150
    outputs_dir: Path = PROJECT_ROOT / "outputs"
    state_dir: Path = PROJECT_ROOT / "state"
    match_top_k: int = 5
    # Requirements judged at the same time. Empty: 2 for the local model (keep at or below its
    # server's parallel slots), 8 for a cloud API.
    match_concurrency: int | None = None

    @property
    def experiences(self) -> Path:
        return self.experiences_dir or self.job_rag_home / "experiences"

    @property
    def concurrency(self) -> int:
        if self.match_concurrency:
            return max(1, self.match_concurrency)
        return 2 if (self.llm_provider or "local").strip().lower() == "local" else 8

    @property
    def llm_config_file(self) -> Path:
        return self.llm_config or self.job_rag_home / "config.local.json"

    @property
    def checkpoint_url(self) -> str:
        """libpq URL for LangGraph's PostgresSaver (no SQLAlchemy driver suffix)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @property
    def profile_file(self) -> Path:
        path = self.profile_path
        return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
