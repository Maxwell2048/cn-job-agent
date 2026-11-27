"""Screening agent: should this JD go on to evidence matching?

Two independent passes, joined by `decide`:

1. `rule_flags`  deterministic checks over the JD text (experience years,
   degree, school tier, age, internship, languages, city, cohort window of a
   linked company). Each flag quotes the clause it came from, verbatim.
2. `extraction_flags`  a cross-check against what the extraction model
   found: an experience requirement with a years qualifier that the rules
   missed is escalated for review (never rejected on the model's word alone).

Severity: hard -> reject, soft -> human review, info -> shown only.
"""
import re
from datetime import date

from .. import eligibility, geo

HARD, SOFT, INFO = "hard", "soft", "info"
REJECT, REVIEW, PASS = "reject", "review", "pass"
SEVERITY_RANK = {HARD: 0, SOFT: 1, INFO: 2}

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
NUM = r"(\d+|[一二两三四五六七八九十]+)"
CLAUSE_SPLIT = re.compile(r"(?<=[，,。；;！!？?\n])")

EXP_WORD = re.compile(r"经验|从业|工作年限|experience", re.I)
EXP_RANGE = re.compile(NUM + r"\s*[-~～—至到]\s*" + NUM + r"\s*年")
EXP_MIN = re.compile(NUM + r"\s*(?:年\s*(?:及|或)?\s*以上|\+\s*年|年\s*\+)")
EXP_ATLEAST = re.compile(r"(?:至少|不少于|不低于)\s*" + NUM + r"\s*年")
# "5年左右JAVA 开发经验", "约3年": an approximate duration; 经验 may be further away
EXP_ABOUT = re.compile(NUM + r"\s*年\s*(?:左右|上下)|(?:约|大约|大概)\s*" + NUM + r"\s*年")
EXP_NEAR = re.compile(r"经验[^，。；\n]{0,4}?" + NUM + r"\s*年|" + NUM + r"\s*年[^，。；\n]{0,6}?经验")
EXP_MIN_EN = re.compile(r"(\d+)\s*\+?\s*(?:or more\s+)?years?", re.I)
EXP_ZERO = re.compile(r"经验不限|不限经验|无经验|零经验|接受应届|应届生|应届毕业生|在校生|无工作经验")
PREFERRED = re.compile(r"优先|加分|更佳|为佳|preferred|a plus|nice to have", re.I)
PHD = re.compile(r"博士")
MASTER = re.compile(r"硕士|研究生")
# "统招本科" means a full-time degree, not a school tier, so it is not listed here.
TIER = re.compile(r"985|211|双一流|C9|名校|重点(?:院校|大学)")
FIRST_DEGREE = re.compile(r"第一学历|本科(?:院校|阶段|学校)(?:须|需|必须|要求)?为?|本硕(?:均|都)")
QS = re.compile(r"QS\s*(?:世界)?(?:排名)?\s*(?:前|top)\s*(\d+)", re.I)
AGE = re.compile(r"(\d{2})\s*周?岁\s*(?:以下|以内|及以下)|年龄[^，。；\n]{0,8}?(?:不超过|不大于|小于|低于|≤|<)\s*(\d{2})")
MAX_YEARS = 20   # larger numbers next to 年 are calendar years or company age, not experience
COHORT = re.compile(r"(20\d{2})\s*届")
INTERN = re.compile(r"实习生|日常实习|暑期实习|实习岗|intern\b", re.I)
OTHER_LANG = re.compile(r"日语|韩语|德语|法语|西班牙语|俄语")
ENGLISH = re.compile(r"英语|英文|CET-?\s*[46]|雅思|IELTS|托福|TOEFL", re.I)
REMOTE = re.compile(r"远程|remote", re.I)


def cn_number(token):
    if token.isdigit():
        return int(token)
    if token == "十":
        return 10
    if "十" in token:
        tens, _, ones = token.partition("十")
        return (_CN_DIGITS.get(tens, 1) if tens else 1) * 10 + (_CN_DIGITS.get(ones, 0) if ones else 0)
    return _CN_DIGITS.get(token)


def clauses(text):
    """Clauses with their character offsets; quotes are verbatim slices."""
    out, start = [], 0
    for piece in CLAUSE_SPLIT.split(text):
        stripped = piece.strip()
        if stripped:
            offset = start + piece.index(stripped)
            out.append((offset, stripped.rstrip("，,。；;！!？?")))
        start += len(piece)
    return out


