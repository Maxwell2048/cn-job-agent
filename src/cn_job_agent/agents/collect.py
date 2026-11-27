"""One collection run: the search planner fills job_postings from the job sites.

mode "agent"  the tool-calling planner on the local model; fails if no model
mode "rules"  the fixed plan, no model
mode "auto"   agent when the local model is reachable and its run succeeds,
              otherwise rules (the reason is recorded in the run's trace)
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from ..collectors import Http, build_collectors
from ..db.models import CollectionRun, SearchProfile
from ..db.session import session_scope
from . import planner
from .graph import PROFILE_FIELDS


@dataclass
class CollectionOutcome:
    run_id: str
    mode: str
    status: str
    stats: dict = field(default_factory=dict)
    saved: list = field(default_factory=list)
    plan: list = field(default_factory=list)
    error: str = ""


def load_profile(database_url, name="default"):
    with session_scope(database_url) as s:
        row = s.scalar(select(SearchProfile).where(SearchProfile.name == name))
        if row is None:
            raise ValueError("数据库里还没有求职画像；先运行 cn-agent profile")
        return {k: getattr(row, k) for k in PROFILE_FIELDS}


def new_collection_id():
    return f"c-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


SEARCHES_PER_SOURCE = 25


def collect(settings, mode="auto", database_url=None, collectors=None, chat_model=None, max_saves=50,
            max_searches=None, run_id=None, on_event=None):
    """max_searches defaults to 25 per job site, so adding sites does not cut the plan short."""
    if mode not in ("auto", "agent", "rules"):
        raise ValueError("mode 必须是 auto、agent 或 rules")
    url = database_url or settings.database_url
    run_id = run_id or new_collection_id()
    http = None
    if collectors is None:
        http = Http()
        collectors = build_collectors(http)
    max_searches = max_searches or SEARCHES_PER_SOURCE * len(collectors)
    profile = load_profile(url)
    with session_scope(url) as s:
        s.add(CollectionRun(id=run_id, mode=mode, status="running", plan=[], stats={}, trace=[]))
    ws = planner.Workspace(url, collectors, profile, run_id, max_saves=max_saves, max_searches=max_searches,
                           on_event=(lambda kind, data: on_event(run_id, kind, data)) if on_event else None)
    trace, used, status, error = [], mode, "done", ""
    try:
        if mode in ("auto", "agent"):
            try:
                model = chat_model or planner.build_chat_model(settings)
                trace += planner.run_agent(ws, model)
                used = "agent"
            except Exception as exc:  # noqa: BLE001 - model offline, no tool support, or a failed step
                if mode == "agent":
                    raise
                trace.append({"type": "fallback", "text": f"Agent 模式不可用，改用规则模式：{exc.__class__.__name__}: "
                                                          f"{str(exc)[:300]}"})
                used = "rules"
        if used == "rules":
            trace += planner.run_rules(ws)
    except Exception as exc:  # noqa: BLE001 - recorded on the run
        status, error = "failed", f"{exc.__class__.__name__}: {exc}"
    finally:
        if http is not None:
            http.close()
        with session_scope(url) as s:
            run = s.get(CollectionRun, run_id)
            run.mode, run.status, run.error = used, status, error
            run.plan, run.stats, run.trace = ws.plan, {**ws.stats(), "saved_ids": ws.saved}, trace
            run.finished_at = datetime.now(timezone.utc)
    return CollectionOutcome(run_id, used, status, ws.stats(), ws.saved, ws.plan, error)
