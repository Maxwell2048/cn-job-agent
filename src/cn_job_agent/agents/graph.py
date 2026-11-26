"""The job graph (LangGraph): screen a JD, then match it against the
experiences library requirement by requirement.

    START -> load_posting -+-> rule_screen --+-> decide --reject------------------------> finalize -> END
                           +-> extract ------+      |--review--> human_review --no------> finalize
                                                    |               |yes
                                                    +--pass---------+--Send x N--> match_one --> summarize -> finalize

- rule_screen (screening agent, no model) and extract (job_rag_starter's
  requirement extraction, local model) run in parallel and join at decide.
- human_review pauses the run with interrupt(); the run is checkpointed in
  PostgreSQL, so it can be resumed later from another process with
  `cn-agent run --resume <run_id> --approve|--decline`.
- match_one is fanned out with Send, one branch per requirement; branches
  run concurrently up to the run's max_concurrency.

    python -m cn_job_agent.agents.graph    # print the graph as Mermaid
"""
import json
import operator
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from sqlalchemy import delete, select

from .. import eligibility
from ..db.models import AgentRun, CampusProgram, JobPosting, RequirementMatch, SearchProfile
from ..db.session import session_scope
from . import matching, report, screening

GRAPH_VERSION = "2"
SCREENED_CATEGORIES = {"location"}   # handled by rule_screen, not sent to evidence matching
PROGRAM_FIELDS = ("title", "window_start", "window_end", "basis", "accepts_prior_unemployed", "status_text",
                  "deadline", "deadline_text", "cohort")
PROFILE_FIELDS = ("name", "roles", "cities", "channels", "testamur_month", "cscse_cert_date", "birth_date",
                  "experience_years", "education")
POSTING_FIELDS = ("id", "title", "company_name", "city", "url", "channel", "jd_text", "source")


class JobState(TypedDict, total=False):
    run_id: str
    posting_id: int
    options: dict                  # force, auto_approve
    posting: dict
    profile: dict
    company: dict | None
    rule_flags: list
    extraction: dict
    screening: dict
    approved: bool
    matches: Annotated[list, operator.add]
    summary: dict
    report_path: str
    trace: Annotated[list, operator.add]


class MatchTask(TypedDict):
    requirement: dict


def _timed(name, work):
    def run(state):
        started = time.time()
        update = work(state) or {}
        return {**update, "trace": [{"node": name, "seconds": round(time.time() - started, 2)}]}
    run.__name__ = name
    return run


