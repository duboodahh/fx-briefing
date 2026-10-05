from datetime import date, datetime, timezone

from src.collect import events, news


def test_us_morning_release_lands_on_same_kst_evening():
    # 10/14 08:30 ET(EDT, UTC-4) = 10/14 21:30 KST
    ev = [{"date": "2026-10-14", "time": "08:30", "tz": "America/New_York", "country": "US", "name": "CPI"}]
    r = events.upcoming(ev, date(2026, 10, 14))
    assert (r[0]["kst_date"], r[0]["kst_time"], r[0]["days_left"]) == ("2026-10-14", "21:30", 0)


def test_dst_shift_after_us_clocks_change():
    # 11/6은 미국 서머타임 종료(11/1) 이후라 EST(UTC-5): 08:30 ET = 22:30 KST
    ev = [{"date": "2026-11-06", "time": "08:30", "tz": "America/New_York", "country": "US", "name": "NFP"}]
    assert events.upcoming(ev, date(2026, 11, 6))[0]["kst_time"] == "22:30"


def test_us_afternoon_event_rolls_to_next_kst_day():
    # 10/28 14:00 ET = 10/29 03:00 KST → 한국 기준으로는 다음 날 새벽
    ev = [{"date": "2026-10-28", "time": "14:00", "tz": "America/New_York", "country": "US", "name": "FOMC"}]
    r = events.upcoming(ev, date(2026, 10, 28))
    assert r == [] or r[0]["days_left"] == 1
    r = events.upcoming(ev, date(2026, 10, 29))
    assert (r[0]["kst_date"], r[0]["kst_time"]) == ("2026-10-29", "03:00")


def test_allday_event_keeps_local_date_and_window_filter():
    ev = [
        {"date": "2026-10-22", "country": "KR", "name": "금통위"},
        {"date": "2026-10-10", "country": "KR", "name": "범위 밖(과거)"},
        {"date": "2026-12-01", "country": "KR", "name": "범위 밖(먼 미래)"},
    ]
    r = events.upcoming(ev, date(2026, 10, 20), days=7)
    assert [e["name"] for e in r] == ["금통위"]
    assert r[0]["kst_time"] is None and r[0]["days_left"] == 2


def test_real_events_yaml_is_loadable():
    evs = events.load_events()
    assert len(evs) > 10
    assert all(e["date"] and e["name"] and e["country"] in events.COUNTRY_TZ for e in evs)


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Fed holds rates</title><link>http://a/1</link><pubDate>Mon, 05 Oct 2026 12:00:00 GMT</pubDate>
<description>&lt;p&gt;Policy &lt;b&gt;unchanged&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>Old story</title><link>http://a/2</link><pubDate>Mon, 28 Sep 2026 12:00:00 GMT</pubDate></item>
<item><title>No date</title><link>http://a/3</link></item>
</channel></rss>"""


def test_parse_rss_filters_old_and_strips_html():
    now = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
    r = news.parse_rss(RSS, "Test", now=now)
    assert [i["title"] for i in r] == ["Fed holds rates"]
    assert r[0]["summary"] == "Policy unchanged"
    assert r[0]["source"] == "Test"
