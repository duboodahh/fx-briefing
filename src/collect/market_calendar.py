"""한국(XKRX)·미국(XNYS) 거래일 캘린더로 '오늘 브리핑에 새 시장 데이터가 있는지'를 판단한다.

기준: 전 영업일(직전 평일)부터 어제까지의 날짜 구간에 해당 시장의 거래일이 하나라도 있으면 새 데이터가 있다.
 - 월요일 아침: 구간 = 금~일 → 금요일 거래분이 새 데이터 (정상 발송)
 - 화요일 아침: 구간 = 월 → 월요일이 한국 휴장이면 한국은 새 데이터 없음
 - 구간 안에 한국·미국 모두 거래일이 없으면 보낼 것이 없으므로 skip

미국은 '주식시장'과 '채권시장' 휴장일이 다르다. 컬럼버스데이(10월 둘째 월요일)와 재향군인의 날(11/11)은
주식시장은 열지만 채권시장(미 재무부 수익률 발표)은 쉰다. 그래서 금리용 플래그(us_new)는 채권 휴장일을 따로 반영하고,
skip 판단(us_session)은 주식시장 거래일 기준으로 한다.
"""
from datetime import date, timedelta

import exchange_calendars as xcals
import pandas as pd

_CODES = {"kr": "XKRX", "us": "XNYS"}
_cache = {}


def _cal(key):
    if key not in _cache:
        _cache[key] = xcals.get_calendar(_CODES[key])
    return _cache[key]


def _is_session(key, d):
    try:
        return bool(_cal(key).is_session(pd.Timestamp(d)))
    except Exception:  # 캘린더 범위를 벗어나는 등 판단 불가하면 '개장'으로 간주해 브리핑이 막히지 않게 한다
        return True


def us_bond_only_holiday(d):
    """주식시장은 열지만 채권시장은 쉬는 날: 컬럼버스데이(10월 둘째 월요일), 재향군인의 날(11/11).

    11/11이 토요일이면 금요일에 쉬지 않고(채권시장은 토요일 휴일을 앞당겨 쉬지 않는다), 일요일이면 월요일에 쉰다.
    """
    if d.month == 10 and d.weekday() == 0 and 8 <= d.day <= 14:
        return True
    if d.month == 11:
        vd = date(d.year, 11, 11)
        if vd.weekday() == 6:
            vd += timedelta(days=1)
        return d == vd and vd.weekday() < 5
    return False


def previous_weekday(d):
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def window(today):
    """[직전 평일, ..., 어제] 날짜 목록. (직전 평일의 장은 그날 아침 브리핑 이후에 열렸으므로 포함)"""
    prev = previous_weekday(today)
    return [prev + timedelta(days=i) for i in range((today - prev).days)]


def status(today):
    days = window(today)
    weekdays = [d for d in days if d.weekday() < 5]
    out = {"window": [d.isoformat() for d in days]}

    kr_open = [d for d in days if _is_session("kr", d)]
    out["kr_new"] = bool(kr_open)
    out["kr_closed"] = [d.isoformat() for d in weekdays if not _is_session("kr", d)]

    us_stock_open = [d for d in days if _is_session("us", d)]
    us_rates_open = [d for d in us_stock_open if not us_bond_only_holiday(d)]
    out["us_session"] = bool(us_stock_open)            # 주식시장 기준 (skip 판단용)
    out["us_new"] = bool(us_rates_open)                # 채권시장 기준 (금리 수치 표시용)
    out["us_closed"] = [d.isoformat() for d in weekdays if d not in us_rates_open]

    out["skip"] = not out["kr_new"] and not out["us_session"]
    return out
