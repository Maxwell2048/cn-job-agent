"""Job-site collectors, keyed by source name.

Each collector has `key`, `company_key`, `company_name`, `search(keyword, limit)`
returning ListedJob rows, and `detail(job)` filling in the JD text.
"""
from .base import Http, ListedJob, SiteError
from .tencent import TencentCollector
from .zhiye import ZhiyeCollector

ZHIYE_SITES = [("iflytek", "iflytek", "科大讯飞"), ("transsion", "transsion", "传音控股")]


def build_collectors(http):
    collectors = [TencentCollector(http)]
    collectors += [ZhiyeCollector(http, host, key, name) for host, key, name in ZHIYE_SITES]
    return {c.key: c for c in collectors}


__all__ = ["Http", "ListedJob", "SiteError", "build_collectors", "TencentCollector", "ZhiyeCollector"]
