from datetime import date

from src.brief import generate, render
from src.collect import news, treasury

DATA = {
    "today_kst": "2026-10-05",
    "weekday": "월",
    "markets": {
        "usdkrw": {"name": "USD/KRW", "last": 1345.08, "change": -15.51, "change_pct": -1.14, "asof": "2026-10-05"},
        "usdjpy": {"name": "USD/JPY", "last": 157.93, "change": 0.37, "change_pct": 0.23, "asof": "2026-10-02"},
        "dxy": {"name": "DXY", "last": 102.41, "change": 0.48, "change_pct": 0.47, "asof": "2026-10-05"},
        "wti": {"name": "WTI", "last": 90.38, "change": -0.73, "change_pct": -0.8, "asof": "2026-10-05"},
    },
    "rates": {
        "yields": {
            "us10y": {"name": "미국채 10년", "last": 5.28, "change_bp": 4.0, "asof": "2026-10-02"},
            "us2y": {"name": "미국채 2년", "last": 4.83, "change_bp": 5.0, "asof": "2026-10-02"},
            "kr3y": {"name": "국고채 3년", "last": 3.937, "change_bp": -7.3, "asof": "2026-10-02"},
            "kr10y": {"name": "국고채 10년", "last": 4.365, "change_bp": -7.1, "asof": "2026-10-02"},
        },
        "spreads": {
            "us_curve_10y2y": {"last_bp": 45.0, "change_bp": -1.0, "asof": "2026-10-02"},
            "kr_curve_10y3y": {"last_bp": 42.8, "change_bp": 0.2, "asof": "2026-10-02"},
            "kr_us_10y": {"last_bp": -91.5, "change_bp": -11.1, "asof": "2026-10-02"},
        },
    },
    "events": [{"name": "미국 9월 CPI", "kst_date": "2026-10-14", "kst_time": "21:30", "days_left": 9}],
    "news_intl": [{"id": 1, "source": "CNBC Economy", "title": "Jobs rose 29,000", "summary": ""}],
    "news_kr": [{"id": 2, "source": "한국경제", "title": "외국인 코스피 20조 매도", "summary": ""}],
    "data_issues": [],
}
PICKS = {"intl": [{"id": 1, "summary": "미 9월 고용 2.9만 명 증가"}], "kr": [{"id": 2, "summary": "외국인 20조 순매도"}]}


def test_render_matches_agreed_format():
    out = render.render(DATA, PICKS)
    lines = out.split("\n")
    assert lines[0] == "Daily Macro Issue Briefing"
    assert lines[1] == "2026.10.05(월)"
    assert "[국외]" in lines and "[국내]" in lines
    assert "• 미 9월 고용 2.9만 명 증가 (CNBC Economy)" in lines
    assert "[금리]" in lines and "[환율•유가]" in lines
    assert "• 미국 국채 10Y 5.28% (+4.0bp)" in lines
    assert "• 국고채 3Y 3.94% (-7.3bp)" in lines          # 3.937 → 소수 둘째 자리
    assert "• 한미 10Y 금리차(국고-미 국채) -91.5bp (-11.1bp)" in lines
    assert "• 원/달러 1,345.08원 (-15.51원)" in lines
    # [금리] 블록 → 빈 줄 → [환율•유가] 블록
    i = lines.index("[환율•유가]")
    assert lines[i - 1] == "" and lines[lines.index("[금리]") + 1].startswith("• 미국 국채 10Y")
    # 일정은 제목 줄 아래에, 기준 줄과는 빈 줄로 띄운다
    i = lines.index("[다음 주요 일정]")
    assert lines[i + 1] == "10/14(수) 21:30 미국 9월 CPI"
    assert lines[i + 2] == "" and lines[i + 3].startswith("*기준: ")
    assert lines[-1] == lines[i + 3]


