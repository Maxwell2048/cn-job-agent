"""把抓回来的原始岗位文本，压成能比较的结构化字段。

抓取层尽量只负责"拿到原文"，所有需要判断的地方集中在这里，好处是：
同一个 JD 无论来自 zhiye、Atom 还是浏览器，入库后字段口径完全一致；
规则改动不需要重新抓，只需要对库里已有行重算（`cn-agent pool renormalize`）。

覆盖四件事：
  薪资   "20-40K·14薪" / "1.5-2.5万" / "8000-12000元/月" / "300-500元/天" / "年薪30-60万"
  年限   "3-5年" / "应届毕业生" / "1年以内" / "5年以上" / "经验不限"
  学历   "本科及以上" / "大专" / "硕士" / "学历不限"（rank 越大门槛越高）
  城市   "北京市·朝阳区" / "上海-浦东新区" / "深圳" -> 标准城市名
另外从 JD 里抽技能词典命中项，用于算技能覆盖率和缺口。

时间/薪资一律不带单位歧义：薪资内部统一为"千元/月"，年薪和日薪先折算再存，
折算口径写在每个函数的 docstring 里，方便以后改。
"""
import re
import unicodedata
from dataclasses import dataclass, field

# ----------------------------------------------------------------- salary
_MONTHS_SUFFIX = re.compile(r"(\d{2})\s*薪")
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|~|～|—|到|至)\s*(\d+(?:\.\d+)?)")
_SINGLE = re.compile(r"(\d+(?:\.\d+)?)")
_UNIT = re.compile(r"(万|w|W|千|k|K|元)")
_YEAR_WORD = re.compile(r"年薪|年包|年度")
_DAY_WORD = re.compile(r"/\s*天|元\s*/\s*天|日薪|每天")
_HOUR_WORD = re.compile(r"/\s*小时|时薪|每小时")
_NEGOTIABLE = ("面议", "面谈", "薪资面议", "待遇面议", "详谈", "保密")

# 每月工作日（折算日薪用），国内招聘口径通常按 21.75 天
WORKDAYS_PER_MONTH = 21.75

# 每个单位折算到"千元"的系数（月薪口径）
_UNIT_TO_K = {"万": 10.0, "w": 10.0, "W": 10.0, "千": 1.0, "k": 1.0, "K": 1.0, "元": 0.001}


@dataclass(frozen=True)
class Salary:
    raw: str = ""
    min_k: float | None = None        # 千元/月
    max_k: float | None = None
    months: int = 12                  # 一年发几个月
    unit: str = ""                    # month | year | day | hour | unknown

    @property
    def is_known(self):
        return self.min_k is not None

    @property
    def annual_min_wan(self):
        """保底年薪（万元），用来比较"14薪 vs 16薪"这种差别。"""
        return None if self.min_k is None else round(self.min_k * self.months / 10, 1)

    @property
    def annual_max_wan(self):
        return None if self.max_k is None else round(self.max_k * self.months / 10, 1)

    def as_dict(self):
        return {"raw": self.raw, "min_k": self.min_k, "max_k": self.max_k, "months": self.months,
                "unit": self.unit, "annual_min_wan": self.annual_min_wan,
                "annual_max_wan": self.annual_max_wan}


def _scale(numbers, factor):
    return [round(n * factor, 2) for n in numbers]


