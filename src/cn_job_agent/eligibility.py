"""Campus-cohort eligibility: does the job seeker's degree date fall inside a
programme's published graduation window?

Overseas degrees are usually judged by the testamur date, which is known
only to the month, so a window that starts or ends in that same month is
reported as "boundary" (inside, but check the online form does not put you
in the month before or after).
"""
import calendar
import re
from dataclasses import dataclass
from datetime import date

ELIGIBLE, BOUNDARY, LIKELY, CONDITIONAL, UNKNOWN, INELIGIBLE = (
    "eligible", "boundary", "likely", "conditional", "unknown", "ineligible")
LABELS = {ELIGIBLE: "符合", BOUNDARY: "符合（卡在边界）", LIKELY: "大概率符合", CONDITIONAL: "有条件",
          UNKNOWN: "待核实", INELIGIBLE: "不符合"}
ORDER = [ELIGIBLE, BOUNDARY, LIKELY, CONDITIONAL, UNKNOWN, INELIGIBLE]


@dataclass(frozen=True)
class Verdict:
    status: str
    reason: str

    @property
    def label(self):
        return LABELS[self.status]


def parse_bound(value, end=False):
    """A window bound from the seed: None, a date, 'YYYY-MM' or 'YYYY-MM-DD'.
    A month-only start is the first day; a month-only end is the last day."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    match = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", str(value).strip())
    if not match:
        raise ValueError(f"无法识别的日期：{value!r}（应为 YYYY-MM 或 YYYY-MM-DD）")
    year, month = int(match[1]), int(match[2])
    if match[3]:
        return date(year, month, int(match[3]))
    return date(year, month, calendar.monthrange(year, month)[1] if end else 1)


def month_of(value):
    """(first day, last day) of the month a date or 'YYYY-MM' falls in."""
    first = parse_bound(value) if not isinstance(value, date) else value.replace(day=1)
    first = first.replace(day=1)
    return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])


def _fmt(value):
    return value.isoformat() if value else "未公布"


def judge_date(window_start, window_end, first, last, what="学位证"):
    """Compare a date known to lie within [first, last] with a window."""
    window = f"窗口 {_fmt(window_start)} 至 {_fmt(window_end)}"
    if window_start and last < window_start:
        return Verdict(INELIGIBLE, f"{what}日期 {first:%Y-%m} 早于{window}")
    if window_end and first > window_end:
        return Verdict(INELIGIBLE, f"{what}日期 {first:%Y-%m} 晚于{window}")
    if window_start is None:
        return Verdict(UNKNOWN, f"{window}：起点没公布，无法判断")
    edge = (window_start > first) or (window_end is not None and window_end < last) \
        or (window_start.replace(day=1) == first) or (window_end is not None and window_end.replace(day=1) == first)
    if edge:
        return Verdict(BOUNDARY, f"{what}月份 {first:%Y-%m} 正好在{window}的边界上；确认网申没有把你算到相邻月份")
    if window_end is None:
        return Verdict(LIKELY, f"{what}日期 {first:%Y-%m} 晚于窗口起点 {_fmt(window_start)}；终点没公布")
    return Verdict(ELIGIBLE, f"{what}日期 {first:%Y-%m} 在{window}内")


def judge(program, profile):
    """Verdict for one programme (a CampusProgram or a dict with the same fields)
    and one profile (testamur_month, cscse_cert_date)."""
    get = (lambda k: program.get(k)) if isinstance(program, dict) else (lambda k: getattr(program, k))
    pget = (lambda k: profile.get(k)) if isinstance(profile, dict) else (lambda k: getattr(profile, k))
    start, end, basis = get("window_start"), get("window_end"), get("basis") or "testamur"
    prior = bool(get("accepts_prior_unemployed"))

    if basis == "cscse_cert":
        cert = pget("cscse_cert_date")
        if cert is None:
            return Verdict(CONDITIONAL, f"按留服认证日期认定：认证日期需落在窗口 {_fmt(start)} 至 {_fmt(end)} 内")
        return judge_date(start, end, cert, cert, "留服认证")

    if start is None and end is None:
        if prior:
            return Verdict(LIKELY, "窗口未写日期，但明文接收上一届未就业毕业生")
        return Verdict(UNKNOWN, "窗口没有公布日期")

    testamur = pget("testamur_month")
    if testamur is None:
        return Verdict(UNKNOWN, "求职画像里没有学位证月份")
    first, last = month_of(testamur)
    verdict = judge_date(start, end, first, last)
    if verdict.status == INELIGIBLE and prior:
        return Verdict(LIKELY, verdict.reason + "；但接收上一届未就业毕业生")
    if basis == "graduation_cert" and verdict.status in (ELIGIBLE, BOUNDARY, LIKELY):
        return Verdict(verdict.status, verdict.reason + "（该单位写的是毕业证日期，海外学历一般按学位证）")
    if basis == "unknown" and verdict.status in (ELIGIBLE, BOUNDARY, LIKELY):
        return Verdict(verdict.status, verdict.reason + "（未写明按哪个日期认定）")
    return verdict
