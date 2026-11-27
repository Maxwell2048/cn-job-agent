"""Shared pieces of the job-site collectors.

Collectors read the public JSON endpoints that the companies' own campus
sites call from the browser: no login, no captcha, nothing behind an account.
Requests are throttled per host and identify as a generic client.
"""
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; job-search-client/0.1)"
MIN_INTERVAL = 1.0      # seconds between requests to the same host


@dataclass
class ListedJob:
    source: str                 # collector key, e.g. "tencent" or "zhiye:iflytek"
    external_id: str            # the site's own id
    company_key: str            # key in the companies table
    title: str
    cities: list[str] = field(default_factory=list)
    url: str = ""
    posted_at: str = ""
    category: str = ""          # the site's recruiting project, e.g. 应届毕业生 / 校园招聘
    jd_text: str = ""           # empty until the detail has been fetched
    channel: str = "campus"     # campus | social

    def __post_init__(self):
        self.title = " ".join((self.title or "").split())    # some sites put line breaks in titles

    def brief(self):
        """What the planner agent sees: enough to judge relevance, no full JD."""
        return {"source": self.source, "id": self.external_id, "title": self.title, "cities": self.cities,
                "channel": self.channel, "category": self.category, "posted_at": self.posted_at}


class SiteError(RuntimeError):
    pass


class Http:
    """httpx client with per-host throttling. `transport` lets tests replace the network."""

    def __init__(self, transport=None, min_interval=MIN_INTERVAL, timeout=20.0):
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                                   timeout=timeout, transport=transport, follow_redirects=True)
        self.min_interval = min_interval
        self._last = {}
        self._lock = threading.Lock()

    def _wait(self, url):
        host = urlsplit(url).netloc
        with self._lock:
            delay = self._last.get(host, 0) + self.min_interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last[host] = time.monotonic()

    def request(self, method, url, **kwargs):
        self._wait(url)
        try:
            response = self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SiteError(f"{method} {url} 失败：{exc.__class__.__name__}: {exc}") from exc

    def close(self):
        self.client.close()


def clean(text):
    return (text or "").replace("\r\n", "\n").strip()


def compose_jd(title, company, lines, sections):
    """A plain-text JD: title, metadata lines, then titled sections. Empty parts are skipped."""
    parts = [title, ""]
    parts += [line for line in lines if line]
    for heading, body in sections:
        body = clean(body)
        if body:
            parts += ["", f"{heading}：", body]
    return "\n".join(parts).strip() + "\n"
