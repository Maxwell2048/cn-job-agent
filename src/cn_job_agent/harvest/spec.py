"""岗位源注册表：把 data/sources.yaml 读成 SourceSpec。

新增一个源 = 往 YAML 里加一段，不用改代码。engine 决定用哪种抓法：

  zhiye      zhiye.com 招聘 SaaS。一个租户 = 一家公司，列表接口自带职责和要求
  atom       RSS / Atom 订阅（V2EX 酷工作这类），标题里常带城市和薪资
  json_api   任意公开 JSON 接口：路径、分页、字段映射都写在 YAML 里
  browser    Playwright 兜底：登录态 + 滚动列表，适合上了风控的聚合站
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "data" / "sources.yaml"

ENGINES = ("zhiye", "atom", "json_api", "browser")


class SourceError(ValueError):
    pass


@dataclass
class SourceSpec:
    key: str
    engine: str
    enabled: bool = True
    company_key: str = ""
    company_name: str = ""
    host: str = ""
    url: str = ""
    label: str = ""
    tier: str = ""                    # A 结构化公开 / B 需解析页面 / C 需登录风控
    channels: list = field(default_factory=list)
    limit: int = 200
    interval: float = 0.0
    keywords: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    note: str = ""

    def __post_init__(self):
        if self.engine not in ENGINES:
            raise SourceError(f"{self.key}: 未知 engine={self.engine!r}，可用：{'、'.join(ENGINES)}")
        self.limit = int(self.limit or 200)
        if not self.company_name:
            self.company_name = self.label or self.company_key or self.key

    @property
    def effective_interval(self):
        return float(self.interval or self.params.get("interval") or 1.5)


def load_sources(path=None, *, only=None, include_disabled=False, tier=None):
    """读注册表。only 按 key 过滤（支持前缀匹配），tier 按 A/B/C 过滤。"""
    path = Path(path or DEFAULT_PATH)
    if not path.is_file():
        raise SourceError(f"找不到源注册表：{path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = data.get("defaults") or {}
    specs = []
    for item in data.get("sources") or []:
        item = dict(item)
        if not include_disabled and not item.get("enabled", True):
            continue
        for name in ("limit", "interval"):
            if name in defaults and name not in item:
                item[name] = defaults[name]
        spec = SourceSpec(**item)
        if only and not any(spec.key == o or spec.key.startswith(o) for o in only):
            continue
        if tier and spec.tier.upper() != tier.upper():
            continue
        specs.append(spec)
    return specs


def describe(specs):
    """按 tier 分组的一行说明，给 CLI 和报告用。"""
    order = {"A": 0, "B": 1, "C": 2, "": 3}
    specs = sorted(specs, key=lambda s: (order.get(s.tier.upper(), 3), s.engine, s.key))
    return [{"key": s.key, "engine": s.engine, "tier": s.tier or "?", "company": s.company_name,
             "host": s.host or s.url, "channels": s.channels, "limit": s.limit,
             "enabled": s.enabled, "note": s.note} for s in specs]
