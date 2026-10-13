"""오버나잇 브리핑용 뉴스 수집·선별. 1순위는 '발행처 원문 링크가 있는 기사'다.

규칙
 1. 원문 링크(발행처 도메인으로 직접 연결)가 없는 기사는 후보에서 뺀다. (구글뉴스 중간 주소 등)
 2. 남은 기사는 등급(1 원 출처 → 2 주요 언론 → 3 전문 사이트)과 최신순으로 정렬한다.
 3. 한 매체가 입력을 독점하지 않도록 매체별 상한을 둔다.
 4. 기간은 직전 미국 장 마감 시점부터 지금까지다.
"""
from datetime import datetime, time, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

from src.collect import news
from src.overnight import collect as ov

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "overnight_news.yaml"
SUMMARY_CHARS = 240
TRACKING_PARAMS = {"mod", "partner", "emc", "ocid", "cmpid", "smid", "taid", "guccounter", "guce_referrer", "fbclid", "gclid"}


def clean_url(url):
    """원문 주소에서 추적용 쿼리 파라미터만 제거한다. (기사 식별에 필요한 파라미터는 남긴다)"""
    parts = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if not (k.lower().startswith("utm_") or k.lower() in TRACKING_PARAMS)]
    return urlunsplit(parts._replace(query=urlencode(q)))


def window_hours(session, now_utc, margin=2):
    """직전 미국 장 마감(16:00 ET)부터 now_utc까지의 시간(여유 포함)."""
    prev_close = datetime.combine(ov.previous_us_session(session), time(16, 0), ov.ET).astimezone(timezone.utc)
    return max(24, int((now_utc - prev_close).total_seconds() // 3600) + margin)


def rank(items, per_source, max_total):
    """원문 있는 기사만 남겨 등급·최신순으로 정렬하고 매체별·전체 상한을 적용한다. 반환: (후보 목록, 원문 없어 제외한 수)."""
    originals = [i for i in items if i.get("original")]
    excluded = len(items) - len(originals)
    originals.sort(key=lambda x: x["published"], reverse=True)       # 최신순(안정 정렬의 바탕)
    originals.sort(key=lambda x: x["tier"])                          # 등급 우선
    count, picked = {}, []
    for it in originals:
        if count.get(it["source"], 0) >= per_source:
            continue
        count[it["source"]] = count.get(it["source"], 0) + 1
        picked.append(it)
    picked = picked[:max_total]
    return [
        {
            "id": n + 1, "source": it["source"], "tier": it["tier"], "topic": it["topic"], "lang": it["lang"],
            "title": it["title"], "summary": it["summary"][:SUMMARY_CHARS],
            "published_utc": it["published"], "url": clean_url(it["link"]),
        }
        for n, it in enumerate(picked)
    ], excluded


def collect_news(session, now_utc=None):
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    now_utc = now_utc or datetime.now(timezone.utc)
    hours = window_hours(session, now_utc, cfg["window_margin_hours"])
    items, errors = news.collect(cfg["feeds"], max_age_hours=hours)
    cands, excluded = rank(items, cfg["max_per_source"], cfg["max_total"])
    by_source = {}
    for c in cands:
        by_source[c["source"]] = by_source.get(c["source"], 0) + 1
    return {
        "window_hours": hours,
        "collected": len(items),
        "excluded_no_original": excluded,
        "candidates": cands,
        "by_source": by_source,
        "errors": errors,
    }
