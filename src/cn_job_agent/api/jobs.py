"""Background work for the web API: job-graph runs and collections run in a
small thread pool, and every node update is kept as an event the browser
follows over Server-Sent Events."""
import threading
from collections import defaultdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ..agents import collect as collect_module
from ..agents import runner


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def summarize_update(node, update):
    """A small, JSON-safe event for one graph node update."""
    event = {"node": node, "at": _now()}
    if node == "__interrupt__":
        values = [getattr(i, "value", i) for i in (update or ())]
        first = values[0] if values else {}
        event["question"] = first.get("question", "") if isinstance(first, dict) else str(first)
        return event
    update = update or {}
    if node == "rule_screen":
        event["flags"] = len(update.get("rule_flags", []))
    elif node == "extract":
        extraction = update.get("extraction") or {}
        event["requirements"] = len(extraction.get("requirements", []))
        event["failed_batches"] = len(extraction.get("failed_batches", []))
    elif node == "decide":
        event["decision"] = (update.get("screening") or {}).get("decision")
    elif node == "human_review":
        event["approved"] = update.get("approved")
    elif node == "match_one":
        match = (update.get("matches") or [{}])[0]
        event.update(requirement_id=match.get("requirement_id"), verdict=match.get("verdict"),
                     text=(match.get("text") or "")[:80])
    elif node == "summarize":
        summary = update.get("summary") or {}
        event.update(score=summary.get("score"), label=summary.get("label"))
    elif node == "finalize":
        event["report_path"] = update.get("report_path")
    for item in update.get("trace", []) if isinstance(update.get("trace"), list) else []:
        if item.get("node") == node and "seconds" in item:
            event["seconds"] = item["seconds"]
    return event


class JobManager:
    def __init__(self, settings, toolkit, checkpointer_factory, collect_options=None, workers=2):
        self.settings = settings
        self.toolkit = toolkit
        self.checkpointer_factory = checkpointer_factory
        self.collect_options = collect_options or {}
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cn-agent-job")
        self.events = defaultdict(list)
        self.finished = set()
        self.futures = {}
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- events
    def emit(self, key, event):
        with self.lock:
            self.events[key].append(event)

    def events_since(self, key, index):
        with self.lock:
            return list(self.events.get(key, [])[index:]), key in self.finished

    def known(self, key):
        """Whether this process started (or resumed) the run or collection."""
        with self.lock:
            return key in self.events

    def _finish(self, key):
        with self.lock:
            self.events[key].append({"node": "__end__", "at": _now()})
            self.finished.add(key)

    def _restart(self, key):
        with self.lock:
            self.finished.discard(key)

    def wait(self, key, timeout=60):
        """For tests and scripts: block until the background job for `key` has finished."""
        future = self.futures.get(key)
        if future:
            future.result(timeout=timeout)

    # ---------------------------------------------------------------- job graph
    def _graph_event(self, run_id, node, update):
        self.emit(run_id, summarize_update(node, update))

    def _execute(self, run_id, payload):
        try:
            with self.checkpointer_factory() as saver:
                runner.execute(self.toolkit, saver, run_id, payload, on_event=self._graph_event)
        except Exception as exc:  # noqa: BLE001 - e.g. the checkpoint database is unreachable
            runner._mark(self.toolkit.database_url, run_id, status="failed",
                         error=f"{exc.__class__.__name__}: {exc}")
        finally:
            self._finish(run_id)

    def run_posting(self, posting_id, force=False, auto_approve=False):
        run_id, payload = runner.create_run(self.toolkit, posting_id, force, auto_approve)
        self.emit(run_id, {"node": "__start__", "at": _now()})
        self.futures[run_id] = self.executor.submit(self._execute, run_id, payload)
        return run_id

    def resume(self, run_id, approve=None):
        payload = runner.prepare_resume(self.toolkit, run_id, approve)
        self._restart(run_id)
        self.emit(run_id, {"node": "__resume__", "at": _now(), "approved": approve})
        self.futures[run_id] = self.executor.submit(self._execute, run_id, payload)
        return run_id

    # ---------------------------------------------------------------- collections
    def _collection_event(self, collection_id, kind, data):
        self.emit(collection_id, {"node": kind, "at": _now(), **data})

    def _collect(self, collection_id, mode):
        try:
            collect_module.collect(self.settings, mode=mode, database_url=self.toolkit.database_url,
                                   run_id=collection_id, on_event=self._collection_event, **self.collect_options)
        finally:
            self._finish(collection_id)

    def start_collection(self, mode="auto"):
        if mode not in ("auto", "agent", "rules"):
            raise ValueError("mode 必须是 auto、agent 或 rules")
        collection_id = collect_module.new_collection_id()
        self.emit(collection_id, {"node": "__start__", "at": _now(), "mode": mode})
        self.futures[collection_id] = self.executor.submit(self._collect, collection_id, mode)
        return collection_id

    # ---------------------------------------------------------------- materials
    def _materials(self, key, run_id):
        from ..agents import materials
        try:
            result = materials.build(self.settings, run_id, self.toolkit.get_llm(),
                                     database_url=self.toolkit.database_url, outputs_dir=self.toolkit.outputs_dir)
            self.emit(key, {"node": "materials", "at": _now(), "folder": Path(result.folder).name,
                            "warnings": len(result.warnings)})
        except Exception as exc:  # noqa: BLE001 - shown in the UI
            self.emit(key, {"node": "__error__", "at": _now(), "error": f"{exc.__class__.__name__}: {exc}"})
        finally:
            self._finish(key)

    def _interview(self, key, run_id):
        from ..agents import interview
        try:
            result = interview.build(self.settings, run_id, self.toolkit.get_llm(),
                                     database_url=self.toolkit.database_url, outputs_dir=self.toolkit.outputs_dir)
            self.emit(key, {"node": "interview", "at": _now(), "warnings": len(result["warnings"])})
        except Exception as exc:  # noqa: BLE001 - shown in the UI
            self.emit(key, {"node": "__error__", "at": _now(), "error": f"{exc.__class__.__name__}: {exc}"})
        finally:
            self._finish(key)

    def generate_interview(self, run_id):
        """Start the interview-prep agent for a finished run; returns the event key."""
        self._check_done(run_id)
        key = f"i-{run_id}-{datetime.now(timezone.utc):%H%M%S%f}"
        self.emit(key, {"node": "__start__", "at": _now()})
        self.futures[key] = self.executor.submit(self._interview, key, run_id)
        return key

    def _check_done(self, run_id):
        from ..db.models import AgentRun
        from ..db.session import session_scope
        with session_scope(self.toolkit.database_url) as s:
            run = s.get(AgentRun, run_id)
            if run is None:
                raise LookupError(f"没有编号为 {run_id} 的运行")
            if run.status != "done":
                raise ValueError("只有完成了证据匹配的运行才能生成面试准备或申请材料")

    def generate_materials(self, run_id):
        """Start the materials agent for a finished run; returns the event key."""
        from ..db.models import AgentRun
        from ..db.session import session_scope
        with session_scope(self.toolkit.database_url) as s:
            run = s.get(AgentRun, run_id)
            if run is None:
                raise LookupError(f"没有编号为 {run_id} 的运行")
            if run.status != "done":
                raise ValueError("只有完成了证据匹配的运行才能生成申请材料")
        key = f"m-{run_id}-{datetime.now(timezone.utc):%H%M%S%f}"
        self.emit(key, {"node": "__start__", "at": _now()})
        self.futures[key] = self.executor.submit(self._materials, key, run_id)
        return key

    def shutdown(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
