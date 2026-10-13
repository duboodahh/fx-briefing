from datetime import date

from src.brief import build_input, render, verify
from src.collect import market_calendar as mc
from test_render_pipeline import DATA, PICKS


# ---- 미국 채권시장 휴장 (주식은 열지만 채권은 쉬는 날) ----
def test_columbus_day_is_bond_only_holiday():
    assert mc.us_bond_only_holiday(date(2026, 10, 12)) is True     # 10월 둘째 월요일
    assert mc.us_bond_only_holiday(date(2026, 10, 5)) is False     # 첫째 월요일
    assert mc.us_bond_only_holiday(date(2026, 10, 19)) is False    # 셋째 월요일


def test_veterans_day_rules_for_weekends():
    assert mc.us_bond_only_holiday(date(2026, 11, 11)) is True     # 수요일
    assert mc.us_bond_only_holiday(date(2027, 11, 11)) is True     # 목요일
    # 2028-11-11은 토요일: 금요일(11/10)에 쉬지 않는다
    assert mc.us_bond_only_holiday(date(2028, 11, 10)) is False
    # 2029-11-11은 일요일: 월요일(11/12)에 쉰다
    assert mc.us_bond_only_holiday(date(2029, 11, 12)) is True


def test_day_after_columbus_day_hides_us_rates_but_still_sends():
    s = mc.status(date(2026, 10, 13))      # 구간 [월 10/12]
    assert s["us_new"] is False and s["us_closed"] == ["2026-10-12"]
    assert s["us_session"] is True          # 주식시장은 열렸으므로
    assert s["kr_new"] is True and s["skip"] is False


def test_us_hidden_also_hides_cross_spread_and_basis_date():
    d = {**DATA, "calendar": {"kr_new": True, "us_new": False, "kr_closed": [], "us_closed": ["2026-10-12"]}}
    out = render.render(d, PICKS)
    assert "• 미국 채권시장 휴장 (10/12)" in out
    assert "미국 국채 10Y" not in out and "한미 10Y 금리차" not in out
    assert "• 국고채 3Y 3.94% (-7.3bp)" in out
    assert "미국채" not in out.split("*기준:")[1]


# ---- 환율·유가 기준 표기: 수집 시각 ----
def test_quote_label_uses_snapshot_time_when_recent():
    d = {**DATA, "snapshot_kst": "2026-10-05T14:07"}
    line = render._basis_line(d)
    # 원/달러·DXY·WTI(10/5 봉)와 달러/엔(10/2 봉, 3일 이내)은 모두 수집 시각으로 표기, 금리는 거래일
    assert line == "*기준: 원/달러•달러/엔•DXY•WTI 10/5 14시 / 금리 10/2"


def test_quote_label_falls_back_to_bar_date_when_stale():
    d = {**DATA, "snapshot_kst": "2026-10-13T07:07"}
    # 모든 봉이 10/2~10/5라 수집일(10/13)과 4일 넘게 차이 → 수집 시각이 아니라 봉 날짜
    line = render._basis_line(d)
    assert "10/13 07시" not in line and "원/달러•DXY•WTI 10/5" in line


def test_without_snapshot_behaves_as_before():
    assert render._basis_line(DATA) == "*기준: 원/달러•DXY•WTI 10/5 / 금리•달러/엔 10/2"


# ---- 뉴스 원문 링크 ----
def with_urls():
    d = {**DATA}
    d["news_intl"] = [{"id": 1, "source": "CNBC Economy", "title": "Jobs rose 29,000", "summary": "", "url": "https://cnbc.test/a?x=1&y=2"}]
    d["news_kr"] = [{"id": 2, "source": "한국경제", "title": "외국인 코스피 20조 매도", "summary": "", "url": "https://hk.test/b"}]
    return d


def test_news_url_is_printed_right_below_the_bullet_as_plain_text():
    lines = render.render(with_urls(), PICKS).split("\n")
    i = lines.index("• 미 9월 고용 2.9만 명 증가 (CNBC Economy)")
    assert lines[i + 1] == "  https://cnbc.test/a?x=1&y=2"      # 이스케이프 없이 원문 그대로
    j = lines.index("• 외국인 20조 순매도 (한국경제)")
    assert lines[j + 1] == "  https://hk.test/b"


def test_links_can_be_turned_off_and_missing_url_adds_nothing():
    out = render.render(with_urls(), PICKS, show_links=False)
    assert "https://" not in out
    no_url = {**DATA}  # DATA의 뉴스에는 url이 없음
    assert "http" not in render.render(no_url, PICKS)


def test_urls_never_reach_the_llm_and_do_not_pollute_number_check():
    payload = build_input.llm_payload(with_urls())
    assert all("url" not in n for n in payload["news_intl"] + payload["news_kr"])
    # 주소 속 숫자(예: ?x=1)가 '기사에 있는 숫자'로 취급되어 환각 숫자를 통과시키면 안 된다
    d = with_urls()
    d["news_intl"][0]["url"] = "https://x.test/9999.99"
    assert verify.find_unverified("가짜 수치 9,999.99", build_input.llm_payload(d)) == ["9,999.99"]
