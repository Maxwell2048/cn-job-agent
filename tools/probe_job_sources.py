"""Probe which sources can actually be harvested, and dump evidence.

For every candidate source this prints status, content type, payload signature
and whether a usable job count could be extracted. Raw bodies land in
state/probes/ so an adapter can be written from the real shape instead of a guess.

Usage:
    python tools/probe_job_sources.py                 # all
    python tools/probe_job_sources.py --only rss,51job
    python tools/probe_job_sources.py --keep-body     # also save every body
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "state" / "probes"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
JSON_HEADERS = {**BASE_HEADERS, "Accept": "application/json, text/plain, */*"}


def _count_in_html(body):
    """Cheap signal: how many job-looking anchors does the HTML shell carry?"""
    return len(re.findall(r"(job|position|zhiwei|岗位)[^\"'<>]{0,40}", body, re.I))


def _json_shape(body):
    try:
        data = json.loads(body)
    except Exception:
        return None
    def walk(node, depth=0):
        if depth > 3:
            return "..."
        if isinstance(node, dict):
            return {k: walk(v, depth + 1) for k, v in list(node.items())[:8]}
        if isinstance(node, list):
            return [walk(node[0], depth + 1)] if node else []
        return type(node).__name__
    return walk(data)


def _rss_count(body):
    return len(re.findall(r"<item[\s>]", body))


def probe(name, kind, method, url, *, headers=None, json_body=None, params=None,
          parser=None, note=""):
    """Return a thunk so the probe runs inside the thread pool, not at import."""
    return lambda: _probe(name, kind, method, url, headers=headers, json_body=json_body,
                          params=params, parser=parser, note=note)


def _probe(name, kind, method, url, *, headers=None, json_body=None, params=None,
           parser=None, note=""):
    result = {"name": name, "kind": kind, "url": url, "note": note, "status": None,
              "ctype": "", "bytes": 0, "signal": "", "usable": False, "error": ""}
    try:
        with httpx.Client(headers=headers or JSON_HEADERS, timeout=15.0,
                          follow_redirects=True) as client:
            started = time.monotonic()
            resp = client.request(method, url, json=json_body, params=params)
            result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        result["status"] = resp.status_code
        result["ctype"] = (resp.headers.get("content-type") or "").split(";")[0]
        body = resp.text
        result["bytes"] = len(body)
        if parser:
            signal, usable = parser(body)
            result["signal"] = signal
            result["usable"] = usable
        else:
            result["signal"] = body[:90].replace("\n", " ")
        if result["usable"]:
            (OUT / f"{re.sub(r'[^a-z0-9]+', '_', name.lower())}.txt").write_text(
                body[:800_000], encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - a dead source is the result we want
        result["error"] = f"{exc.__class__.__name__}: {str(exc)[:120]}"
    return result


def json_count(*keys):
    def parse(body):
        try:
            data = json.loads(body)
        except Exception:
            return f"not json: {body[:60]!r}", False
        if isinstance(data, dict):
            for k in keys:
                node = data
                for part in k.split("."):
                    node = node.get(part) if isinstance(node, dict) else None
                if isinstance(node, list) and node:
                    return f"{k}: {len(node)} rows; first keys={list(node[0])[:8]}", True
        return f"json without {keys}: keys={list(data)[:8] if isinstance(data, dict) else type(data).__name__}", False
    return parse


def rss_parse(body):
    n = _rss_count(body)
    return f"{n} <item>", n > 0


def html_parse(body):
    n = _count_in_html(body)
    return f"{n} job-ish tokens (html shell, needs JS?)", False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma separated name substrings")
    ap.add_argument("--out", default=str(OUT / "summary.json"))
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    ts = int(time.time() * 1000)
    probes = [
        # ---------------------------------------------------------- RSS / Atom
        probe("v2ex-job-rss", "rss", "GET", "https://www.v2ex.com/feed/jobs.xml",
              headers=BASE_HEADERS, parser=rss_parse, note="V2EX 酷工作"),
        probe("eleduck-rss", "rss", "GET", "https://eleduck.com/rss",
              headers=BASE_HEADERS, parser=rss_parse, note="电鸭社区远程岗"),
        probe("eleduck-feed-alt", "rss", "GET", "https://eleduck.com/feed",
              headers=BASE_HEADERS, parser=rss_parse, note="电鸭备用 feed"),
        probe("nowcoder-rss", "rss", "GET", "https://www.nowcoder.com/rss/job",
              headers=BASE_HEADERS, parser=rss_parse, note="牛客（多半无 rss）"),

        # ---------------------------------------------------------- 招聘 SaaS 公开 JSON
        probe("zhiye-iflytek-all", "saas", "POST",
              "https://iflytek.zhiye.com/api/Jobad/GetJobAdPageList",
              headers={**JSON_HEADERS, "langType": "zh_CN", "X-Requested-With": "xmlhttprequest",
                       "Referer": "https://iflytek.zhiye.com/"},
              json_body={"PageIndex": 0, "PageSize": 20, "Category": [], "KeyWords": "",
                         "SpecialType": 0, "PortalId": "",
                         "DisplayFields": ["Category", "Kind", "LocId", "PostDate"]},
              parser=json_count("Data"), note="zhiye 全部分类（校招+社招）"),
        probe("zhiye-iflytek-social", "saas", "POST",
              "https://iflytek.zhiye.com/api/Jobad/GetJobAdPageList",
              headers={**JSON_HEADERS, "langType": "zh_CN", "X-Requested-With": "xmlhttprequest",
                       "Referer": "https://iflytek.zhiye.com/"},
              json_body={"PageIndex": 0, "PageSize": 20, "Category": ["1"], "KeyWords": "",
                         "SpecialType": 0, "PortalId": "",
                         "DisplayFields": ["Category", "Kind", "LocId", "PostDate"]},
              parser=json_count("Data"), note="zhiye 社招分类 Category=1"),

        # ---------------------------------------------------------- 聚合站 API
        probe("51job-search-pc", "aggregator", "GET",
              "https://we.51job.com/api/job/search-pc",
              headers={**JSON_HEADERS, "Referer": "https://we.51job.com/pc/search?keyword=python",
                       "FromDomain": "we.51job.com"},
              params={"api_key": "51job", "timestamp": ts, "keyword": "python", "searchType": "2",
                      "jobArea": "000000", "sortType": "0", "pageNum": "1", "pageSize": "20",
                      "source": "1", "pageCode": "sou|sou|soulb"},
              parser=json_count("resultbody.job.items"), note="前程无忧 PC 搜索"),
        probe("zhaopin-fe-api", "aggregator", "GET",
              "https://fe-api.zhaopin.com/c/i/search/position",
              headers={**JSON_HEADERS, "Referer": "https://sou.zhaopin.com/",
                       "Origin": "https://sou.zhaopin.com", "x-zp-client-id": "undefined"},
              params={"keyword": "python", "cityId": "538", "pageIndex": "1", "pageSize": "20"},
              parser=json_count("data.list"), note="智联搜索接口"),
        probe("lagou-wn-api", "aggregator", "GET",
              "https://www.lagou.com/wn/api/sou",
              headers={**JSON_HEADERS, "Referer": "https://www.lagou.com/wn/jobs?kd=python"},
              params={"kd": "python", "city": "深圳", "pn": "1", "first": "true", "needAddtionalResult": "false"},
              parser=json_count("content.positionResult.result"), note="拉勾 wn 接口（需 cookie）"),
        probe("zhipin-wapi", "aggregator", "GET",
              "https://www.zhipin.com/wapi/zpgeek/search/joblist.json",
              headers={**JSON_HEADERS, "Referer": "https://www.zhipin.com/web/geek/jobs?query=python"},
              params={"page": "1", "pageSize": "30", "query": "python", "city": "101280600"},
              parser=json_count("zpData.jobList"), note="BOSS 直聘（需 __zp_stoken__）"),
        probe("liepin-api", "aggregator", "GET",
              "https://api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job",
              headers={**JSON_HEADERS, "Referer": "https://www.liepin.com/zhaopin/"},
              params={"data": json.dumps({"mainSearchPcConditionForm": {"city": "410", "dq": "410",
                                                                       "pubTime": "", "currentPage": 0,
                                                                       "pageSize": 40, "key": "python",
                                                                       "suggestTag": "", "workYearCode": "0",
                                                                       "compId": "", "compName": "",
                                                                       "compTag": "", "industry": "",
                                                                       "salary": "", "jobKind": "",
                                                                       "compScale": "", "compKind": "",
                                                                       "compStage": "", "eduLevel": ""},
                                                     "passThroughForm": {"scene": "input", "skId": "",
                                                                         "fkId": "", "ckId": ""}})},
              parser=json_count("data.data.jobCardList"), note="猎聘 PC 搜索接口"),

        # ---------------------------------------------------------- 国企 / 官方
        probe("iguopin-home", "official", "GET", "https://www.iguopin.com/",
              headers=BASE_HEADERS, parser=html_parse, note="国聘首页"),
        probe("shixiseng-list", "official", "GET",
              "https://www.shixiseng.com/interns?keyword=python&city=%E5%85%A8%E5%9B%BD",
              headers=BASE_HEADERS, parser=html_parse, note="实习僧列表（HTML）"),
        probe("suda-jyb", "campus", "GET", "https://jyb.suda.edu.cn/",
              headers=BASE_HEADERS, parser=html_parse, note="苏州大学就业网"),
        probe("whu-jyzd", "campus", "GET", "https://jyzd.whu.edu.cn/",
              headers=BASE_HEADERS, parser=html_parse, note="武汉大学就业网"),
        probe("szrc", "campus", "GET", "https://www.szhr.com.cn/",
              headers=BASE_HEADERS, parser=html_parse, note="苏州人才网"),
    ]

    if args.only:
        wanted = [s.strip().lower() for s in args.only.split(",") if s.strip()]
        probes = [p for p in probes if any(w in p.name.lower() or w in p.kind.lower() for w in wanted)]

    print(f"probing {len(probes)} sources in parallel\n")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda fn: fn(), probes))

    print(f"{'source':26s} {'kind':10s} {'status':6s} {'bytes':>8s}  signal")
    print("-" * 110)
    for r in results:
        status = str(r["status"]) if r["status"] else "ERR"
        print(f"{r['name']:26s} {r['kind']:10s} {status:6s} {r['bytes']:8d}  {r['signal'][:70]}")
        if r["error"]:
            print(f"{'':26s} {'':10s} {'':6s} {'':8s}  !! {r['error']}")
        print(f"{'':26s} {'':10s} {'':6s} {'':8s}  .. {r['note']}")

    usable = [r["name"] for r in results if r["usable"]]
    print(f"\n直接可用（有结构化岗位数据）: {len(usable)}")
    for name in usable:
        print(f"  + {name}")
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
