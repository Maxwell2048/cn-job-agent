"""Company job sites on the zhiye.com recruiting platform (one collector per tenant host).

The job list calls POST /api/Jobad/GetJobAdPageList. Category "2" is 校园招聘
and "1" is 社会招聘; each tenant is searched in the channels configured for
it, and every row is tagged campus or social from its own CategoryId. The
list rows already carry the duties (Duty) and requirements (Require), so no
detail request is needed. robots.txt on these hosts allows all paths.
"""
from .base import ListedJob, SiteError, compose_jd

PAGE_SIZE = 20
CATEGORY = {"campus": "2", "social": "1"}
CHANNEL = {code: channel for channel, code in CATEGORY.items()}


def city_of(loc_name):
    """"安徽省·合肥市" -> "合肥"; "深圳市" -> "深圳"."""
    name = loc_name.split("·")[-1].strip()
    return name[:-1] if name.endswith("市") and len(name) > 2 else name


class ZhiyeCollector:
    def __init__(self, http, host, company_key, company_name, channels=("campus",)):
        self.http = http
        self.host = host
        self.key = f"zhiye:{host}"
        self.company_key = company_key
        self.company_name = company_name
        self.channels = tuple(channels)
        self.base = f"https://{host}.zhiye.com"

    def search(self, keyword, limit=40):
        jobs, page = [], 0
        headers = {"langType": "zh_CN", "X-Requested-With": "xmlhttprequest"}
        codes = [CATEGORY[c] for c in self.channels]
        while len(jobs) < limit:
            body = {"PageIndex": page, "PageSize": PAGE_SIZE, "Category": codes, "KeyWords": keyword,
                    "SpecialType": 0, "PortalId": "",
                    "DisplayFields": ["Category", "Kind", "LocId", "PostDate", "ClassificationOne"]}
            data = self.http.request("POST", f"{self.base}/api/Jobad/GetJobAdPageList", json=body, headers=headers)
            if data.get("Code") != 200:
                raise SiteError(f"{self.company_name}搜索返回 Code={data.get('Code')}：{data.get('Message')}")
            rows = data.get("Data") or []
            for row in rows:
                channel = CHANNEL.get(str(row.get("CategoryId") or ""), "campus" if "校园" in (row.get("Category") or "")
                                      else "social")
                cities = [city_of(n) for n in row.get("LocNames") or []]
                # /campus/detail opens any posting of the tenant, social ones included (/social/detail does not).
                job = ListedJob(source=self.key, external_id=str(row["Id"]), company_key=self.company_key,
                                title=row.get("JobAdName", ""), cities=cities, channel=channel,
                                url=f"{self.base}/campus/detail?jobAdId={row['Id']}",
                                posted_at=(row.get("PostDate") or "")[:10], category=row.get("Category") or "")
                # Category and post date live on the posting, not in the JD text the model reads.
                job.jd_text = compose_jd(job.title, self.company_name, [
                    f"公司：{self.company_name}",
                    f"工作地点：{'、'.join(row.get('LocNames') or [])}" if row.get("LocNames") else "",
                ], [("工作职责", row.get("Duty")), ("任职要求", row.get("Require"))])
                jobs.append(job)
            total = data.get("Count") or 0
            if len(rows) < PAGE_SIZE or (page + 1) * PAGE_SIZE >= total:
                break
            page += 1
        return jobs[:limit]

    def detail(self, job):
        if not job.jd_text:
            raise SiteError(f"{self.company_name}岗位 {job.external_id} 没有职责和要求文本")
        return job
