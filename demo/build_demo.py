"""Build the public demo dataset with the real pipeline and a fictional candidate.

    .venv/Scripts/python.exe demo/build_demo.py      # needs Docker (PostgreSQL) and a model in .env

1. creates the cn_job_agent_demo database and migrates it
2. loads the campus seed, the fictional profile and indexes demo/experiences
3. collects real public postings in agent mode (a few per run)
4. screens and matches them (reviews approved automatically for the demo)
5. writes tailored materials for the best-scoring runs
Then run demo/export_snapshot.py to turn the result into static JSON.
"""
import sys

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

import demo_env

settings = demo_env.activate()

from cn_job_agent import cli  # noqa: E402  (after the environment is set)
from cn_job_agent.db.models import AgentRun  # noqa: E402
from cn_job_agent.db.session import session_scope  # noqa: E402

MAX_POSTINGS = 8
MATERIALS_FOR = 3


def step(*argv):
    print(f"\n==> cn-agent {' '.join(argv)}", flush=True)
    code = cli.main(list(argv))
    if code:
        sys.exit(f"cn-agent {' '.join(argv)} failed ({code})")


def create_database():
    url = make_url(settings.database_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if not conn.execute(text("select 1 from pg_database where datname = :d"), {"d": url.database}).scalar():
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


def main():
    create_database()
    step("db", "upgrade")
    step("seed")
    step("profile")
    step("index")
    step("collect", "--mode", "agent", "--max-saves", str(MAX_POSTINGS))
    step("run", "--pending", "--limit", str(MAX_POSTINGS), "--approve-review")
    with session_scope(settings.database_url) as s:
        runs = [r for r in s.scalars(select(AgentRun).where(AgentRun.status == "done")) if r.summary.get("score") is not None]
        best = [r.id for r in sorted(runs, key=lambda r: -r.summary["score"])[:MATERIALS_FOR]]
    for run_id in best:
        step("materials", run_id)
        step("interview", run_id)
    print("\nDemo data ready. Next: python demo/export_snapshot.py")


if __name__ == "__main__":
    main()
