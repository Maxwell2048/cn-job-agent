"""Database rows as JSON for the web UI. Nothing here returns secrets: the model
section names the provider, model and data destination, never the API key."""
from sqlalchemy import func, select

from .. import eligibility, geo
from ..db.models import AgentRun, CampusProgram, CollectionRun, Company, JobPosting, RequirementMatch, SearchProfile


def iso(value):
    return value.isoformat() if value else None


def latest_run(posting):
    """The newest run that did not fail, else the newest run."""
    runs = sorted(posting.runs, key=lambda r: r.started_at, reverse=True)
    return next((r for r in runs if r.status != "failed"), runs[0] if runs else None)


def run_brief(run):
    if run is None:
        return None
    summary = run.summary or {}
    return {"id": run.id, "status": run.status, "decision": (run.screening or {}).get("decision"),
            "score": summary.get("score"), "label": summary.get("label"),
            "required_covered": summary.get("required_covered"), "required_total": summary.get("required_total"),
            "counts": summary.get("counts"), "started_at": iso(run.started_at), "finished_at": iso(run.finished_at)}


def posting_brief(posting):
    return {"id": posting.id, "title": posting.title, "company": posting.company.name if posting.company else
            posting.company_name, "company_key": posting.company.key if posting.company else None,
            "city": posting.city, "channel": posting.channel, "source": posting.source, "url": posting.url,
            "status": posting.status, "posted_at": posting.posted_at, "created_at": iso(posting.created_at),
            "latest_run": run_brief(latest_run(posting))}


def match_row(m):
    return {"requirement_id": m.requirement_id, "text": m.text, "category": m.category, "importance": m.importance,
            "source_quote": m.source_quote, "verdict": m.verdict, "processing_status": m.processing_status,
            "reason": m.reason, "evidence": m.evidence, "missing_aspects": m.missing_aspects,
            "questions_for_user": m.questions_for_user, "errors": m.errors}


def run_detail(run):
    return {**run_brief(run), "posting_id": run.posting_id, "posting_title": run.posting.title,
            "screening": run.screening or {}, "summary": run.summary or {}, "trace": run.trace or [],
            "versions": run.versions or {}, "error": run.error, "has_report": bool(run.report_path),
            "matches": [match_row(m) for m in run.matches]}


def program_row(program, profile):
    verdict = eligibility.judge(program, profile) if profile else None
    return {"title": program.title, "window_start": iso(program.window_start), "window_end": iso(program.window_end),
            "window_text": program.window_text, "basis": program.basis, "status_text": program.status_text,
            "deadline": iso(program.deadline), "deadline_text": program.deadline_text, "roles": program.roles,
            "cities": program.cities, "requirements": program.requirements, "apply_limit": program.apply_limit,
            "confidence": program.confidence, "sources": program.sources,
            "verdict": verdict.status if verdict else None, "verdict_label": verdict.label if verdict else None,
            "verdict_reason": verdict.reason if verdict else None}


def profile_dict(row):
    if row is None:
        return None
    return {"name": row.name, "roles": row.roles, "cities": row.cities, "channels": row.channels,
            "testamur_month": row.testamur_month, "cscse_cert_date": row.cscse_cert_date,
            "birth_date": row.birth_date, "experience_years": row.experience_years, "education": row.education}


def load_profile(session, name="default"):
    return session.scalar(select(SearchProfile).where(SearchProfile.name == name))


def profile_public(row):
    """The profile for display: roles, cities, channels. Dates stay server-side."""
    if row is None:
        return None
    return {"roles": row.roles, "cities": row.cities, "channels": row.channels}


def companies(session, cities=None, include_all=False):
    row = load_profile(session)
    profile = profile_dict(row)
    wanted = cities or (row.cities if row else [])
    out = []
    for company in session.scalars(select(Company).order_by(Company.sector, Company.name)):
        programs = []
        for program in company.programs:
            kind, matched = geo.match(program.cities, wanted)
            item = {**program_row(program, profile), "city_match": kind, "matched_cities": matched}
            if include_all or (kind and item["verdict"] != eligibility.INELIGIBLE):
                programs.append(item)
        if programs or (include_all and not company.programs):
            out.append({"key": company.key, "name": company.name, "sector": company.sector, "portal": company.portal,
                        "note": company.note, "programs": programs})
    return out


def overview(session):
    by_status = dict(session.execute(select(JobPosting.status, func.count()).group_by(JobPosting.status)).all())
    runs_by_status = dict(session.execute(select(AgentRun.status, func.count()).group_by(AgentRun.status)).all())
    recent = session.scalars(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(8)).all()
    collections = session.scalars(select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(3)).all()
    return {"postings": by_status, "runs": runs_by_status,
            "companies": session.scalar(select(func.count()).select_from(Company)),
            "programs": session.scalar(select(func.count()).select_from(CampusProgram)),
            "profile": profile_public(load_profile(session)),
            "recent_runs": [{**run_brief(r), "posting_id": r.posting_id, "posting_title": r.posting.title}
                            for r in recent],
            "recent_collections": [collection_brief(c) for c in collections]}


def collection_brief(run):
    return {"id": run.id, "mode": run.mode, "status": run.status, "stats": {k: v for k, v in (run.stats or {}).items()
                                                                              if k != "saved_ids"},
            "started_at": iso(run.started_at), "finished_at": iso(run.finished_at), "error": run.error}


def collection_detail(run):
    return {**collection_brief(run), "plan": run.plan or [], "trace": run.trace or [],
            "saved": (run.stats or {}).get("saved_ids", [])}


def insights(session):
    """Across every judged requirement: verdicts by category, and the requirements
    most often without evidence (what to work on next)."""
    rows = session.execute(select(RequirementMatch.category, RequirementMatch.verdict, func.count())
                           .group_by(RequirementMatch.category, RequirementMatch.verdict)).all()
    by_category = {}
    for category, verdict, count in rows:
        by_category.setdefault(category, {})[verdict or "error"] = count
    gaps = session.execute(
        select(RequirementMatch.text, func.count().label("n"))
        .where(RequirementMatch.verdict == "insufficient", RequirementMatch.importance != "preferred",
               RequirementMatch.category != "responsibility")
        .group_by(RequirementMatch.text).order_by(func.count().desc(), RequirementMatch.text).limit(15)).all()
    return {"by_category": by_category, "top_gaps": [{"text": t, "count": n} for t, n in gaps]}
