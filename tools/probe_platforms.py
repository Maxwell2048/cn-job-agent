"""Probe the campus portals in data/seed/campus_2027.yaml to find out which
recruiting SaaS platform hosts each company's job board.

The point: collectors are cheap per *platform*, expensive per *company*. If 30
companies sit on the same platform, one collector covers all 30. This script
produces the evidence needed to pick which platforms to write first.

Usage:
    python tools/probe_platforms.py                # all companies with a URL-shaped portal
    python tools/probe_platforms.py --keys tencent,iflytek
    python tools/probe_platforms.py --out state/platform_probe.json
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed" / "campus_2027.yaml"
OUT = ROOT / "state" / "platform_probe.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
TIMEOUT = 12.0
MAX_BYTES = 400_000

# Host / HTML fingerprints. Each entry: platform key -> regex matched against
# the final URL and the first MAX_BYTES of the page. Order matters: the first
# platform whose pattern fires wins, so platform CDN hosts come before generic
# product names (a Moka tenant page often also mentions "moka" in a script path).
FINGERPRINTS = [
    ("moka",       r"mokahr\.com|moka\.ai|/moka/|moka-|Moka(HR|招聘)?"),
    ("zhiye",      r"\bzhiye\.com|/api/Jobad/|zhiye-public|CareerSite\.zhiye"),
    ("beisen",     r"italent\.cn|beisen\.com|italent-|北森"),
    ("dayee",      r"dayee\.com|dayee-|用友大易|大易云"),
    ("feishu",     r"larksuite\.com|feishu\.cn|hire\.feishu|飞书招聘"),
    ("hotjob",     r"hotjob\.cn"),
    ("chinahr",    r"chinahr\.com"),
    ("iguopin",    r"iguopin\.com"),
    ("zhaopin",    r"zhaopin\.com|zhaopin\.cn|智联招聘"),
    ("51job",      r"51job\.com|前程无忧"),
    ("liepin",     r"liepin\.com"),
    ("lagou",      r"lagou\.com"),
    ("maimai",     r"maimai\.cn"),
    ("nowcoder",   r"nowcoder\.com"),
]

# Self-hosted boards worth a bespoke collector: the page loads its own JSON API.
SELF_HOSTED_HINTS = [
    ("join.qq.com", "tencent"),
    ("talent.baidu.com", "baidu_style"),
    ("jobs.bytedance.com", "bytedance_style"),
    ("talent.alibaba.com", "alibaba_style"),
    ("zhaopin.meituan.com", "meituan_style"),
    ("hr.163.com", "netease_style"),
]

CJK = re.compile(r"[\u4e00-\u9fff]")


def portal_url(portal):
    """Return the first http(s) URL inside the portal field, or ''.

    Portal fields are hand-written: "iflytek.zhiye.com；公众号\"科大讯飞招聘\"",
    "zhaopin.sgcc.com.cn（唯一渠道）", "民生银行招聘官网". Only the URL-shaped
    leading token is usable.
    """
    portal = (portal or "").strip()
    if not portal:
        return ""
    for token in re.split(r"[；;，,\s（）()]+", portal):
        token = token.strip()
        if not token or CJK.search(token):
            continue
        if "." not in token:
            continue
        host = token.split("/")[0]
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(:\d+)?", host, re.I):
            continue
        return token if token.startswith("http") else "https://" + token
    return ""


def probe(item):
    key, name, url = item
    result = {"key": key, "name": name, "portal_url": url, "final_url": "", "status": None,
              "platform": "", "evidence": "", "error": ""}
    try:
        with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True, verify=False) as client:
            resp = client.get(url)
            result["status"] = resp.status_code
            result["final_url"] = str(resp.url)
            body = resp.text[:MAX_BYTES]
    except Exception as exc:  # noqa: BLE001 - a dead portal is a useful result too
        result["error"] = f"{exc.__class__.__name__}: {str(exc)[:160]}"
        return result

    haystack = f"{result['final_url']}\n{body}"
    for host, tag in SELF_HOSTED_HINTS:
        if host in result["final_url"]:
            result["platform"], result["evidence"] = f"self:{tag}", host
            return result
    for platform, pattern in FINGERPRINTS:
        m = re.search(pattern, haystack, re.I)
        if m:
            result["platform"] = platform
            result["evidence"] = f"{m.group(0)[:60]}"
            return result
    result["platform"] = "unknown"
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", help="comma separated company keys")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    seed = yaml.safe_load(SEED.read_text(encoding="utf-8"))
    wanted = set(args.keys.split(",")) if args.keys else None
    items = []
    for company in seed["companies"]:
        if wanted and company["key"] not in wanted:
            continue
        url = portal_url(company.get("portal", ""))
        if url:
            items.append((company["key"], company["name"], url))

    print(f"probing {len(items)} portals with {args.workers} workers\n")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(probe, items))

    results.sort(key=lambda r: (r["platform"] == "unknown", r["platform"], r["key"]))
    for r in results:
        state = r["platform"] or "ERROR"
        detail = r["final_url"] or r["error"]
        print(f"{r['key']:22s} {state:16s} {detail[:90]}   [{r['evidence'][:40]}]")

    counts = {}
    for r in results:
        counts[r["platform"]] = counts.get(r["platform"], 0) + 1
    print("\n--- platform coverage ---")
    for platform, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"{platform:20s} {n}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwritten: {args.out}")


if __name__ == "__main__":
    main()
