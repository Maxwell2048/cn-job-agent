"""JD intake: save a pasted / file / clipboard JD as a job posting, link it to a
known company and infer the hiring channel when the user did not give one."""
import hashlib
import re

from sqlalchemy import select

from ..db.models import Company, JobPosting

CAMPUS = re.compile(r"校招|校园招聘|应届|20\d{2}\s*届|管培生|毕业生|春招|秋招|补录")
SOCIAL = re.compile(r"社招|社会招聘|\d+\s*[-~～至到]?\s*\d*\s*年(?:以上|及以上)?[^，。；\n]{0,8}经验")


def normalize(text):
    """Same normalization as job_rag_starter's jd_parser.normalize_jd (BOM, newlines)."""
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def infer_title(text):
    for line in text.splitlines():
        line = line.strip(" #*\t")
        if line:
            return line[:120]
    return ""


def infer_channel(text):
    if CAMPUS.search(text):
        return "campus"
    if SOCIAL.search(text):
        return "social"
    return "unknown"


def _base_names(company):
    """Names a JD might use for this company: the name without its bracketed
    note, and each part of a "A/B" or "A（B、C）" style name."""
    names = {company.name}
    head = re.split(r"[（(]", company.name)[0].strip()
    if head:
        names.add(head)
    inner = re.findall(r"[（(]([^）)]+)[）)]", company.name)
    for part in inner:
        names.update(p.strip() for p in re.split(r"[、,/，]", part) if len(p.strip()) >= 2)
    for part in re.split(r"[/]", head):
        if len(part.strip()) >= 2:
            names.add(part.strip())
    return {n for n in names if len(n) >= 2}


def link_company(session, company_name, jd_text=""):
    """The known company whose name appears in the given company name (or, when
    that is empty, in the first lines of the JD). Longest match wins, so
    "腾讯音乐" beats "腾讯"."""
    haystack = company_name.strip() or "\n".join(jd_text.splitlines()[:5])
    if not haystack:
        return None
    best, best_len = None, 0
    for company in session.scalars(select(Company)):
        for name in _base_names(company):
            if name in haystack and len(name) > best_len:
                best, best_len = company, len(name)
    return best


def add_posting(session, text, source="manual", title="", company_name="", city="", url="", channel="",
                external_id=None, posted_at="", company_key=None, collection_run_id=None):
    """Save a JD. Returns (posting, created). The same site id from the same
    source, or an identical JD text, returns the existing row."""
    text = normalize(text)
    if not text.strip():
        raise ValueError("JD 文本为空")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if external_id:
        existing = session.scalar(select(JobPosting).where(JobPosting.source == source,
                                                           JobPosting.external_id == external_id))
        if existing:
            return existing, False
    existing = session.scalar(select(JobPosting).where(JobPosting.jd_sha256 == digest))
    if existing:
        return existing, False
    company = session.scalar(select(Company).where(Company.key == company_key)) if company_key else None
    company = company or link_company(session, company_name, text)
    posting = JobPosting(source=source, external_id=external_id, posted_at=posted_at,
                         collection_run_id=collection_run_id, title=title or infer_title(text),
                         company_name=company_name, company=company, city=city, url=url,
                         channel=channel or infer_channel(text), jd_text=text, jd_sha256=digest)
    session.add(posting)
    session.flush()
    return posting, True
