"""Point cn-job-agent at the fictional demo candidate instead of the real one.

Import this before anything from cn_job_agent: it sets the CN_* variables so
the demo uses its own database (cn_job_agent_demo), experiences, profile,
base resume and output folder. The language model settings stay as in .env.
"""
import os
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
SNAPSHOT = DEMO / "snapshot"
DEMO_DB = "cn_job_agent_demo"


def activate():
    from cn_job_agent.config import Settings, get_settings
    real = Settings()                                   # reads .env for the server address and the model
    url = make_url(real.database_url).set(database=DEMO_DB)
    os.environ.update({
        "CN_DATABASE_URL": url.render_as_string(hide_password=False),
        "CN_EXPERIENCES_DIR": str(DEMO / "experiences"),
        "CN_PROFILE_PATH": str(DEMO / "profile.yaml"),
        "CN_RESUME_BASE": str(DEMO / "base_resume.json"),
        "CN_OUTPUTS_DIR": str(ROOT / "state" / "demo_outputs"),
    })
    get_settings.cache_clear()
    settings = get_settings()
    assert make_url(settings.database_url).database == DEMO_DB
    return settings
