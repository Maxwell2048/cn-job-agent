"""Job-site collectors, keyed by source name.

Each collector has `key`, `company_key`, `company_name`, `search(keyword, limit)`
returning ListedJob rows, and `detail(job)` filling in the JD text.

The zhiye tenants below are the ones found reachable on 2026-11-27 (public
list API, no login); channels say which of 校园招聘 / 社会招聘 each one is
searched in.
"""
from .base import Http, ListedJob, SiteError
from .tencent import TencentCollector
from .zhiye import ZhiyeCollector

ZHIYE_SITES = [
    # host, company key, company name, channels
    ("iflytek", "iflytek", "科大讯飞", ("campus", "social")),
    ("transsion", "transsion", "传音控股", ("campus", "social")),
    # vivo.zhiye.com is reachable but lists only 26 "员工校招" (category 5) technician roles: not searched.
    ("cicc", "cicc", "中金公司", ("campus", "social")),
    ("guosen", "guosen", "国信证券", ("campus", "social")),
    ("unitree", "unitree", "宇树科技", ("campus", "social")),
    ("roborock", "roborock", "石头科技", ("campus", "social")),
    ("sugon", "sugon", "中科曙光", ("campus", "social")),
    ("dahua", "dahua", "大华股份", ("campus", "social")),
    ("sunwoda", "sunwoda", "欣旺达", ("campus", "social")),
    ("ninestar", "ninestar", "纳思达", ("social",)),
]


def build_collectors(http):
    collectors = [TencentCollector(http)]
    collectors += [ZhiyeCollector(http, host, key, name, channels) for host, key, name, channels in ZHIYE_SITES]
    return {c.key: c for c in collectors}


__all__ = ["Http", "ListedJob", "SiteError", "build_collectors", "TencentCollector", "ZhiyeCollector", "ZHIYE_SITES"]