def parse_salary(text):
    """"20-40K·14薪" -> Salary(min_k=20, max_k=40, months=14, unit="month").

    没有单位就不猜：("3-5年" 里的数字不是钱)，返回未知。
    """
    raw = (text or "").strip()
    if not raw or any(word in raw for word in _NEGOTIABLE):
        return Salary(raw=raw)

    months = 12
    m = _MONTHS_SUFFIX.search(raw)
    if m:
        months = int(m.group(1))
        if not 12 <= months <= 24:      # "20-40K" 后面偶然出现的两位数不是月数
            months = 12

    unit_match = _UNIT.search(raw)
    if not unit_match:
        return Salary(raw=raw)
    factor = _UNIT_TO_K[unit_match.group(1)]

    numbers = None
    rng = _RANGE.search(raw)
    if rng:
        numbers = [float(rng.group(1)), float(rng.group(2))]
    else:
        single = _SINGLE.search(raw)
        if single:
            value = float(single.group(1))
            numbers = [value, value]

    if not numbers:
        return Salary(raw=raw)

    values = _scale(numbers, factor)

    if _HOUR_WORD.search(raw):
        # 时薪：按每天 8 小时、每月 21.75 天折算
        values = [round(v * 8 * WORKDAYS_PER_MONTH, 2) for v in values]
        unit = "hour"
    elif _DAY_WORD.search(raw):
        values = [round(v * WORKDAYS_PER_MONTH, 2) for v in values]
        unit = "day"
    elif _YEAR_WORD.search(raw):
        values = [round(v / 12, 2) for v in values]
        unit = "year"
        months = 12
    else:
        unit = "month"

    low, high = min(values), max(values)
    # 明显是月薪口径之外的残留（例如"300-500元"没有 /天 也没有 千/万）时，
    # 元 -> 千 的系数已经处理过，这里只挡掉明显不合理的值。
    if high > 1000 or (high == 0):
        return Salary(raw=raw, months=months, unit="unknown")
    return Salary(raw=raw, min_k=low, max_k=high, months=months, unit=unit)


# ------------------------------------------------------------- experience
_EXP_UNLIMITED = ("不限", "无要求", "不要求", "均可")
_EXP_FRESH = ("应届", "在校", "实习生", "无经验", "0经验", "毕业生", "刚毕业")
_EXP_ABOVE = re.compile(r"(\d+(?:\.\d+)?)\s*年\s*(?:以上|及以上|起|\+)")


@dataclass(frozen=True)
class Experience:
    raw: str = ""
    min_years: float | None = None
    max_years: float | None = None
    unlimited: bool = False

    def as_dict(self):
        return {"raw": self.raw, "min_years": self.min_years, "max_years": self.max_years,
                "unlimited": self.unlimited}


def parse_experience(text):
    """"3-5年" -> (3, 5)；"应届毕业生" -> (0, 1)；"经验不限" -> unlimited。"""
    raw = (text or "").strip()
    if not raw:
        return Experience()
    if any(word in raw for word in _EXP_FRESH):
        return Experience(raw=raw, min_years=0, max_years=1)
    if any(word in raw for word in _EXP_UNLIMITED):
        return Experience(raw=raw, unlimited=True, min_years=0, max_years=99)

    above = _EXP_ABOVE.search(raw)
    if above:
        low = float(above.group(1))
        return Experience(raw=raw, min_years=low, max_years=99)

    rng = _RANGE.search(raw)
    if rng:
        low, high = float(rng.group(1)), float(rng.group(2))
        if high <= 40:                                    # "1-3年"；"20-40K" 不是年限
            return Experience(raw=raw, min_years=min(low, high), max_years=max(low, high))

    single = re.search(r"(\d+(?:\.\d+)?)\s*年", raw)
    if single:
        years = float(single.group(1))
        if years <= 40:
            return Experience(raw=raw, min_years=years, max_years=years)
    return Experience(raw=raw)


# ----------------------------------------------------------------- degree
# rank 越大门槛越高；0 = 不限。判断"我够不够"只需要比大小。
DEGREE_RANK = {"不限": 0, "学历不限": 0, "高中": 1, "中专": 1, "大专": 2, "专科": 2,
               "本科": 3, "硕士": 4, "研究生": 4, "博士": 5}
# 出现顺序即优先级：一句话里同时出现"本科"和"硕士"时按更高的算（"硕士优先"另说，见 parse_degree）
_DEGREE_SCAN = ("博士", "硕士", "研究生", "本科", "大专", "专科", "中专", "高中")


