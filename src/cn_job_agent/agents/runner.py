"""Start and resume runs of the job graph, with LangGraph checkpoints in PostgreSQL.

Each run has one id that is both the agent_runs primary key and the LangGraph
thread_id, so an interrupted or failed run continues exactly where it stopped:
`resume(run_id, approve=True)` answers the human-review interrupt, and
`resume(run_id)` without an answer retries after a failure (completed
requirement branches are not re-run).
"""
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from langgraph.types import Command

from ..db.models import AgentRun, JobPosting
from ..db.session import session_scope
from ..rag import bridge
from . import graph as job_graph
from . import matching


class Toolkit:
    """What the graph's nodes need. Everything expensive is built on first use,
    so a run that the rules reject never loads the embedding model.

    These are plain methods, not properties: when LangGraph compiles a graph it
    reads the attributes that node closures use (looking for subgraphs), which
    would build a property's value at compile time."""

    def __init__(self, settings, database_url=None, profile_name="default"):
        self.settings = settings
        self.database_url = database_url or settings.database_url
        self.outputs_dir = settings.outputs_dir
        self.profile_name = profile_name
        self._built = {}
        self._lock = threading.RLock()   # get_matcher builds the llm and embedder while holding it

    def today(self):
        return date.today()

    def _once(self, name, build):
        with self._lock:
            if name not in self._built:
                self._built[name] = build()
            return self._built[name]

    def get_jd_parser(self):
        return bridge.load(self.settings.job_rag_home, "jd_parser")

    def get_llm(self):
        return self._once("llm", lambda: matching.build_llm(self.settings))

    def get_embedder(self):
        from ..rag.embedder import E5Embedder
        return self._once("embedder", lambda: E5Embedder(bridge.search_module(self.settings.job_rag_home).MODEL,
                                                         offline=self.settings.offline))

    def get_matcher(self):
        def build():
            evidence_matcher = bridge.load(self.settings.job_rag_home, "evidence_matcher")
            retriever = matching.PgRetriever(self.database_url, self.get_embedder(),
                                             bridge.search_module(self.settings.job_rag_home))
            return evidence_matcher.EvidenceMatcher(self.get_llm(), retriever, top_k=self.settings.match_top_k)
        return self._once("matcher", build)

    def versions(self):
        home = self.settings.job_rag_home
        out = {"graph": job_graph.GRAPH_VERSION,
               "extraction_prompt": bridge.load(home, "jd_parser").EXTRACTION_PROMPT_VERSION,
               "judgment_prompt": bridge.load(home, "evidence_matcher").JUDGMENT_PROMPT_VERSION}
        if "llm" in self._built:
            out["model"] = getattr(self._built["llm"], "model", "")
        return out


@dataclass
class Outcome:
    run_id: str
    status: str                       # interrupted | rejected | done | failed
    report_path: str = ""
    screening: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    interrupt: dict | None = None
    error: str = ""


@contextmanager
def postgres_checkpointer(settings):
    from langgraph.checkpoint.postgres import PostgresSaver
    with PostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        yield saver


def setup_checkpointer(settings):
    """Create LangGraph's checkpoint tables (idempotent)."""
    with postgres_checkpointer(settings) as saver:
        saver.setup()


def new_run_id():
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def _config(run_id, settings):
    return {"configurable": {"thread_id": run_id}, "max_concurrency": max(1, settings.match_concurrency)}


def _mark(database_url, run_id, **fields):
    with session_scope(database_url) as s:
        run = s.get(AgentRun, run_id)
        for key, value in fields.items():
            setattr(run, key, value)
        if fields.get("status") == "interrupted":
            s.get(JobPosting, run.posting_id).status = "review"
        if fields.get("status") == "failed":
            run.finished_at = datetime.now(timezone.utc)
            s.get(JobPosting, run.posting_id).status = "failed"


def _invoke(toolkit, checkpointer, run_id, payload):
    graph = job_graph.build_graph(toolkit, checkpointer)
    config = _config(run_id, toolkit.settings)
    try:
        graph.invoke(payload, config)
    except Exception as exc:  # noqa: BLE001 - recorded on the run; the checkpoint allows a retry
        message = f"{exc.__class__.__name__}: {exc}"
        _mark(toolkit.database_url, run_id, status="failed", error=message)
        return Outcome(run_id, "failed", error=message)
    snapshot = graph.get_state(config)
    if snapshot.next:
        payloads = [i.value for task in snapshot.tasks for i in task.interrupts]
        _mark(toolkit.database_url, run_id, status="interrupted", error="")
        return Outcome(run_id, "interrupted", screening=snapshot.values.get("screening", {}),
                       interrupt=payloads[0] if payloads else None)
    with session_scope(toolkit.database_url) as s:
        run = s.get(AgentRun, run_id)
        return Outcome(run_id, run.status, run.report_path, run.screening, run.summary, error=run.error)


def start(toolkit, checkpointer, posting_id, force=False, auto_approve=False):
    run_id = new_run_id()
    options = {"force": force, "auto_approve": auto_approve}
    with session_scope(toolkit.database_url) as s:
        if s.get(JobPosting, posting_id) is None:
            raise ValueError(f"没有编号为 {posting_id} 的岗位；用 cn-agent jd list 查看")
        s.add(AgentRun(id=run_id, posting_id=posting_id, graph_version=job_graph.GRAPH_VERSION,
                       status="running", screening={}, summary={}, versions={"options": options}, trace=[]))
    return _invoke(toolkit, checkpointer, run_id,
                   {"run_id": run_id, "posting_id": posting_id, "options": options})


def resume(toolkit, checkpointer, run_id, approve=None):
    """approve=True/False answers the review question; None retries a failed run."""
    with session_scope(toolkit.database_url) as s:
        run = s.get(AgentRun, run_id)
        if run is None:
            raise ValueError(f"没有编号为 {run_id} 的运行")
        if run.status == "interrupted" and approve is None:
            raise ValueError("这个运行在等你确认；加 --approve 或 --decline")
        if run.status not in ("interrupted", "failed"):
            raise ValueError(f"这个运行的状态是 {run.status}，不需要继续")
        run.status, run.error = "running", ""
    payload = Command(resume=approve) if approve is not None else None
    return _invoke(toolkit, checkpointer, run_id, payload)
