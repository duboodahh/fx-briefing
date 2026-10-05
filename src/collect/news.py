"""공개 RSS에서 최근 헤드라인을 모은다. 시장 영향도 선별·요약은 4단계에서 LLM이 한다."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (fx-briefing personal project)"}


def _clean(text, limit=300):
    text = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _parse_date(s):
    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def parse_rss(xml_text, source, now=None, max_age_hours=36):
    """RSS 2.0 문자열을 파싱해 최근 max_age_hours 이내 기사만 [dict]로 반환 (최신순)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    items = []
    for it in ET.fromstring(xml_text).iter("item"):
        title = _clean(it.findtext("title"), 200)
        published = _parse_date(it.findtext("pubDate"))
        if not title or published is None or published < cutoff:
            continue
        items.append(
            {
                "source": source,
                "title": title,
                "link": (it.findtext("link") or "").strip(),
                "published": published.astimezone(timezone.utc).isoformat(timespec="minutes"),
                "summary": _clean(it.findtext("description")),
            }
        )
    return sorted(items, key=lambda x: x["published"], reverse=True)


def fetch_feed(url, source, **kw):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        raise RuntimeError(f"{source}: 요청 실패 ({type(e).__name__})") from None
    if r.status_code != 200:
        raise RuntimeError(f"{source}: HTTP {r.status_code}")
    try:
        return parse_rss(r.content, source, **kw)
    except ET.ParseError:
        raise RuntimeError(f"{source}: RSS 파싱 실패") from None


def collect(feeds, **kw):
    """feeds: [{name, url, region, title_filter?}]. 피드별 실패는 격리하고, 제목 기준으로 중복을 제거한다.

    region(intl|kr)을 각 기사에 붙인다. title_filter(정규식)가 있으면 제목이 맞는 기사만 남긴다.
    """
    items, errors, seen = [], {}, set()
    for f in feeds:
        pattern = re.compile(f["title_filter"]) if f.get("title_filter") else None
        try:
            for it in fetch_feed(f["url"], f["name"], **kw):
                if pattern and not pattern.search(it["title"]):
                    continue
                k = it["title"].lower()
                if k not in seen:
                    seen.add(k)
                    it["region"] = f.get("region", "intl")
                    items.append(it)
        except RuntimeError as e:
            errors[f["name"]] = str(e)
    return sorted(items, key=lambda x: x["published"], reverse=True), errors
