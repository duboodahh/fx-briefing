from src.brief import build_input, verify

DATA = {
    "markets": [{"name": "USD/KRW", "last": 1345.08, "change": -15.51, "change_pct": -1.14, "asof": "2026-10-05"}],
    "rates": {"yields": [{"name": "미국채 10년", "last": 5.24, "change_bp": -5.0, "asof": "2026-10-01"}],
              "spreads": [{"name": "한미 10년", "last_bp": -80.4, "change_bp": 7.9}]},
    "events_next_14d": [{"name": "미국 9월 CPI", "kst_date": "2026-10-14", "kst_time": "21:30", "days_left": 9}],
    "news": [{"title": "Fed's Waller sees rates near 3.5% by year end", "summary": ""}],
}


def test_matching_numbers_pass():
    text = "원/달러 1,345.08원(-1.14%), 미국 10년 5.24%(-5.0bp), 한미 10년 금리차 -80.4bp, CPI는 10/14 21:30 발표(D-9)."
    assert verify.find_unverified(text, DATA) == []


def test_sign_and_rounding_tolerated():
    # 부호 방향, 적힌 자릿수까지 반올림한 값은 통과
    assert verify.find_unverified("원/달러 1,345원, 하락폭 1.1%", DATA) == []
    assert verify.find_unverified("한미 10년 금리차 80.4bp 역전", DATA) == []


def test_invented_numbers_flagged():
    text = "원/달러 1,350.50원, 미국 10년 5.30%, 금리차 -81bp"
    bad = verify.find_unverified(text, DATA)
    assert "1,350.50" in bad and "5.30" in bad and "81" in bad


def test_numbers_from_news_are_allowed():
    assert verify.find_unverified("Waller는 연말 금리 3.5%를 언급", DATA) == []


def test_dates_times_years_counts_ignored():
    text = "10/28 FOMC, 2026년, 07:30 KST, 뉴스 3개, 3년물과 10년물, 2Y, D-9"
    assert verify.find_unverified(text, DATA) == []


def test_select_news_caps_per_source_and_orders_newest_first():
    items = [{"source": "A", "title": f"a{i}", "summary": "x" * 500, "published": f"2026-10-0{i}T00:00+00:00"} for i in range(1, 10)]
    items += [{"source": "B", "title": "b1", "summary": "", "published": "2026-10-09T12:00+00:00"}]
    out = build_input.select_news(items)
    assert sum(1 for n in out if n["source"] == "A") == build_input.NEWS_PER_SOURCE
    assert out[0]["source"] == "B"                       # 가장 최신
    assert all(len(n["summary"]) <= build_input.SUMMARY_CHARS for n in out)
    assert [n["id"] for n in out] == list(range(1, len(out) + 1))