def flag(code, severity, message, quote=""):
    return {"code": code, "severity": severity, "message": message, "quote": quote}


def min_years(clause):
    """Smallest number of years of experience the clause asks for, or None."""
    if not EXP_WORD.search(clause):
        return None

    def numbers(pattern):
        found = []
        for match in pattern.finditer(clause):
            token = next((g for g in match.groups() if g), None)
            value = cn_number(token) if token else None
            if value is not None and value < MAX_YEARS:
                found.append(value)
        return found

    for pattern in (EXP_RANGE, EXP_MIN, EXP_ATLEAST, EXP_ABOUT, EXP_NEAR, EXP_MIN_EN):
        values = numbers(pattern)
        if values:
            return min(values)
    return None


def experience_flag(years, own, quote, source="规则"):
    preferred = bool(PREFERRED.search(quote))
    gap = years - own
    if gap <= 0:
        return flag("experience", INFO, f"要求 {years} 年经验，你有 {own} 年，满足", quote)
    if preferred:
        return flag("experience", INFO, f"{years} 年经验写的是优先条件（{source}）", quote)
    if gap >= 3:
        return flag("experience", HARD, f"硬性要求 {years} 年以上经验，你可计入的全职经验是 {own} 年（{source}）", quote)
    return flag("experience", SOFT, f"要求 {years} 年经验，你可计入的全职经验是 {own} 年；"
                                    f"中小公司常放宽，值得人工看一眼（{source}）", quote)


def age_at(birth, today):
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def rule_flags(posting, profile, company_programs=(), today=None):
    """Deterministic flags for one posting (dict) and profile (dict)."""
    today = today or date.today()
    text = posting["jd_text"]
    education = profile.get("education") or {}
    own_years = int(profile.get("experience_years") or 0)
    flags = []

    for _, clause in clauses(text):
        years = min_years(clause)
        if years is not None:
            flags.append(experience_flag(years, own_years, clause))
        if EXP_ZERO.search(clause):
            flags.append(flag("entry_level", INFO, "明确接收应届生或不限经验", clause))

        if PHD.search(clause) and not MASTER.search(clause) and re.search(r"学历|及以上|以上|要求|须|需", clause):
            severity = INFO if PREFERRED.search(clause) or education.get("degree") == "phd" else HARD
            flags.append(flag("degree", severity, "要求博士学历" if severity == HARD else "博士优先", clause))

        if TIER.search(clause):
            tier = education.get("undergrad_tier", "other")
            first_degree = bool(FIRST_DEGREE.search(clause))
            if PREFERRED.search(clause):
                flags.append(flag("school_tier", INFO, "985/211 等院校优先，不是硬门槛", clause))
            elif first_degree and tier == "other":
                flags.append(flag("school_tier", HARD, "第一学历（本科）要求 985/211 或双一流，你的本科不属于这类院校", clause))
            elif tier == "other":
                flags.append(flag("school_tier", SOFT, "提到 985/211 等院校要求，没写明是否看第一学历；"
                                                       "海外硕士是否被认可要问 HR", clause))
        for match in QS.finditer(clause):
            limit, rank = int(match[1]), education.get("qs_rank")
            if rank is None:
                flags.append(flag("qs_rank", SOFT, f"要求 QS 前 {limit}，画像里没有填学校排名", clause))
            elif rank > limit:
                flags.append(flag("qs_rank", SOFT if PREFERRED.search(clause) else HARD,
                                  f"要求 QS 前 {limit}，你的学校排名 {rank}", clause))
            else:
                flags.append(flag("qs_rank", INFO, f"要求 QS 前 {limit}，你的学校排名 {rank}，满足", clause))

        for match in AGE.finditer(clause):
            limit = int(match[1] or match[2])
            birth = profile.get("birth_date")
            if birth is None:
                flags.append(flag("age", SOFT, f"年龄上限 {limit} 岁；画像里没有出生日期，无法判断", clause))
            elif age_at(birth, today) > limit:
                flags.append(flag("age", HARD, f"年龄上限 {limit} 岁，你已超过", clause))
            else:
                flags.append(flag("age", INFO, f"年龄上限 {limit} 岁，满足", clause))

        if INTERN.search(clause):
            flags.append(flag("internship", SOFT, "这是实习岗；你已毕业，先确认对方是否接收已毕业的人", clause))
        if OTHER_LANG.search(clause) and not PREFERRED.search(clause):
            flags.append(flag("language", SOFT, "要求英语以外的外语", clause))
        elif ENGLISH.search(clause):
            flags.append(flag("english", INFO, "有英语要求或加分，你的英语是优势", clause))
        for match in COHORT.finditer(clause):
            flags.append(flag("cohort", INFO, f"注明 {match[1]} 届；以企业的毕业时间窗口为准", clause))

    flags.extend(city_flags(posting, profile))
    flags.extend(cohort_flags(posting, profile, company_programs))
    return dedupe(flags)