def test_near_events_use_plain_header_and_list_up_to_three():
    evs = [{"name": f"일정{i}", "kst_date": "2026-10-06", "kst_time": None, "days_left": 1} for i in range(5)]
    out = render.render({**DATA, "events": evs}, PICKS).split("\n")
    i = out.index("[주요 일정]")
    assert out[i + 1: i + 4] == ["10/6(화) 일정0", "10/6(화) 일정1", "10/6(화) 일정2"] and out[i + 4] == ""


def test_no_events_keeps_only_basis_line():
    out = render.render({**DATA, "events": []}, PICKS)
    assert "주요 일정" not in out and out.split("\n")[-1].startswith("*기준: ")


def test_basis_line_groups_by_date():
    line = render._basis_line(DATA)
    assert line == "*기준: 원/달러•DXY•WTI 10/5 / 금리•달러/엔 10/2"


def test_missing_items_are_marked_not_invented():
    d = {**DATA, "rates": {"yields": {}, "spreads": {}}}
    out = render.render(d, PICKS)
    assert "• 미국 국채 10Y 수집 실패" in out and "• 국고채 3Y 수집 실패" in out


def test_no_news_shows_placeholder_and_fits_telegram():
    out = render.render(DATA, {"intl": [], "kr": []})
    assert "• 오늘 선별된 주요 뉴스 없음" in out
    assert len(out) < 4096


def test_negative_zero_is_not_shown():
    assert render._num(-0.001, 2, sign=True) == "+0.00"


def test_clean_picks_drops_bad_ids_and_caps_three():
    d = {**DATA, "news_intl": [{"id": i, "source": "X", "title": "t", "summary": ""} for i in (1, 2, 3, 4)], "news_kr": []}
    raw = {"intl": [{"id": 1, "summary": "a"}, {"id": 2, "summary": "b"}, {"id": 3, "summary": "c"},
                    {"id": 4, "summary": "d"}, {"id": 99, "summary": "x"}, {"id": 1, "summary": "dup"}],
           "kr": [{"id": 1, "summary": "다른 지역 id"}]}
    picks, problems = generate.clean_picks(raw, d)
    assert [p["id"] for p in picks["intl"]] == [1, 2, 3]
    assert picks["kr"] == []
    assert any("99" in p for p in problems) and any("중복" in p for p in problems)


XML = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"
 xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"
 xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
<entry><content><m:properties><d:NEW_DATE>2026-10-01T00:00:00</d:NEW_DATE><d:BC_2YEAR>4.78</d:BC_2YEAR></m:properties></content></entry>
<entry><content><m:properties><d:NEW_DATE>2026-10-02T00:00:00</d:NEW_DATE><d:BC_2YEAR>4.83</d:BC_2YEAR></m:properties></content></entry>
<entry><content><m:properties><d:NEW_DATE>2026-10-03T00:00:00</d:NEW_DATE><d:BC_2YEAR>N/A</d:BC_2YEAR></m:properties></content></entry>
</feed>"""


def test_treasury_parse_sorted_and_skips_na():
    assert treasury.parse_month(XML, "BC_2YEAR") == [("2026-10-01", 4.78), ("2026-10-02", 4.83)]


def test_treasury_month_helper_wraps_year():
    assert treasury._month_start(date(2026, 1, 15), 0) == "202601"
    assert treasury._month_start(date(2026, 1, 15), 1) == "202512"


def test_news_collect_adds_region_and_applies_title_filter(monkeypatch):
    def fake_fetch(url, source, **kw):
        return [
            {"source": source, "title": "원/달러 환율 급락", "link": "", "published": "2026-10-05T00:00+00:00", "summary": ""},
            {"source": source, "title": "신제품 출시 소식", "link": "", "published": "2026-10-05T00:00+00:00", "summary": ""},
        ]

    monkeypatch.setattr(news, "fetch_feed", fake_fetch)
    feeds = [{"name": "연합뉴스", "url": "u", "region": "kr", "title_filter": "환율|금리"}]
    items, errors = news.collect(feeds)
    assert [i["title"] for i in items] == ["원/달러 환율 급락"]
    assert items[0]["region"] == "kr" and errors == {}