@dataclass(frozen=True)
class Degree:
    raw: str = ""
    label: str = ""
    rank: int = 0
    preferred_only: bool = False       # "本科及以上优先"/"硕士优先"：不是硬门槛

    def as_dict(self):
        return {"raw": self.raw, "label": self.label, "rank": self.rank,
                "preferred_only": self.preferred_only}


def parse_degree(text):
    """"本科及以上" -> rank 3；"硕士优先" -> rank 4 但 preferred_only=True。"""
    raw = (text or "").strip()
    if not raw:
        return Degree()
    for label in _DEGREE_SCAN:
        if label in raw:
            rank = DEGREE_RANK.get(label, 0)
            preferred = ("优先" in raw or "加分" in raw) and "及以上" not in raw
            return Degree(raw=raw, label=label, rank=rank, preferred_only=preferred)
    if "不限" in raw:
        return Degree(raw=raw, label="不限", rank=0)
    return Degree(raw=raw)


# ------------------------------------------------------------------ city
_CITY_ALIASES = {
    "北京市": "北京", "上海市": "上海", "天津市": "天津", "重庆市": "重庆",
    "深圳市": "深圳", "广州市": "广州", "杭州市": "杭州", "南京市": "南京",
    "苏州市": "苏州", "武汉市": "武汉", "成都市": "成都", "西安市": "西安",
    "长沙市": "长沙", "合肥市": "合肥", "郑州市": "郑州", "青岛市": "青岛",
    "厦门市": "厦门", "无锡市": "无锡", "东莞市": "东莞", "佛山市": "佛山",
    "宁波市": "宁波", "济南市": "济南", "福州市": "福州", "珠海市": "珠海",
    "香港": "香港", "新加坡": "新加坡",
}
_CITY_SPLIT = re.compile(r"[·・\-—/、,，\s]+")