def city_flags(posting, profile):
    wanted = profile.get("cities") or []
    city = (posting.get("city") or "").strip()
    text = posting["jd_text"]
    if REMOTE.search(city) or (not city and REMOTE.search(text)):
        return [flag("city", INFO, "可远程办公")]
    if city:
        inside = [c for c in wanted if c in city]   # "深圳市南山区" contains "深圳"
        if inside:
            return [flag("city", INFO, f"工作城市 {city} 在你的目标城市里")]
        kind, matched = geo.match([city], wanted)
        if kind == geo.CITY:
            return [flag("city", INFO, f"工作城市 {city} 在你的目标城市里")]
        if kind:
            return [flag("city", SOFT, f"工作地写的是 {city}，可能不在你的目标城市（{'、'.join(matched)}）")]
        return [flag("city", SOFT, f"工作城市 {city} 不在你的目标城市（{'、'.join(wanted)}）里")]
    found = [c for c in wanted if c in text]
    if found:
        return [flag("city", INFO, f"JD 提到了你的目标城市：{'、'.join(found)}")]
    return [flag("city", SOFT, "JD 没写工作城市，投递前确认")]


def cohort_flags(posting, profile, company_programs):
    """For campus postings of a known company: the best cohort verdict of its programmes."""
    if posting.get("channel") != "campus" or not company_programs:
        return []
    verdicts = [(eligibility.ORDER.index(v.status), p, v)
                for p in company_programs for v in [eligibility.judge(p, profile)]]
    _, program, verdict = min(verdicts, key=lambda item: item[0])
    name = program.get("title") if isinstance(program, dict) else program.title
    message = f"{name}：{verdict.label}。{verdict.reason}"
    if verdict.status == eligibility.INELIGIBLE:
        return [flag("cohort_window", HARD, message)]
    if verdict.status in (eligibility.ELIGIBLE, eligibility.LIKELY):
        return [flag("cohort_window", INFO, message)]
    return [flag("cohort_window", SOFT, message)]


def extraction_flags(requirements, profile, rules):
    """Experience requirements the model found that the rules did not."""
    own = int(profile.get("experience_years") or 0)
    seen = {f["quote"] for f in rules if f["code"] == "experience"}
    out = []
    for requirement in requirements:
        if requirement.get("category") != "experience":
            continue
        quote = requirement.get("source_quote", "")
        if any(quote and (quote in s or s in quote) for s in seen):
            continue
        for qualifier in requirement.get("qualifiers", []):
            if qualifier.get("type") != "years":
                continue
            # A bare number ("5", "三") or a number with 年 ("3年", "两年以上");
            # "一定的经验" has 一 inside a word and is not a number of years.
            value = str(qualifier.get("value", "")).strip()
            match = re.fullmatch(NUM + r"\s*\+?", value) or re.search(NUM + r"\s*\+?\s*年", value) \
                or re.search(r"(\d+)\s*\+?\s*years?", value, re.I)
            years = cn_number(match[1]) if match else None
            if years is None or years <= own:
                continue
            found = experience_flag(years, own, quote, source="模型提取")
            if requirement.get("importance") == "preferred":
                found = flag("experience", INFO, f"{years} 年经验是优先条件（模型提取）", quote)
            elif found["severity"] == HARD:
                found["severity"] = SOFT   # the model alone never rejects a posting
            out.append(found)
    return out


def dedupe(flags):
    seen, out = set(), []
    for item in flags:
        key = (item["code"], item["severity"], item["message"], item["quote"])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def decide(flags):
    """reject when any hard flag, review when any soft flag, else pass."""
    severities = {f["severity"] for f in flags}
    if HARD in severities:
        return REJECT
    if SOFT in severities:
        return REVIEW
    return PASS


def sort_flags(flags):
    return sorted(flags, key=lambda f: SEVERITY_RANK[f["severity"]])
