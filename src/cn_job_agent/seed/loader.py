"""Load the campus-recruiting seed file and the search profile into the database.

Both loads are idempotent upserts keyed by company key / programme key /
profile name, so re-running after editing the YAML updates rows in place and
removes programmes deleted from the file.
"""
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select

from ..db.models import CampusProgram, Company, SearchProfile
from ..eligibility import parse_bound

SECTORS = {"internet", "hardware", "bank", "soe", "foreign"}
BASES = {"testamur", "cscse_cert", "graduation_cert", "unknown"}
CONFIDENCE = {"official", "third_party", "mixed", "unverified"}
CHANNELS = {"campus", "social_entry", "foreign_global"}


class Source(BaseModel):
    label: str
    url: str


class ProgramIn(BaseModel):
    key: str = "main"
    title: str = ""
    cohort: str = "2027"
    window: list | None = None
    window_text: str = ""
    basis: str = "testamur"
    accepts_prior_unemployed: bool = False
    status: str = ""
    deadline: date | None = None
    deadline_text: str = ""
    roles: list[str] = Field(default_factory=list)
    cities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    apply_limit: str = ""
    confidence: str = "unverified"
    sources: list[Source] = Field(default_factory=list)

    @field_validator("basis")
    @classmethod
    def _basis(cls, value):
        if value not in BASES:
            raise ValueError(f"basis 必须是 {sorted(BASES)} 之一")
        return value

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, value):
        if value not in CONFIDENCE:
            raise ValueError(f"confidence 必须是 {sorted(CONFIDENCE)} 之一")
        return value

    @model_validator(mode="after")
    def _window(self):
        if self.window is not None:
            if len(self.window) != 2:
                raise ValueError("window 必须是 [起, 止] 或 null")
            start, end = parse_bound(self.window[0]), parse_bound(self.window[1], end=True)
            if start and end and start > end:
                raise ValueError(f"window 起点 {start} 晚于终点 {end}")
        return self

    @property
    def window_start(self):
        return parse_bound(self.window[0]) if self.window else None

    @property
    def window_end(self):
        return parse_bound(self.window[1], end=True) if self.window else None


class CompanyIn(BaseModel):
    key: str
    name: str
    sector: str
    portal: str = ""
    note: str = ""
    programs: list[ProgramIn] = Field(default_factory=list)

    @field_validator("sector")
    @classmethod
    def _sector(cls, value):
        if value not in SECTORS:
            raise ValueError(f"sector 必须是 {sorted(SECTORS)} 之一")
        return value

    @model_validator(mode="after")
    def _unique_programs(self):
        keys = [p.key for p in self.programs]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{self.key} 的 programs key 重复：{keys}")
        return self


class SeedFile(BaseModel):
    source_doc: str = ""
    checked_on: date | None = None
    companies: list[CompanyIn]

    @model_validator(mode="after")
    def _unique_companies(self):
        seen = set()
        for company in self.companies:
            if company.key in seen:
                raise ValueError(f"公司 key 重复：{company.key}")
            seen.add(company.key)
        return self


class RoleIn(BaseModel):
    key: str
    label: str
    keywords: list[str] = Field(default_factory=list)


class EducationIn(BaseModel):
    degree: str = "bachelor"                 # bachelor | master | phd
    undergrad_tier: str = "other"            # 985 | 211 | double_first_class | other
    qs_rank: int | None = None               # QS rank of the highest-degree university

    @field_validator("degree")
    @classmethod
    def _degree(cls, value):
        if value not in {"bachelor", "master", "phd"}:
            raise ValueError("degree 必须是 bachelor、master 或 phd")
        return value

    @field_validator("undergrad_tier", mode="before")
    @classmethod
    def _tier_text(cls, value):
        return str(value)          # YAML reads an unquoted 985 / 211 as a number

    @field_validator("undergrad_tier")
    @classmethod
    def _tier(cls, value):
        if value not in {"985", "211", "double_first_class", "other"}:
            raise ValueError("undergrad_tier 必须是 985、211、double_first_class 或 other")
        return value


class ProfileIn(BaseModel):
    name: str = "default"
    roles: list[RoleIn]
    cities: list[str]
    channels: list[str]
    testamur_month: str | date | None = None
    cscse_cert_date: date | None = None
    birth_date: date | None = None
    experience_years: int = 0
    education: EducationIn = Field(default_factory=EducationIn)

    @field_validator("channels")
    @classmethod
    def _channels(cls, value):
        unknown = set(value) - CHANNELS
        if unknown:
            raise ValueError(f"未知渠道 {sorted(unknown)}；可用 {sorted(CHANNELS)}")
        return value

    @property
    def testamur_first_day(self):
        return parse_bound(self.testamur_month).replace(day=1) if self.testamur_month else None


def read_seed(path: Path) -> SeedFile:
    return SeedFile.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def read_profile(path: Path) -> ProfileIn:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到求职画像 {path}；复制 profile.example.yaml 为 profile.local.yaml 再填写")
    return ProfileIn.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_seed(session, seed: SeedFile):
    """Upsert companies and programmes. Returns counts."""
    counts = {"companies": 0, "programs": 0, "programs_removed": 0}
    existing = {c.key: c for c in session.scalars(select(Company))}
    for item in seed.companies:
        company = existing.get(item.key) or Company(key=item.key)
        company.name, company.sector, company.portal, company.note = item.name, item.sector, item.portal, item.note
        session.add(company)
        current = {p.key: p for p in company.programs}
        wanted = set()
        for p in item.programs:
            program = current.get(p.key) or CampusProgram(key=p.key)
            if p.key not in current:
                company.programs.append(program)
            program.title, program.cohort = p.title, p.cohort
            program.window_start, program.window_end, program.window_text = p.window_start, p.window_end, p.window_text
            program.basis, program.accepts_prior_unemployed = p.basis, p.accepts_prior_unemployed
            program.status_text, program.deadline, program.deadline_text = p.status, p.deadline, p.deadline_text
            program.roles, program.cities, program.requirements = p.roles, p.cities, p.requirements
            program.apply_limit, program.confidence = p.apply_limit, p.confidence
            program.sources = [s.model_dump() for s in p.sources]
            program.checked_on = seed.checked_on
            wanted.add(p.key)
            counts["programs"] += 1
        for key, program in current.items():
            if key not in wanted:
                company.programs.remove(program)
                counts["programs_removed"] += 1
        counts["companies"] += 1
    session.flush()
    return counts


def load_profile(session, profile: ProfileIn):
    row = session.scalar(select(SearchProfile).where(SearchProfile.name == profile.name)) \
        or SearchProfile(name=profile.name)
    row.roles = [r.model_dump() for r in profile.roles]
    row.cities, row.channels = profile.cities, profile.channels
    row.testamur_month = profile.testamur_first_day
    row.cscse_cert_date, row.birth_date = profile.cscse_cert_date, profile.birth_date
    row.experience_years, row.education = profile.experience_years, profile.education.model_dump()
    session.add(row)
    session.flush()
    return row
