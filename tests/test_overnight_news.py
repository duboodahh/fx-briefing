from datetime import date, datetime, timezone

from src.collect import news
from src.overnight import news as onews


def test_is_original_requires_publisher_domain():
    assert news.is_original("https://www.wsj.com/finance/x", ["wsj.com"]) is True
    assert news.is_original("https://markets.wsj.com/a", ["wsj.com"]) is True            # 하위 도메인 허용
    assert news.is_original("https://news.google.com/rss/articles/CBM", ["apnews.com"]) is False   # 중간 주소
    assert news.is_original("https://evil-wsj.com/x", ["wsj.com"]) is False             # 비슷한 도메인 차단
    assert news.is_original("", ["wsj.com"]) is False
    assert news.is_original("https://news.google.com/x") is False                        # 도메인 지정이 없어도 중간 주소는 불가


def test_clean_url_drops_tracking_but_keeps_article_params():
    assert onews.clean_url("https://www.wsj.com/a/b?mod=rss_markets_ma") == "https://www.wsj.com/a/b"
    assert onews.clean_url("https://x.com/a?id=77&utm_source=rss&partner=rss") == "https://x.com/a?id=77"


def item(source, tier, published, original=True, title=None):
    return {"source": source, "tier": tier, "topic": "both", "lang": "en", "title": title or f"{source} {published}",
            "summary": "s", "published": published, "link": f"https://{source}.test/{published}?mod=rss", "original": original}


def test_rank_excludes_non_original_and_orders_by_tier_then_recency():
    items = [item("tier3", 3, "2026-10-13T10:00"), item("tier2old", 2, "2026-10-13T05:00"),
             item("tier2new", 2, "2026-10-13T09:00"), item("tier1", 1, "2026-10-12T20:00"),
             item("aggregator", 2, "2026-10-13T11:00", original=False)]
    out, excluded = onews.rank(items, per_source=8, max_total=60)
    assert excluded == 1
    assert [c["source"] for c in out] == ["tier1", "tier2new", "tier2old", "tier3"]
    assert [c["id"] for c in out] == [1, 2, 3, 4]
    assert all("mod=" not in c["url"] for c in out)                                      # 추적 파라미터 제거


def test_rank_caps_per_source_and_total():
    items = [item("A", 2, f"2026-10-13T0{i}:00") for i in range(9)] + [item("B", 2, "2026-10-12T01:00")]
    out, _ = onews.rank(items, per_source=3, max_total=4)
    assert [c["source"] for c in out].count("A") == 3 and len(out) == 4


def test_window_hours_spans_from_previous_close():
    # 세션 10/12(월)의 직전 마감 = 10/9(금) 16:00 ET = 10/9 20:00 UTC. 10/12 22:00 UTC까지 74시간 + 여유 2 = 76
    from src.overnight import collect
    h = onews.window_hours(date(2026, 10, 12), datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc), margin=2)
    assert h == 76
    # 짧은 구간이라도 최소 24시간
    assert onews.window_hours(date(2026, 10, 13), datetime(2026, 10, 13, 22, 0, tzinfo=timezone.utc), margin=0) >= 24


def test_rank_caps_same_publisher_across_feeds():
    # CNBC 계열 피드 3개(각 3건)는 한 발행처로 묶여 합계 상한(4건)을 넘지 못하고, 다른 발행처가 자리를 얻는다
    items = [{**item(f"CNBC {k}", 2, f"2026-10-13T0{i}:00"), "publisher": "CNBC"} for k in "ABC" for i in range(3)]
    items += [item("FT", 2, "2026-10-12T01:00")]
    out, _ = onews.rank(items, per_source=6, max_total=80, per_publisher=4)
    assert [c["publisher"] for c in out].count("CNBC") == 4 and any(c["source"] == "FT" for c in out)
