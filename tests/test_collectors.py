"""Collectors against canned responses shaped like the real sites' JSON (no network)."""
import json

import httpx
import pytest

from cn_job_agent.collectors import Http, SiteError, TencentCollector, ZhiyeCollector
from cn_job_agent.collectors.zhiye import city_of


def http_with(handler):
    return Http(transport=httpx.MockTransport(handler), min_interval=0)


def tencent_row(i, title, cities="深圳总部 北京 "):
    return {"id": i, "positionTitle": title, "workCities": cities, "projectName": "应届毕业生",
            "postId": str(1000 + i)}


def test_tencent_search_pages_and_detail():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("searchPosition"):
            body = json.loads(request.content)
            assert body["projectMappingIdList"] == [1] and body["keyword"] == "Agent"
            page = body["pageIndex"]
            rows = [tencent_row(i, f"Agent 岗位 {i}") for i in range(20)] if page == 1 else [tencent_row(99, "AI全栈工程师")]
            return httpx.Response(200, json={"status": 0, "data": {"positionList": rows}})
        assert request.url.params["postId"] == "1099"
        return httpx.Response(200, json={"status": 0, "data": {
            "title": "AI全栈工程师", "tidName": "技术", "projectName": "应届毕业生", "workCityList": ["深圳总部", "杭州"],
            "desc": "1、负责 Agent 应用开发", "request": "1、熟悉 Python", "graduateBonus": ""}})

    collector = TencentCollector(http_with(handler))
    jobs = collector.search("Agent", limit=40)
    assert len(jobs) == 21 and jobs[0].cities == ["深圳", "北京"]
    job = collector.detail(jobs[-1])
    assert job.url.endswith("postid=1099")
    assert "岗位描述：\n1、负责 Agent 应用开发" in job.jd_text and "工作地点：深圳、杭州" in job.jd_text
    assert "加分项" not in job.jd_text      # empty sections are left out
    assert "招聘类型" not in job.jd_text and "岗位类别" not in job.jd_text   # metadata is not JD text


def test_tencent_error_status_raises():
    collector = TencentCollector(http_with(lambda r: httpx.Response(200, json={"status": 1, "message": "busy"})))
    with pytest.raises(SiteError):
        collector.search("Agent")


def test_http_errors_become_site_errors():
    collector = TencentCollector(http_with(lambda r: httpx.Response(503)))
    with pytest.raises(SiteError):
        collector.search("Agent")


def test_zhiye_search_builds_jd_from_the_list():
    def handler(request):
        assert request.headers["langType"] == "zh_CN"
        body = json.loads(request.content)
        assert body["Category"] == ["2"] and body["KeyWords"] == "Agent"
        return httpx.Response(200, json={"Code": 200, "Count": 1, "Data": [{
            "Id": "abc-1", "JobAdName": "AI Agent 应用研发工程师(J1)", "LocNames": ["湖北省·武汉市"],
            "Category": "校园招聘", "PostDate": "2026-08-26T18:04:23", "Duty": "负责 Agent", "Require": "熟悉 Python"}]})

    collector = ZhiyeCollector(http_with(handler), "iflytek", "iflytek", "科大讯飞")
    [job] = collector.search("Agent")
    assert job.source == "zhiye:iflytek" and job.cities == ["武汉"] and job.posted_at == "2026-08-26"
    assert job.url == "https://iflytek.zhiye.com/campus/detail?jobAdId=abc-1"
    assert "工作职责：\n负责 Agent" in job.jd_text and "任职要求：\n熟悉 Python" in job.jd_text
    assert "招聘类型" not in job.jd_text and "发布日期" not in job.jd_text
    assert collector.detail(job) is job


@pytest.mark.parametrize("name, city", [("安徽省·合肥市", "合肥"), ("深圳市", "深圳"), ("上海", "上海")])
def test_city_of(name, city):
    assert city_of(name) == city


def test_titles_are_single_line():
    from cn_job_agent.collectors import ListedJob
    assert ListedJob("s", "1", "c", "Data Agent研发工程师\n（大数据方向）").title == "Data Agent研发工程师 （大数据方向）"