def norm_city(text):
    """"北京市·朝阳区" -> "北京"；"上海-浦东新区" -> "上海"；认不出就原样返回首段。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    first = _CITY_SPLIT.split(raw)[0].strip()
    first = re.sub(r"(特别行政区|自治州|地区)$", "", first)
    if first in _CITY_ALIASES:
        return _CITY_ALIASES[first]
    if first.endswith("市") and len(first) > 2:
        return first[:-1]
    return first


def norm_cities(values):
    """去重且保序，丢掉空值和"全国"。"""
    seen, out = set(), []
    for value in values or []:
        city = norm_city(value)
        if not city or city in ("全国", "不限", "-") or city in seen:
            continue
        seen.add(city)
        out.append(city)
    return out


# ----------------------------------------------------------------- title
_TITLE_NOISE = re.compile(r"[【\[（(][^】\]）)]{0,20}[】\]）)]|\s+")
_TITLE_LEVEL = ("高级", "资深", "senior", "sr.", "中级", "初级", "junior", "jr.", "助理", "实习", "实习生")


def norm_title(text):
    """去掉【校招】/（急招）之类的括号和多余空白，折成可比较的标题。

    级别词（高级/初级/实习）保留：它们是筛选信号，不是噪声。
    """
    title = unicodedata.normalize("NFKC", (text or "")).strip()
    title = _TITLE_NOISE.sub(" ", title)
    return " ".join(title.split()).lower()


# ---------------------------------------------------------------- skills
# 词典：canonical -> 别名。CJK 别名用子串匹配，拉丁别名用词边界匹配（避免 RAG 命中 storage）。
SKILLS = {
    "Python": ["python"], "Java": ["java"], "Go": ["golang", " go "], "C++": ["c++", "cpp"],
    "C": [" c语言", " c/c++"], "C#": ["c#", ".net"], "Rust": ["rust"], "Scala": ["scala"],
    "JavaScript": ["javascript", "js"], "TypeScript": ["typescript", "ts"],
    "React": ["react"], "Vue": ["vue"], "Next.js": ["next.js", "nextjs"], "Node.js": ["node.js", "nodejs"],
    "FastAPI": ["fastapi"], "Django": ["django"], "Flask": ["flask"], "Spring Boot": ["spring boot", "springboot"],
    "gRPC": ["grpc"], "微服务": ["微服务", "microservice"], "高并发": ["高并发"], "分布式": ["分布式"],
    "SQL": ["sql"], "PostgreSQL": ["postgres", "pgsql"], "MySQL": ["mysql"], "SQLite": ["sqlite"],
    "Redis": ["redis"], "MongoDB": ["mongodb"], "Elasticsearch": ["elasticsearch", " es "],
    "Kafka": ["kafka"], "RabbitMQ": ["rabbitmq"], "消息队列": ["消息队列", "mq"],
    "Docker": ["docker"], "Kubernetes": ["kubernetes", "k8s"], "Linux": ["linux"], "Git": ["git"],
    "CI/CD": ["ci/cd", "cicd", "持续集成"], "Jenkins": ["jenkins"], "Nginx": ["nginx"],
    "阿里云": ["阿里云", "aliyun"], "腾讯云": ["腾讯云"], "AWS": ["aws"], "华为云": ["华为云"],
    "RAG": ["rag", "检索增强"], "LLM": ["llm", "大模型", "大语言模型"], "Agent": ["agent", "智能体"],
    "LangChain": ["langchain"], "LangGraph": ["langgraph"], "Prompt": ["prompt", "提示词"],
    "Function Calling": ["function calling", "工具调用", "tool calling"],
    "MCP": ["mcp ", "model context protocol"],
    "微调": ["微调", "fine-tune", "finetune", "lora", "sft"],
    "向量数据库": ["向量数据库", "vector database", "milvus", "faiss", "pgvector", "chroma", "qdrant"],
    "推理优化": ["vllm", "llama.cpp", "tensorrt", "推理加速", "量化部署"],
    "多模态": ["多模态", "multimodal"], "知识图谱": ["知识图谱", "neo4j"],
    "机器学习": ["机器学习", "machine learning"], "深度学习": ["深度学习", "deep learning"],
    "PyTorch": ["pytorch"], "TensorFlow": ["tensorflow"], "Transformers": ["transformers", "huggingface"],
    "NLP": ["nlp", "自然语言处理"], "计算机视觉": ["计算机视觉", "opencv", "yolo", " cv "],
    "语音识别": ["语音识别", "asr", "tts", "语音合成"], "OCR": ["ocr"],
    "推荐系统": ["推荐系统", "推荐算法"], "搜索": ["搜索引擎", "召回", "排序"],
    "数据挖掘": ["数据挖掘"], "数据分析": ["数据分析"], "数据仓库": ["数据仓库", "数仓", "data warehouse"],
    "ETL": ["etl", "数据管道"], "Spark": ["spark"], "Hadoop": ["hadoop"], "Flink": ["flink"],
    "Hive": ["hive"], "Airflow": ["airflow", "调度平台"], "Pandas": ["pandas"], "NumPy": ["numpy"],
    "BI": ["bi", "tableau", "power bi", "powerbi", "帆软", "finebi"], "Excel": ["excel", "vba"],
    "指标体系": ["指标体系", "指标口径"], "A/B测试": ["a/b", "ab测试", "abtest"],
    "爬虫": ["爬虫", "scrapy", "selenium", "playwright", "逆向"], "自动化测试": ["自动化测试", "pytest", "selenium"],
    "运维": ["运维", "sre"], "监控": ["prometheus", "grafana", "监控告警"],
    "网络": ["tcp/ip", "网络协议", "路由交换"], "安全": ["渗透测试", "安全加固", "等保", "漏洞"],
    "前端": ["前端", "html", "css", "webpack", "vite"], "小程序": ["小程序"],
    "Android": ["android"], "iOS": ["ios", "swift"], "Flutter": ["flutter"], "React Native": ["react native"],
    "Unity": ["unity"], "嵌入式": ["嵌入式", "单片机", "rtos", "stm32", "freertos"],
    "硬件": ["硬件", "pcb", "电路"], "驱动": ["驱动开发", "kernel"],
    "测试": ["测试用例", "功能测试", "接口测试"], "技术支持": ["技术支持", "售后", "客户支持"],
    "解决方案": ["解决方案", "售前"], "实施": ["实施工程师", "交付"],
    "产品": ["产品经理", "需求分析"], "项目管理": ["项目管理", "pmp", "敏捷", "scrum"],
    "金融业务": ["金融", "证券", "银行", "支付", "清算", "风控"], "区块链": ["区块链", "web3", "solidity"],
    "英语": ["英语", "english", "六级", "雅思"], "算法": ["算法", "数据结构", "leetcode"],
}

# 预编译：拉丁别名用词边界，CJK 用子串
_COMPILED = []
for _canon, _aliases in SKILLS.items():
    _patterns = []
    for _alias in _aliases:
        _alias = _alias.strip()
        if not _alias:
            continue
        if re.fullmatch(r"[a-z0-9 .+/#\-]+", _alias):
            _patterns.append(re.compile(rf"(?<![a-z0-9]){re.escape(_alias)}(?![a-z0-9])", re.I))
        else:
            _patterns.append(re.compile(re.escape(_alias), re.I))
    _COMPILED.append((_canon, _patterns))


def extract_skills(*texts):
    """把 JD 里命中的技能按词典归成一个有序列表（词典顺序，方便 diff）。"""
    haystack = "\n".join(t for t in texts if t)
    if not haystack:
        return []
    hits = []
    for canon, patterns in _COMPILED:
        for pattern in patterns:
            if pattern.search(haystack):
                hits.append(canon)
                break
    return hits


# --------------------------------------------------------------- channel
_CAMPUS_WORDS = ("校招", "校园招聘", "应届", "毕业生", "管培生", "实习", "2026届", "2027届", "2028届")
_SOCIAL_WORDS = ("社招", "社会招聘", "x年以上", "资深", "高级工程师", "专家")


def detect_channel(title, jd_text="", explicit=""):
    """explicit 优先（采集器/站点自己标的分类），否则按标题和正文里的词判断。"""
    if explicit in ("campus", "social", "intern"):
        return explicit
    blob = f"{title or ''}\n{(jd_text or '')[:600]}"
    if any(word in blob for word in ("实习", "intern")):
        return "intern"
    if any(word in blob for word in _CAMPUS_WORDS):
        return "campus"
    if any(word.lower() in blob.lower() for word in _SOCIAL_WORDS):
        return "social"
    return "unknown"


# ------------------------------------------------------- dedupe identity
def fingerprint(title, company, city):
    """跨源去重用：同一家公司、同一个标题、同一城市，视为同一个岗位。

    不同站点的措辞差异（"Java开发"vs"Java 开发工程师"）不在这一步处理，
    那属于"近似重复"，交给 pool.dedupe 的标题相似度判断。
    """
    import hashlib
    key = "|".join((norm_title(title), (company or "").strip(), norm_city(city)))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


DEFAULT_SKILL_FIELDS = ("skills",)


def normalize_row(*, title, company, city, jd_text="", salary_raw="", exp_raw="", degree_raw="",
                  channel=""):
    """原始字段 -> 入库字段。采集器只调这一个函数，字段口径只在一处定义。"""
    salary = parse_salary(salary_raw)
    experience = parse_experience(exp_raw)
    degree = parse_degree(degree_raw)
    cities = norm_cities([city] if city else [])
    if not cities:
        # 没有独立城市字段的源（比如 Atom），从标题的开头方括号里找 ["北京"] 这类写法
        m = re.search(r"[\[【]([^\]】]{2,12})[\]】]", title or "")
        if m:
            cities = norm_cities(_CITY_SPLIT.split(m.group(1)))
    return {
        "city": cities[0] if cities else "",
        "cities": cities,
        "title_norm": norm_title(title),
        "salary": salary,
        "experience": experience,
        "degree": degree,
        "skills": extract_skills(title, jd_text),
        "channel": detect_channel(title, jd_text, channel),
        "fingerprint": fingerprint(title, company, cities[0] if cities else ""),
    }
