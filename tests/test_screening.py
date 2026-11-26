from datetime import date

import pytest

from cn_job_agent.agents import postings, screening
from cn_job_agent.agents.screening import HARD, INFO, SOFT, decide, min_years, rule_flags

PROFILE = {"cities": ["苏州", "武汉", "深圳", "杭州"], "experience_years": 0, "birth_date": None,
           "testamur_month": date(2026, 8, 1), "cscse_cert_date": None,
           "education": {"degree": "master", "undergrad_tier": "other", "qs_rank": 77}}


def flags_for(text, city="深圳", channel="social", profile=PROFILE, programs=()):
    return rule_flags({"jd_text": text, "city": city, "channel": channel}, profile, programs, date(2026, 11, 26))


def codes(flags, severity):
    return {f["code"] for f in flags if f["severity"] == severity}


@pytest.mark.parametrize("clause, years", [
    ("3年以上Python开发经验", 3),
    ("1-3年工作经验", 1),
    ("具备两年以上相关经验", 2),
    ("至少5年后端开发经验", 5),
    ("工作经验：3年", 3),
    ("3+ years of experience with Python", 3),
    ("熟悉 Python 和 SQL", None),
    ("2027年毕业，工作地点深圳", None),           # a calendar year, no 经验
    ("公司成立于2015年，经验丰富的团队", None),     # 2015 is not a number of years
])
def test_min_years(clause, years):
    assert min_years(clause) == years


def test_experience_severity_scales_with_the_gap():
    assert "experience" in codes(flags_for("要求：5年以上Java开发经验。"), HARD)
    assert "experience" in codes(flags_for("要求：1-3年工作经验。"), SOFT)
    assert "experience" in codes(flags_for("3年以上大模型应用经验者优先。"), INFO)
    assert "entry_level" in codes(flags_for("经验不限，接受应届生。"), INFO)


def test_degree_and_school_tier():
    assert "degree" in codes(flags_for("博士及以上学历。"), HARD)
    assert "degree" not in codes(flags_for("硕士或博士学历。"), HARD)
    assert "school_tier" in codes(flags_for("第一学历为985/211院校。"), HARD)
    assert "school_tier" in codes(flags_for("985/211院校硕士。"), SOFT)
    assert "school_tier" in codes(flags_for("985/211院校优先。"), INFO)
    # 统招本科 is a full-time degree requirement, not a school tier
    assert not [f for f in flags_for("统招本科及以上学历。") if f["code"] == "school_tier"]
    assert "qs_rank" in codes(flags_for("海外院校需QS前100。"), INFO)
    assert "qs_rank" in codes(flags_for("海外院校需QS前50。"), HARD)


def test_age_internship_language_city():
    assert "age" in codes(flags_for("年龄35岁以下。"), SOFT)              # no birth date in the profile
    old = {**PROFILE, "birth_date": date(1990, 1, 1)}
    assert "age" in codes(flags_for("年龄35岁以下。", profile=old), HARD)
    assert "internship" in codes(flags_for("招聘日常实习生。"), SOFT)
    assert "language" in codes(flags_for("要求日语N1。"), SOFT)
    assert "english" in codes(flags_for("英语CET-6。"), INFO)
    assert "city" in codes(flags_for("熟悉 Python。", city="深圳市南山区"), INFO)
    assert "city" in codes(flags_for("熟悉 Python。", city="北京"), SOFT)
    assert "city" in codes(flags_for("可远程办公。", city=""), INFO)


def test_quotes_are_verbatim_clauses():
    text = "岗位要求：\n1. 3年以上Python开发经验；\n2. 本科及以上学历。\n"
    for f in flags_for(text):
        assert f["quote"] == "" or f["quote"] in text


def test_cohort_window_of_a_linked_company():
    late = [{"title": "2027 校招", "window_start": date(2026, 9, 1), "window_end": None, "basis": "testamur",
             "accepts_prior_unemployed": False}]
    ok = [{"title": "2027 校招", "window_start": date(2026, 1, 1), "window_end": date(2027, 12, 31),
           "basis": "testamur", "accepts_prior_unemployed": False}]
    assert "cohort_window" in codes(flags_for("2027届校招。", channel="campus", programs=late), HARD)
    assert "cohort_window" in codes(flags_for("2027届校招。", channel="campus", programs=ok), INFO)
    assert not [f for f in flags_for("社招。", channel="social", programs=late) if f["code"] == "cohort_window"]


def test_extraction_cross_check_never_rejects():
    requirement = {"category": "experience", "importance": "required", "source_quote": "five years in industry",
                   "qualifiers": [{"type": "years", "value": "5", "source_quote": "five years"}]}
    [found] = screening.extraction_flags([requirement], PROFILE, [])
    assert found["severity"] == SOFT


def test_decide():
    assert decide([{"severity": INFO}]) == "pass"
    assert decide([{"severity": INFO}, {"severity": SOFT}]) == "review"
    assert decide([{"severity": SOFT}, {"severity": HARD}]) == "reject"


def test_posting_helpers():
    assert postings.infer_channel("2027届校园招聘") == "campus"
    assert postings.infer_channel("社招 3年以上经验") == "social"
    assert postings.infer_channel("熟悉 Python") == "unknown"
    assert postings.infer_title("\n\n## AI Agent 开发工程师\n职责") == "AI Agent 开发工程师"
    assert postings.normalize("﻿a\r\nb") == "a\nb\n"


@pytest.mark.parametrize("title, hits", [
    ("RAG 应用工程师", ["RAG"]),
    ("Storage Engineer", []),                    # "rag" inside "storage" is not RAG
    ("Mobile 开发", []),                          # "bi" inside "mobile" is not BI
    ("BI 数据分析师", ["BI", "数据分析"]),
    ("AI全栈工程师", ["全栈"]),
])
def test_planner_keyword_match(title, hits):
    from cn_job_agent.agents.planner import matched_keywords
    assert matched_keywords(title, ["RAG", "BI", "数据分析", "全栈"]) == hits
