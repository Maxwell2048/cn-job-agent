"""Settings from environment variables (CN_ prefix) or a .env file in the project root."""
from functools import lru_cache
from pathlib import Path

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

    @property
    def experiences(self) -> Path:
        return self.experiences_dir or self.job_rag_home / "experiences"

    @property
    def profile_file(self) -> Path:
        path = self.profile_path
        return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
