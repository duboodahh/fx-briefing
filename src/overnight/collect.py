"""오버나잇(미국장 마감) 브리핑용 수치 수집. 숫자는 코드가 수집·계산하고, 이후 LLM은 숫자를 건드리지 않는다.

기준 세션: 브리핑 날짜(KST) 기준 '어제까지의 마지막 미국 주식시장 거래일'.
 - 화요일 아침 → 월요일 세션, 월요일 아침 → 금요일 세션
 - 미국 장은 KST 05:00(서머타임 종료 후 06:00)에 끝나므로 07:00 실행이면 일봉이 확정되어 있다.
"""
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import yaml
import yfinance as yf

from src.collect import fred, treasury
from src.collect import market_calendar as mc

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "overnight.yaml"
ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")


def us_session_date(today_kst):
    """어제까지의 마지막 미국 주식시장 거래일."""
    d = today_kst - timedelta(days=1)
    while not mc._is_session("us", d):
        d -= timedelta(days=1)
    return d


def previous_us_session(d):
    """d 이전의 마지막 미국 주식시장 거래일."""
    d -= timedelta(days=1)
    while not mc._is_session("us", d):
        d -= timedelta(days=1)
    return d


def close_kst_hour(session):
    """기준 세션의 미국 장 종료(16:00 ET)가 한국시간 몇 시인지. 서머타임이면 5시, 아니면 6시."""
    return datetime.combine(session, time(16, 0), ET).astimezone(KST).hour


def _hourly(ticker):
    """최근 1시간봉 [(시작시각 ET, 종가)] 오름차순. 테스트에서 이 함수를 바꿔 끼운다."""
    h = yf.Ticker(ticker).history(period="10d", interval="1h", auto_adjust=False)["Close"].dropna()
    return [(ts.tz_convert(ET).to_pydatetime(), float(v)) for ts, v in h.items()]


def _us_close_value(bars, day):
    """day의 미국 장 종료 시점(16:00 ET) 값 = 16:00 이전에 끝나는 마지막 1시간봉의 종가. 없으면 None."""
    cands = [(ts, v) for ts, v in bars if ts.date() == day and ts.hour <= 15]
    return cands[-1][1] if cands else None


def us_close_pair(item, session):
    """환율·달러지수: 기준 세션과 직전 미국 거래일의 '미국 장 종료 시점(16:00 ET)' 값으로 변화를 계산한다.

    FX는 24시간 거래라 일봉 종가(봉 경계)가 미국 장 종료와 맞지 않는다. 그래서 1시간봉에서 그 시각 값을 직접 쓴다.
    """
    out = {"key": item["key"], "name": item["name"], "name_en": item.get("name_en", item["name"])}
    try:
        bars = _hourly(item["ticker"])
        prev_day = previous_us_session(session)
        last, prev = _us_close_value(bars, session), _us_close_value(bars, prev_day)
        if last is None or prev is None:
            raise ValueError(f"{session if last is None else prev_day} 1시간봉 없음")
        nd = item["decimals"]
        out.update(
            last=round(last, nd), prev=round(prev, nd), change=round(last - prev, nd),
            change_pct=round((last / prev - 1) * 100, 2), asof=session.isoformat(), prev_asof=prev_day.isoformat(),
            stale=False, basis="us_close_16et",
        )
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _history(ticker):
    """최근 일봉 종가 시리즈 [(date, close)] 오름차순. 테스트에서 이 함수를 바꿔 끼운다."""
    h = yf.Ticker(ticker).history(period="15d", auto_adjust=False)["Close"].dropna()
    return [(d.date(), float(v)) for d, v in h.items()]


def close_pair(item, session):
    """기준 세션 이하의 마지막 두 종가로 변화를 계산한다. 반환: dict, 실패 시 error만 담는다."""
    out = {"key": item["key"], "name": item["name"], "name_en": item.get("name_en", item["name"])}
    try:
        bars = [(d, v) for d, v in _history(item["ticker"]) if d <= session]
        if len(bars) < 2:
            raise ValueError(f"종가 데이터 부족 ({len(bars)}개)")
        (pd_, prev), (d, last) = bars[-2], bars[-1]
        nd = item["decimals"]
        out.update(
            last=round(last, nd), prev=round(prev, nd), change=round(last - prev, nd),
            change_pct=round((last / prev - 1) * 100, 2), asof=d.isoformat(), prev_asof=pd_.isoformat(),
            stale=d < session,  # 기준 세션 봉이 없어 더 오래된 봉을 쓴 경우
        )
    except Exception as e:  # 야후는 비공식이라 지표별로 실패를 격리한다 (메시지에는 URL이 없다)
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def crosscheck(index_row, fred_series_id, api_key, session, tol_pct):
    """야후 종가를 FRED와 대조한다. FRED는 하루쯤 늦게 반영되므로 같은 날짜가 없으면 '미반영'으로 둔다."""
    if "error" in index_row or not api_key:
        return {"status": "n/a"}
    try:
        obs = dict(fred.fetch_series(fred_series_id, api_key, n=10))
    except RuntimeError as e:
        return {"status": "n/a", "reason": str(e)}
    ref = obs.get(index_row["asof"])
    if ref is None:
        return {"status": "FRED 미반영"}
    diff = abs(index_row["last"] / ref - 1) * 100
    return {"status": "mismatch" if diff > tol_pct else "ok", "fred": ref, "diff_pct": round(diff, 3)}


def treasury_row(item, session):
    """재무부 수익률. 기준 세션 날짜 값이 없으면(채권시장만 쉬는 날 등) closed 로 표시한다."""
    out = {"key": item["key"], "name": item["name"], "name_en": item.get("name_en", item["name"])}
    try:
        obs = [(d, v) for d, v in treasury.fetch_series(item["field"], n=12) if d <= session.isoformat()]
        if len(obs) < 2:
            raise ValueError("관측치 부족")
        (pd_, prev), (d, last) = obs[-2], obs[-1]
        out.update(last=last, prev=prev, change_bp=round((last - prev) * 100, 1), asof=d, prev_asof=pd_)
        out["status"] = "ok" if d == session.isoformat() else "closed"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def collect(today_kst, load_env=True):
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    session = us_session_date(today_kst)
    if load_env:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    fred_key = os.environ.get("FRED_API_KEY")
    tol = cfg["crosscheck_tolerance_pct"]

    indices = []
    for item in cfg["indices"]:
        row = close_pair(item, session)
        if item.get("check_fred"):
            row["check"] = crosscheck(row, item["check_fred"], fred_key, session, tol)
        indices.append(row)

    data = {
        "today_kst": today_kst.isoformat(),
        "session_date": session.isoformat(),
        "calendar": mc.status(today_kst),
        "indices": indices,
        "rates": [treasury_row(i, session) for i in cfg["rates"]],
        "close_kst_hour": close_kst_hour(session),
        "fx": [us_close_pair(i, session) for i in cfg["fx"]],
        "energy": [close_pair(i, session) for i in cfg["energy"]],
    }
    data["issues"] = (
        [f"{r['name']}: {r['error']}" for g in ("indices", "rates", "fx", "energy") for r in data[g] if "error" in r]
        + [f"{r['name']}: 야후·FRED 종가 불일치 ({r['check']['diff_pct']}%)" for r in indices if r.get("check", {}).get("status") == "mismatch"]
        + [f"{r['name']}: 기준 세션 봉 없음(최근 봉 {r['asof']})" for g in ("indices", "fx", "energy") for r in data[g] if r.get("stale")]
    )
    return data
