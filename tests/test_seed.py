from datetime import date

import pytest
from pydantic import ValidationError

from cn_job_agent import eligibility as el
from cn_job_agent import geo
from cn_job_agent.config import PROJECT_ROOT
from cn_job_agent.seed.loader import ProfileIn, SeedFile, read_profile, read_seed

SEED = PROJECT_ROOT / "data" / "seed" / "campus_2027.yaml"
# The handbook's own verdicts were made for a testamur dated 2026-08.
HANDBOOK = {"testamur_month": date(2026, 8, 1), "cscse_cert_date": None}


@pytest.fixture(scope="module")
def seed():
    return read_seed(SEED)


def programs(seed):
    return {(c.key, p.key): p for c in seed.companies for p in c.programs}


def test_seed_parses_and_is_sizeable(seed):
    assert seed.checked_on == date(2026, 11, 21)
    assert len(seed.companies) >= 100
    assert len(programs(seed)) >= 70


def test_sources_are_links(seed):
    for program in programs(seed).values():
        for source in program.sources:
            assert source.url.startswith("https://"), source


@pytest.mark.parametrize("key, status", [
    (("tencent", "main"), el.ELIGIBLE),
    (("hikvision", "main"), el.ELIGIBLE),
    (("byd", "main"), el.ELIGIBLE),
    (("icbc", "main"), el.ELIGIBLE),
    (("vivo", "main"), el.BOUNDARY),
    (("cmbnt", "main"), el.BOUNDARY),
    (("transsion", "main"), el.BOUNDARY),
    (("vipshop", "main"), el.CONDITIONAL),
    (("china_mobile", "group"), el.LIKELY),
    (("china_tower", "main"), el.UNKNOWN),
    (("bytedance", "main"), el.INELIGIBLE),
    (("alibaba", "main"), el.INELIGIBLE),
    (("xiaohongshu", "regular"), el.INELIGIBLE),
    (("xiaohongshu", "redstar"), el.ELIGIBLE),
    (("psbc", "main"), el.INELIGIBLE),
])
def test_verdicts_agree_with_the_handbook(seed, key, status):
    p = programs(seed)[key]
    verdict = el.judge({"window_start": p.window_start, "window_end": p.window_end, "basis": p.basis,
                        "accepts_prior_unemployed": p.accepts_prior_unemployed}, HANDBOOK)
    assert verdict.status == status, verdict.reason


def test_invalid_seed_is_rejected():
    base = {"key": "x", "name": "X", "sector": "internet"}
    with pytest.raises(ValidationError):
        SeedFile.model_validate({"companies": [{**base, "sector": "retail"}]})
    with pytest.raises(ValidationError):
        SeedFile.model_validate({"companies": [base, base]})
    with pytest.raises(ValidationError):
        SeedFile.model_validate({"companies": [{**base, "programs": [{"window": ["2027-01", "2026-01"]}]}]})
    with pytest.raises(ValidationError):
        SeedFile.model_validate({"companies": [{**base, "programs": [{"basis": "birthday"}]}]})


def test_example_profile_is_valid():
    profile = read_profile(PROJECT_ROOT / "profile.example.yaml")
    assert profile.testamur_first_day == date(2025, 12, 1)
    assert {r.key for r in profile.roles} == {"agent_llm_app", "ai_fullstack_backend", "data", "support_solutions"}
    with pytest.raises(ValidationError):
        ProfileIn.model_validate({"roles": [], "cities": [], "channels": ["linkedin"]})


@pytest.mark.parametrize("cities, wanted, kind", [
    (["杭州", "武汉"], ["武汉"], geo.CITY),
    (["福建", "浙江", "湖北"], ["杭州"], geo.IN_PROVINCE),
    (["各省公司"], ["苏州"], geo.NATION),
    (["西安"], ["深圳"], None),
])
def test_city_match(cities, wanted, kind):
    assert geo.match(cities, wanted)[0] == kind


def test_unquoted_school_tier_is_accepted():
    profile = ProfileIn.model_validate({"roles": [], "cities": [], "channels": ["campus"],
                                        "education": {"degree": "master", "undergrad_tier": 211}})
    assert profile.education.undergrad_tier == "211"
