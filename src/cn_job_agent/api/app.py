"""FastAPI app: the job agents behind a local web UI.

    cn-agent serve            http://127.0.0.1:8100  (API under /api, the React app at /)

Long work (a job-graph run, a collection) starts in a background thread and
returns its id at once; the browser follows progress over Server-Sent Events
(/api/runs/{id}/events, /api/collections/{id}/events). The server binds to
localhost and never returns the model API key.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from .. import llm as llm_module
from ..agents import postings as postings_module
from ..agents import runner
from ..agents.graph import build_graph
from ..config import PROJECT_ROOT, get_settings
from ..db.models import AgentRun, CollectionRun, JobPosting
from ..db.session import session_scope
from . import views
from .jobs import JobManager

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


class NewPosting(BaseModel):
    text: str = Field(min_length=20)
    title: str = ""
    company: str = ""
    city: str = ""
    url: str = ""
    channel: str = ""


class RunOptions(BaseModel):
    force: bool = False
    auto_approve: bool = False


class ResumeBody(BaseModel):
    approve: bool | None = None


class CollectBody(BaseModel):
    mode: str = "auto"


def create_app(settings=None, toolkit=None, checkpointer_factory=None, collect_options=None, workers=2,
               serve_frontend=True):
    settings = settings or get_settings()
    toolkit = toolkit or runner.Toolkit(settings)
    url = toolkit.database_url
    manager = JobManager(settings, toolkit, checkpointer_factory or (lambda: runner.postgres_checkpointer(settings)),
                         collect_options, workers)

    @asynccontextmanager
    async def lifespan(app):
        yield
        manager.shutdown()

    app = FastAPI(title="cn-job-agent", version="0.3.0", lifespan=lifespan)
    app.state.manager = manager

    # ---------------------------------------------------------------- overview
    @app.get("/api/overview")
    def overview():
        with session_scope(url) as s:
            return views.overview(s)

    @app.get("/api/model")
    def model():
        try:
            resolved = llm_module.resolve(settings)
        except Exception as exc:  # noqa: BLE001 - shown in the UI
            return {"ok": False, "provider": settings.llm_provider, "error": str(exc)}
        return {"ok": True, "provider": resolved.provider, "label": resolved.label, "model": resolved.model,
                "host": resolved.host, "cloud": resolved.cloud, "privacy": resolved.privacy_note()}

    @app.get("/api/insights")
    def insights():
        with session_scope(url) as s:
            return views.insights(s)

    @app.get("/api/graph")
    def graph():
        """The compiled job graph's real topology, for the trace diagram."""
        drawn = build_graph(toolkit).get_graph()
        return {"nodes": [{"id": n} for n in drawn.nodes],
                "edges": [{"source": e.source, "target": e.target, "conditional": e.conditional} for e in drawn.edges]}

    # ---------------------------------------------------------------- postings
    @app.get("/api/postings")
    def list_postings(status: str | None = None, q: str | None = None, limit: int = Query(200, le=1000)):
        with session_scope(url) as s:
            query = select(JobPosting).order_by(JobPosting.id.desc()).limit(limit)
            if status:
                query = query.where(JobPosting.status == status)
            if q:
                like = f"%{q}%"
                query = query.where(or_(JobPosting.title.ilike(like), JobPosting.company_name.ilike(like),
                                        JobPosting.city.ilike(like)))
            return [views.posting_brief(p) for p in s.scalars(query)]

    @app.post("/api/postings", status_code=201)
    def add_posting(body: NewPosting):
        with session_scope(url) as s:
            try:
                posting, created = postings_module.add_posting(
                    s, body.text, source="web", title=body.title, company_name=body.company, city=body.city,
                    url=body.url, channel=body.channel if body.channel in ("campus", "social") else "")
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            return {"created": created, "posting": views.posting_brief(posting)}

    @app.get("/api/postings/{posting_id}")
    def get_posting(posting_id: int):
        with session_scope(url) as s:
            posting = s.get(JobPosting, posting_id)
            if posting is None:
                raise HTTPException(404, "没有这个岗位")
            profile = views.profile_dict(views.load_profile(s))
            latest = views.latest_run(posting)
            company = None
            if posting.company:
                company = {"key": posting.company.key, "name": posting.company.name, "portal": posting.company.portal,
                           "programs": [views.program_row(p, profile) for p in posting.company.programs]}
            return {**views.posting_brief(posting), "jd_text": posting.jd_text, "company_detail": company,
                    "runs": [views.run_brief(r) for r in sorted(posting.runs, key=lambda r: r.started_at,
                                                                  reverse=True)],
                    "latest": views.run_detail(latest) if latest else None}

    @app.post("/api/postings/{posting_id}/runs", status_code=202)
    def start_run(posting_id: int, body: RunOptions = RunOptions()):
        try:
            return {"run_id": manager.run_posting(posting_id, body.force, body.auto_approve)}
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    # ---------------------------------------------------------------- runs
    @app.get("/api/runs")
    def list_runs(limit: int = Query(50, le=500)):
        with session_scope(url) as s:
            runs = s.scalars(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit))
            return [{**views.run_brief(r), "posting_id": r.posting_id, "posting_title": r.posting.title} for r in runs]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        with session_scope(url) as s:
            run = s.get(AgentRun, run_id)
            if run is None:
                raise HTTPException(404, "没有这个运行")
            return views.run_detail(run)

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    def resume_run(run_id: str, body: ResumeBody):
        try:
            return {"run_id": manager.resume(run_id, body.approve)}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/runs/{run_id}/report", response_class=PlainTextResponse)
    def run_report(run_id: str):
        with session_scope(url) as s:
            run = s.get(AgentRun, run_id)
            path = Path(run.report_path) if run and run.report_path else None
        outputs = Path(toolkit.outputs_dir).resolve()      # reports are only served from here
        if path is None or not path.resolve().is_relative_to(outputs) or not path.is_file():
            raise HTTPException(404, "这个运行还没有报告")
        return path.read_text(encoding="utf-8")

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str, start: int = 0):
        return sse(run_id, start, lambda: _run_finished(run_id))

    def _run_finished(run_id):
        with session_scope(url) as s:
            run = s.get(AgentRun, run_id)
            return run is None or run.status != "running"

    # ---------------------------------------------------------------- materials (Chinese resume, greeting)
    MATERIAL_FILES = {"resume_zh.docx", "resume_zh.md", "greeting.txt"}

    @app.post("/api/runs/{run_id}/materials", status_code=202)
    def generate_materials(run_id: str):
        try:
            return {"job": manager.generate_materials(run_id)}
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/runs/{run_id}/materials")
    def get_materials(run_id: str):
        from ..agents import materials as materials_module
        folder = materials_module.latest(toolkit.outputs_dir, run_id)
        if folder is None:
            raise HTTPException(404, "还没有生成申请材料")
        data = json.loads((folder / "materials.json").read_text(encoding="utf-8"))
        data.pop("folder", None)                                  # no local paths in responses
        return {**data, "version": folder.name, "files": sorted(f.name for f in folder.iterdir()
                                                                 if f.name in MATERIAL_FILES)}

    @app.get("/api/runs/{run_id}/materials/{name}")
    def material_file(run_id: str, name: str):
        from ..agents import materials as materials_module
        folder = materials_module.latest(toolkit.outputs_dir, run_id)
        if folder is None or name not in MATERIAL_FILES or not (folder / name).is_file():
            raise HTTPException(404, "没有这个文件")
        return FileResponse(folder / name, filename=f"{run_id}-{name}")

    @app.get("/api/jobs/{key}/events")
    async def job_events(key: str, start: int = 0):
        return sse(key, start, lambda: True)

    # ---------------------------------------------------------------- collections
    @app.get("/api/collections")
    def list_collections(limit: int = Query(20, le=200)):
        with session_scope(url) as s:
            return [views.collection_brief(c) for c in
                    s.scalars(select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(limit))]

    @app.post("/api/collections", status_code=202)
    def start_collection(body: CollectBody):
        try:
            return {"collection_id": manager.start_collection(body.mode)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/collections/{collection_id}")
    def get_collection(collection_id: str):
        with session_scope(url) as s:
            run = s.get(CollectionRun, collection_id)
            if run is None:
                raise HTTPException(404, "没有这次采集")
            return views.collection_detail(run)

    @app.get("/api/collections/{collection_id}/events")
    async def collection_events(collection_id: str, start: int = 0):
        return sse(collection_id, start, lambda: True)

    # ---------------------------------------------------------------- companies
    @app.get("/api/companies")
    def list_companies(city: list[str] | None = Query(None), all: bool = False):
        with session_scope(url) as s:
            return views.companies(s, city, all)

    # ---------------------------------------------------------------- server-sent events
    def sse(key, start, finished_elsewhere):
        """Events of one run or collection. Work started by another process (the CLI)
        has no events here: the stream then just reports the end once it is over."""
        async def stream():
            index, idle = max(0, start), 0
            while True:
                events, finished = manager.events_since(key, index)
                for event in events:
                    index += 1
                    yield f"id: {index}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                if finished and not events:
                    break
                if not events and not manager.known(key) and await asyncio.to_thread(finished_elsewhere):
                    yield f"data: {json.dumps({'node': '__end__'})}\n\n"
                    break
                if not events:
                    idle += 1
                    if idle % 30 == 0:
                        yield ": keepalive\n\n"
                await asyncio.sleep(0.5)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------------------------------------------------------- React app
    if serve_frontend and (FRONTEND_DIST / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            file = (FRONTEND_DIST / path).resolve()
            if path and file.is_file() and file.is_relative_to(FRONTEND_DIST.resolve()):
                return FileResponse(file)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app
