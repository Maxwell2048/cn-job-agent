"""Tencent campus recruiting (join.qq.com).

The site's job list calls POST /api/v1/position/searchPosition and the
detail page calls GET /api/v1/jobDetails/getJobDetailsByPostId. Project
mapping 1 is 应届毕业生 (graduate hiring). join.qq.com has no robots.txt.
"""
import time

from .base import ListedJob, SiteError, compose_jd

BASE = "https://join.qq.com"
GRADUATE_PROJECT = 1
PAGE_SIZE = 20


class TencentCollector:
    key = "tencent"
    company_key = "tencent"
    company_name = "腾讯"

    def __init__(self, http):
        self.http = http

    def _stamp(self):
        return int(time.time() * 1000)

    def search(self, keyword, limit=40):
        jobs, page = [], 1
        while len(jobs) < limit:
            body = {"projectIdList": [], "projectMappingIdList": [GRADUATE_PROJECT], "keyword": keyword,
                    "bgList": [], "workCountryType": 0, "workCityList": [], "recruitCityList": [],
                    "positionFidList": [], "pageIndex": page, "pageSize": PAGE_SIZE}
            data = self.http.request("POST", f"{BASE}/api/v1/position/searchPosition?timestamp={self._stamp()}",
                                     json=body)
            if data.get("status") != 0:
                raise SiteError(f"腾讯搜索返回 status={data.get('status')}：{data.get('message')}")
            rows = (data.get("data") or {}).get("positionList") or []
            for row in rows:
                jobs.append(ListedJob(
                    source=self.key, external_id=str(row["postId"]), company_key=self.company_key,
                    title=row.get("positionTitle", ""),
                    cities=[c.replace("总部", "") for c in (row.get("workCities") or "").split()],
                    url=f"{BASE}/post_detail.html?postid={row['postId']}",
                    category=row.get("projectName") or row.get("recruitLabelName") or ""))
            if len(rows) < PAGE_SIZE:
                break
            page += 1
        return jobs[:limit]

    def detail(self, job):
        data = self.http.request("GET", f"{BASE}/api/v1/jobDetails/getJobDetailsByPostId",
                                 params={"timestamp": self._stamp(), "postId": job.external_id})
        if data.get("status") != 0 or not data.get("data"):
            raise SiteError(f"腾讯岗位 {job.external_id} 详情读取失败：{data.get('message')}")
        d = data["data"]
        cities = [c.replace("总部", "") for c in d.get("workCityList") or []] or job.cities
        job.title = " ".join((d.get("title") or job.title).split())
        job.cities = cities
        job.category = d.get("projectName") or job.category
        job.jd_text = compose_jd(job.title, self.company_name, [
            f"公司：{self.company_name}",
            f"招聘类型：{job.category}（校园招聘）" if job.category else "招聘类型：校园招聘",
            f"岗位类别：{d.get('tidName')}" if d.get("tidName") else "",
            f"工作地点：{'、'.join(cities)}" if cities else "",
        ], [("岗位描述", d.get("desc")), ("岗位要求", d.get("request")),
            ("加分项", d.get("graduateBonus"))])
        return job
