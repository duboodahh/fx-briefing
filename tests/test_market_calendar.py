from datetime import date

from src.brief import render
from src.collect import market_calendar as mc
from test_render_pipeline import DATA, PICKS


def test_window_monday_covers_friday_to_sunday():
    assert [d.isoformat() for d in mc.window(date(2026, 10, 5))] == ["2026-10-02", "2026-10-03", "2026-10-04"]


def test_window_tuesday_is_just_monday():
    assert [d.isoformat() for d in mc.window(date(2026, 10, 6))] == ["2026-10-05"]


def test_holiday_monday_then_tuesday_hides_only_korea():
    # 2026-10-05(월)은 한국 대체공휴일 → 10/6(화) 아침에는 한국만 새 데이터가 없다
    s = mc.status(date(2026, 10, 6))
    assert s["kr_new"] is False and s["us_new"] is True and s["skip"] is False
    assert s["kr_closed"] == ["2026-10-05"] and s["us_closed"] == []


def test_monday_after_normal_friday_is_normal():
    s = mc.status(date(2026, 10, 5))
    assert s["kr_new"] and s["us_new"] and not s["skip"]


def test_korean_holiday_morning_still_has_new_data():
    # 10/9(금)은 한국 휴일이지만 구간은 [10/8] → 한국·미국 모두 새 데이터가 있어 발송한다
    s = mc.status(date(2026, 10, 9))
    assert s["kr_new"] and s["us_new"] and not s["skip"]


def test_monday_after_korean_friday_holiday_hides_korea():
    s = mc.status(date(2026, 10, 12))          # 구간 [금 10/9(한국 휴장), 토, 일]
    assert s["kr_new"] is False and s["us_new"] is True
    assert s["kr_closed"] == ["2026-10-09"]


def test_both_closed_skips():
    s = mc.status(date(2026, 12, 28))          # 구간 [금 12/25(양국 휴장), 토, 일]
    assert s["skip"] is True and s["kr_closed"] == ["2026-12-25"] and s["us_closed"] == ["2026-12-25"]


def test_day_after_us_thanksgiving_hides_us():
    s = mc.status(date(2026, 11, 27))          # 구간 [목 11/26]: 미국 휴장, 한국 개장
    assert s["us_new"] is False and s["kr_new"] is True and s["us_closed"] == ["2026-11-26"]


def test_render_hides_korean_rates_but_keeps_us_and_fx():
    d = {**DATA, "calendar": {"kr_new": False, "us_new": True, "kr_closed": ["2026-10-05"], "us_closed": []}}
    out = render.render(d, PICKS)
    assert "• 한국 채권시장 휴장 (10/5)" in out
    assert "국고채 3Y" not in out and "한미 10Y 금리차" not in out    # 한국 수치·한미 금리차 숨김
    assert "• 미국 국채 10Y 5.28% (+4.0bp)" in out                   # 미국 수치는 그대로
    assert "• 원/달러 1,345.08원 (-15.51원)" in out                    # 환율은 해외 시세라 유지
    assert "국고채" not in out.split("*기준:")[1]                       # 기준 줄에서도 한국 금리 날짜 제외


def test_render_hides_us_rates_and_cross_spread_on_us_holiday():
    d = {**DATA, "calendar": {"kr_new": True, "us_new": False, "kr_closed": [], "us_closed": ["2026-11-26"]}}
    out = render.render(d, PICKS)
    assert "• 미국 채권시장 휴장 (11/26)" in out
    assert "미국 국채 10Y" not in out and "한미 10Y 금리차" not in out
    assert "• 국고채 3Y 3.94% (-7.3bp)" in out


def test_render_without_calendar_info_shows_everything():
    out = render.render(DATA, PICKS)
    assert "휴장" not in out and "한미 10Y 금리차" in out
