"""한국(XKRX)·미국(XNYS) 거래일 캘린더로 '오늘 브리핑에 새 시장 데이터가 있는지'를 판단한다.

기준: 전 영업일(직전 평일)부터 어제까지의 날짜 구간에 해당 시장의 거래일이 하나라도 있으면 새 데이터가 있다.
 - 월요일 아침: 구간 = 금~일 → 금요일 거래분이 새 데이터 (정상 발송)
 - 화요일 아침: 구간 = 월 → 월요일이 한국 휴장이면 한국은 새 데이터 없음
 - 구간 안에 한국·미국 모두 거래일이 없으면 보낼 것이 없으므로 skip

미국 주식시장 캘린더(XNYS)는 채권시장만 쉬는 날(컬럼버스데이, 재향군인의 날)을 반영하지 않는다.
그런 날은 미 재무부 데이터에 그날 값이 없어, 하단 '*기준' 줄의 날짜로만 드러난다.
"""
from datetime import timedelta

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
    out = {"window": [d.isoformat() for d in days]}
    for key in _CODES:
        out[f"{key}_new"] = any(_is_session(key, d) for d in days)
        out[f"{key}_closed"] = [d.isoformat() for d in days if d.weekday() < 5 and not _is_session(key, d)]
    out["skip"] = not out["kr_new"] and not out["us_new"]
    return out