def build_graph(toolkit, checkpointer=None):
    """Compile the graph. `toolkit` supplies the database URL, the local model,
    the requirement extractor and the evidence matcher (fakes in tests)."""
    url = toolkit.database_url

    def load_posting(state):
        with session_scope(url) as s:
            posting = s.get(JobPosting, state["posting_id"])
            if posting is None:
                raise ValueError(f"没有编号为 {state['posting_id']} 的岗位")
            profile = s.scalar(select(SearchProfile).where(SearchProfile.name == toolkit.profile_name))
            if profile is None:
                raise ValueError("数据库里还没有求职画像；先运行 cn-agent profile")
            profile_dict = {k: getattr(profile, k) for k in PROFILE_FIELDS}
            company = None
            if posting.company is not None:
                programs = s.scalars(select(CampusProgram).where(CampusProgram.company_id == posting.company_id)).all()
                company = {"key": posting.company.key, "name": posting.company.name, "programs": []}
                for p in programs:
                    verdict = eligibility.judge(p, profile_dict)
                    company["programs"].append({**{k: getattr(p, k) for k in PROGRAM_FIELDS},
                                                "verdict": verdict.status, "verdict_label": verdict.label,
                                                "verdict_reason": verdict.reason})
            return {"posting": {k: getattr(posting, k) for k in POSTING_FIELDS}, "profile": profile_dict,
                    "company": company}

    def rule_screen(state):
        programs = (state.get("company") or {}).get("programs", [])
        return {"rule_flags": screening.rule_flags(state["posting"], state["profile"], programs, toolkit.today())}

    def extract(state):
        result = toolkit.get_jd_parser().extract_requirements(state["posting"]["jd_text"], toolkit.get_llm())
        return {"extraction": result}

    def decide(state):
        extraction = state.get("extraction") or {}
        requirements = extraction.get("requirements", [])
        flags = screening.dedupe(state.get("rule_flags", [])
                                 + screening.extraction_flags(requirements, state["profile"], state.get("rule_flags", [])))
        decision = screening.decide(flags)
        if not requirements and extraction.get("failed_batches") and decision != screening.REJECT:
            decision = "error"
        return {"screening": {"decision": decision, "flags": screening.sort_flags(flags)}}

    def human_review(state):
        answer = interrupt({
            "question": "筛选发现需要你确认的条件，是否继续做证据匹配？",
            "flags": [f for f in state["screening"]["flags"] if f["severity"] in ("hard", "soft")],
        })
        return {"approved": bool(answer)}

    def fan_out(state):
        # Work location is the screening agent's job (city flags), not evidence in the experiences library.
        requirements = [r for r in state["extraction"].get("requirements", [])
                        if r.get("category") not in SCREENED_CATEGORIES]
        if not requirements:
            return "summarize"
        toolkit.get_matcher()   # build the shared matcher here, before branches run in parallel
        return [Send("match_one", {"requirement": r}) for r in requirements]

    def after_decide(state):
        decision = state["screening"]["decision"]
        force = state.get("options", {}).get("force")
        if decision == "error" or (decision == screening.REJECT and not force):
            return "finalize"
        if decision == screening.REVIEW and not state.get("options", {}).get("auto_approve"):
            return "human_review"
        return fan_out(state)

    def after_review(state):
        return fan_out(state) if state.get("approved") else "finalize"

    def match_one(task: MatchTask):
        started = time.time()
        result = toolkit.get_matcher().match_requirement(task["requirement"])
        return {"matches": [result], "trace": [{"node": "match_one", "requirement": result["requirement_id"],
                                                "seconds": round(time.time() - started, 2)}]}

    def summarize(state):
        return {"summary": matching.summarize(state.get("matches", []))}

    def finalize(state):
        # Not wrapped in _timed: the trace it saves must already contain its own entry.
        entry = {"node": "finalize", "seconds": 0.0}
        started = time.time()
        path = persist(toolkit, {**state, "trace": state.get("trace", []) + [entry]},
                       on_written=lambda: entry.update(seconds=round(time.time() - started, 2)))
        return {"report_path": path, "trace": [entry]}

    graph = StateGraph(JobState)
    for name, work in (("load_posting", load_posting), ("rule_screen", rule_screen), ("extract", extract),
                       ("decide", decide), ("human_review", human_review), ("summarize", summarize)):
        graph.add_node(name, _timed(name, work))
    graph.add_node("finalize", finalize)
    graph.add_node("match_one", match_one)
    graph.add_edge(START, "load_posting")
    graph.add_edge("load_posting", "rule_screen")
    graph.add_edge("load_posting", "extract")
    graph.add_edge(["rule_screen", "extract"], "decide")
    graph.add_conditional_edges("decide", after_decide, ["finalize", "human_review", "match_one", "summarize"])
    graph.add_conditional_edges("human_review", after_review, ["finalize", "match_one", "summarize"])
    graph.add_edge("match_one", "summarize")
    graph.add_edge("summarize", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def run_status(state):
    decision = state.get("screening", {}).get("decision")
    if decision == "error":
        return "failed"
    if "summary" in state:
        return "done"
    return "rejected"


def persist(toolkit, state, on_written=None):
    """Write the report files and the run's database rows; returns the report path.
    `on_written` runs after the files are written, before the rows are saved."""
    run_id = state["run_id"]
    status = run_status(state)
    matches = state.get("matches", [])
    summary = state.get("summary") or {}
    out_dir = Path(toolkit.outputs_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = report.render(run_id, state["posting"], state.get("screening", {}), state.get("company"),
                             state.get("extraction"), matches, summary, state.get("approved"))
    report_path = out_dir / "report.md"
    report_path.write_text(markdown, encoding="utf-8")
    result = {k: state.get(k) for k in ("run_id", "posting_id", "options", "company", "screening", "extraction",
                                        "approved", "summary", "trace")}
    result["matches"] = matches
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                                         encoding="utf-8")
    if on_written:
        on_written()

    with session_scope(toolkit.database_url) as s:
        run = s.get(AgentRun, run_id)
        run.status = status
        run.screening = state.get("screening", {})
        run.summary = summary
        run.trace = state.get("trace", [])
        run.report_path = str(report_path)
        run.versions = {**(run.versions or {}), **toolkit.versions()}
        run.finished_at = datetime.now(timezone.utc)
        s.execute(delete(RequirementMatch).where(RequirementMatch.run_id == run_id))
        for m in matches:
            s.add(RequirementMatch(run_id=run_id, requirement_id=m["requirement_id"], text=m["text"],
                                   category=m["category"], importance=m["importance"],
                                   source_quote=m.get("source_quote") or "", verdict=m.get("verdict"),
                                   processing_status=m.get("processing_status", ""), reason=m.get("reason", ""),
                                   evidence=m.get("evidence", []), missing_aspects=m.get("missing_aspects", []),
                                   questions_for_user=m.get("questions_for_user", []), errors=m.get("errors", [])))
        posting = s.get(JobPosting, state["posting_id"])
        posting.status = {"done": "matched", "rejected": "screened_out", "failed": "failed"}[status]
    return str(report_path)


if __name__ == "__main__":
    class _Offline:
        database_url = ""
    print(build_graph(_Offline()).get_graph().draw_mermaid())
