from datetime import date

import pytest
import requests

from src.overnight import collect, render


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("테스트에서 실제 네트워크 호출이 발생함")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests, "post", boom)


def test_session_date_tuesday_is_monday_and_monday_is_friday():
    assert collect.us_session_date(date(2026, 10, 13)) == date(2026, 10, 12)   # 화 → 월(컬럼버스데이, 주식은 개장)
    assert collect.us_session_date(date(2026, 10, 12)) == date(2026, 10, 9)    # 월 → 금
    assert collect.us_session_date(date(2026, 11, 27)) == date(2026, 11, 25)   # 11/26 추수감사절(휴장) 건너뜀


def fake_history(bars):
    return lambda ticker: [(date.fromisoformat(d), v) for d, v in bars]


ITEM = {"key": "spx", "name": "S&P500", "ticker": "^GSPC", "decimals": 2}


def test_close_pair_uses_only_bars_up_to_session(monkeypatch):
    monkeypatch.setattr(collect, "_history", fake_history([("2026-10-08", 7765.36), ("2026-10-09", 7811.54),
                                                           ("2026-10-12", 7807.24), ("2026-10-13", 7790.0)]))
    r = collect.close_pair(ITEM, date(2026, 10, 12))      # 10/13 봉은 아직 진행 중이므로 제외
    assert (r["last"], r["prev"], r["asof"], r["stale"]) == (7807.24, 7811.54, "2026-10-12", False)
    assert r["change"] == -4.3 and r["change_pct"] == -0.06


def test_close_pair_flags_stale_when_session_bar_missing(monkeypatch):
    monkeypatch.setattr(collect, "_history", fake_history([("2026-10-08", 158.06), ("2026-10-09", 158.06)]))
    r = collect.close_pair({**ITEM, "ticker": "JPY=X"}, date(2026, 10, 12))
    assert r["stale"] is True and r["asof"] == "2026-10-09"


def test_close_pair_isolates_failure(monkeypatch):
    monkeypatch.setattr(collect, "_history", lambda t: (_ for _ in ()).throw(RuntimeError("야후 오류")))
    assert "error" in collect.close_pair(ITEM, date(2026, 10, 12))


def test_crosscheck_ok_mismatch_and_lag(monkeypatch):
    row = {"last": 7807.24, "asof": "2026-10-12"}
    monkeypatch.setattr(collect.fred, "fetch_series", lambda *a, **k: [("2026-10-09", 7811.54), ("2026-10-12", 7807.24)])
    assert collect.crosscheck(row, "SP500", "k", date(2026, 10, 12), 0.1)["status"] == "ok"
    monkeypatch.setattr(collect.fred, "fetch_series", lambda *a, **k: [("2026-10-12", 7900.0)])
    assert collect.crosscheck(row, "SP500", "k", date(2026, 10, 12), 0.1)["status"] == "mismatch"
    monkeypatch.setattr(collect.fred, "fetch_series", lambda *a, **k: [("2026-10-09", 7811.54)])
    assert collect.crosscheck(row, "SP500", "k", date(2026, 10, 12), 0.1)["status"] == "FRED 미반영"


def test_treasury_row_marks_closed_on_bond_holiday(monkeypatch):
    monkeypatch.setattr(collect.treasury, "fetch_series", lambda *a, **k: [("2026-10-08", 4.75), ("2026-10-09", 4.80)])
    item = {"key": "us2y", "name": "미 2Y", "field": "BC_2YEAR"}
    r = collect.treasury_row(item, date(2026, 10, 12))
    assert r["status"] == "closed" and r["asof"] == "2026-10-09"
    monkeypatch.setattr(collect.treasury, "fetch_series", lambda *a, **k: [("2026-10-09", 4.80), ("2026-10-12", 4.85)])
    r = collect.treasury_row(item, date(2026, 10, 12))
    assert r["status"] == "ok" and r["change_bp"] == 5.0


DATA = {
    "today_kst": "2026-10-13", "session_date": "2026-10-12",
    "indices": [
        {"key": "dji", "name": "다우", "last": 51850.55, "change_pct": 0.38},
        {"key": "rut", "name": "러셀2000", "last": 2794.48, "change_pct": -0.45},
    ],
    "rates": [
        {"key": "us2y", "name": "미 2Y", "last": 4.7869, "change_bp": 0.0, "status": "ok"},
        {"key": "us10y", "name": "미 10Y", "last": 5.2378, "change_bp": -2.04, "status": "ok"},
    ],
    "fx": [
        {"key": "dxy", "name": "DXY", "last": 102.58, "change": 0.37, "change_pct": 0.36},
        {"key": "eurusd", "name": "유로/달러", "last": 1.1152, "change": -0.002, "change_pct": -0.18},
        {"key": "usdkrw", "name": "달러/원", "last": 1335.10, "change": -7.7, "change_pct": -0.57},
        {"key": "usdjpy", "name": "달러/엔", "error": "RuntimeError: x"},
    ],
    "energy": [{"key": "wti", "name": "WTI", "last": 93.74, "change": 1.89, "change_pct": 2.06}],
    "issues": ["달러/엔: 기준 세션 봉 없음(최근 봉 2026-10-09)"],
}


