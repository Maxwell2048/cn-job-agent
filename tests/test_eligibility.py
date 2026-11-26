from datetime import date

import pytest

from cn_job_agent import eligibility as el
from cn_job_agent.eligibility import judge, month_of, parse_bound


def program(start=None, end=None, basis="testamur", prior=False):
    return {"window_start": parse_bound(start), "window_end": parse_bound(end, end=True),
            "basis": basis, "accepts_prior_unemployed": prior}


PROFILE = {"testamur_month": date(2026, 8, 1), "cscse_cert_date": None}


def test_parse_bound_month_and_day():
    assert parse_bound("2026-01") == date(2026, 1, 1)
    assert parse_bound("2027-02", end=True) == date(2027, 2, 28)
    assert parse_bound("2026-07-15", end=True) == date(2026, 7, 15)
    assert parse_bound(date(2026, 1, 1)) == date(2026, 1, 1)
    assert parse_bound(None) is None
    with pytest.raises(ValueError):
        parse_bound("2026/01")


def test_month_of():
    assert month_of("2026-08") == (date(2026, 8, 1), date(2026, 8, 31))


@pytest.mark.parametrize("window, status", [
    (("2026-01-01", "2027-12-31"), el.ELIGIBLE),        # Tencent
    (("2026-08", "2027-07"), el.BOUNDARY),              # vivo: starts in the testamur month
    (("2026-08-01", "2027-07-31"), el.BOUNDARY),        # 招银网络科技
    (("2026-08-15", "2027-07-31"), el.BOUNDARY),        # starts mid-month
    (("2026-09", None), el.INELIGIBLE),                 # ByteDance
    (("2026-11", "2027-10"), el.INELIGIBLE),            # Alibaba
    (("2027-01", "2027-12"), el.INELIGIBLE),            # 2027 graduates only
    (("2025-01-01", "2026-07-31"), el.INELIGIBLE),      # closed before the degree
    (("2026-01", None), el.LIKELY),                     # end not published
    ((None, "2027-12-31"), el.UNKNOWN),                 # 中国铁塔: no lower bound
    ((None, None), el.UNKNOWN),
])
def test_testamur_windows(window, status):
    assert judge(program(*window), PROFILE).status == status


def test_prior_cohort_rule_rescues_missing_or_late_window():
    assert judge(program(prior=True), PROFILE).status == el.LIKELY
    assert judge(program("2026-09", "2027-08", prior=True), PROFILE).status == el.LIKELY


def test_cscse_basis_needs_the_certificate_date():
    vipshop = program("2026-07-01", "2027-06-30", basis="cscse_cert")
    assert judge(vipshop, PROFILE).status == el.CONDITIONAL
    assert judge(vipshop, {**PROFILE, "cscse_cert_date": date(2027, 1, 10)}).status == el.ELIGIBLE
    assert judge(vipshop, {**PROFILE, "cscse_cert_date": date(2027, 7, 2)}).status == el.INELIGIBLE


def test_missing_testamur_is_unknown():
    assert judge(program("2026-01", "2027-12"), {"testamur_month": None, "cscse_cert_date": None}).status \
        == el.UNKNOWN


def test_basis_caveats_are_reported():
    assert "毕业证" in judge(program("2026-07-01", "2027-06-30", basis="graduation_cert"), PROFILE).reason
    assert "未写明" in judge(program("2026-01", "2027-12", basis="unknown"), PROFILE).reason