def test_render_structure_and_formats():
    out = render.render(DATA)
    lines = out.split("\n")
    assert lines[0] == "Overnight Market Briefing"
    assert lines[1] == "2026.10.13(화) | 미국장 10/12(월) 마감 기준"
    assert lines.index("[증시]") < lines.index("[FICC]")
    assert "• 다우 51,850.55 (+0.38%)" in lines and "• 러셀2000 2,794.48 (-0.45%)" in lines
    assert "• 미 2Y 4.79% (UNCH)" in lines and "• 미 10Y 5.24% (-2.0bp)" in lines
    assert "• DXY 102.58 (+0.36%)" in lines and "• 유로/달러 1.1152 (-0.18%)" in lines
    assert "• 달러/원 1,335.10원 (-7.70원)" in lines and "• WTI 93.74달러 (+2.06%)" in lines
    assert "• 달러/엔 수집 실패" in lines
    assert any(l.startswith("*지수 종가 야후") for l in lines)
    assert not any("기준 세션 봉 없음" in l for l in lines)    # 개별 주의 줄 대신 ※ 한 줄로 합침


def test_stale_rows_get_mark_and_single_note():
    d = {**DATA, "fx": [{**DATA["fx"][0], "stale": True, "asof": "2026-10-09"}] + DATA["fx"][1:]}
    out = render.render(d)
    assert "• DXY 102.58 (+0.36%) ※10/9" in out
    assert out.count("※ 표시는") == 1


def test_mismatch_is_reported_in_both_languages():
    idx = [{**DATA["indices"][0], "check": {"status": "mismatch", "diff_pct": 0.4}}] + DATA["indices"][1:]
    d = {**DATA, "indices": idx}
    assert "*주의: 다우: 야후·FRED 종가 불일치 (0.4%)" in render.render(d)
    assert "*Note: 다우: Yahoo vs FRED close mismatch (0.4%)" in render.render(d, lang="en")   # name_en 없으면 한글 이름 유지


def test_render_bond_holiday_collapses_rates_to_one_line():
    d = {**DATA, "rates": [{**r, "status": "closed"} for r in DATA["rates"]]}
    out = render.render(d)
    assert "• 미국 채권시장 휴장 (10/12(월))" in out and "미 2Y" not in out


# ---- 환율: 미국 장 종료(16:00 ET) 시점 값 ----
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def hb(day, hour, v):
    return (datetime.fromisoformat(f"{day}T{hour:02d}:00").replace(tzinfo=ET), v)


def test_close_kst_hour_follows_daylight_saving():
    assert collect.close_kst_hour(date(2026, 10, 12)) == 5     # 미국 서머타임: 16:00 ET = 05:00 KST
    assert collect.close_kst_hour(date(2026, 11, 2)) == 6      # 11/1 서머타임 종료 후: 06:00 KST


def test_us_close_pair_uses_15h_bar_and_previous_us_session(monkeypatch):
    bars = [hb("2026-10-09", 15, 1341.10), hb("2026-10-09", 16, 1340.02),   # 금: 16시 봉은 장 종료 이후라 무시
            hb("2026-10-12", 14, 1330.0), hb("2026-10-12", 15, 1334.58), hb("2026-10-12", 23, 1343.18)]
    monkeypatch.setattr(collect, "_hourly", lambda t: bars)
    item = {"key": "usdkrw", "name": "달러/원", "ticker": "KRW=X", "decimals": 2}
    r = collect.us_close_pair(item, date(2026, 10, 12))
    assert (r["last"], r["prev"], r["change"]) == (1334.58, 1341.10, -6.52)
    assert (r["asof"], r["prev_asof"], r["stale"]) == ("2026-10-12", "2026-10-09", False)


def test_us_close_pair_falls_back_to_last_bar_before_16h(monkeypatch):
    # 15시 봉이 빠져 있으면 16:00 이전에 끝나는 마지막 봉(14시 봉)을 쓴다
    bars = [hb("2026-10-09", 15, 100.0), hb("2026-10-12", 14, 101.0), hb("2026-10-12", 20, 99.0)]
    monkeypatch.setattr(collect, "_hourly", lambda t: bars)
    r = collect.us_close_pair({"key": "dxy", "name": "DXY", "ticker": "X", "decimals": 2}, date(2026, 10, 12))
    assert r["last"] == 101.0 and r["change_pct"] == 1.0


def test_us_close_pair_error_when_session_bars_missing(monkeypatch):
    monkeypatch.setattr(collect, "_hourly", lambda t: [hb("2026-10-09", 15, 100.0)])
    assert "error" in collect.us_close_pair({"key": "dxy", "name": "DXY", "ticker": "X", "decimals": 2}, date(2026, 10, 12))
