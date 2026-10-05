"""한국은행 ECOS API에서 일별 시계열을 가져온다. (국고채 금리 등)

API 키가 URL 경로에 포함되므로, 예외 메시지에 URL이 섞여 출력되지 않게 직접 메시지를 만든다.
"""
from datetime import date, timedelta

import requests

URL = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/{n}/{stat}/D/{start}/{end}/{item}"


def fetch_series(stat, item, api_key, n=10, lookback_days=30):
    """최근 관측치 n개를 [(YYYY-MM-DD, 값), ...] 오름차순으로 반환."""
    end = date.today()
    url = URL.format(
        key=api_key,
        n=100,
        stat=stat,
        start=(end - timedelta(days=lookback_days)).strftime("%Y%m%d"),
        end=end.strftime("%Y%m%d"),
        item=item,
    )
    try:
        r = requests.get(url, timeout=20)
    except requests.RequestException as e:
        raise RuntimeError(f"ECOS 요청 실패 ({type(e).__name__})") from None
    if r.status_code != 200:
        raise RuntimeError(f"ECOS HTTP {r.status_code}")

    body = r.json()
    rows = body.get("StatisticSearch", {}).get("row")
    if not rows:
        msg = body.get("RESULT", {}).get("MESSAGE", "응답에 데이터 없음")
        raise RuntimeError(f"ECOS {stat}/{item}: {msg}")

    obs = []
    for row in rows:
        t = row["TIME"]
        if row["DATA_VALUE"] not in ("", None):
            obs.append((f"{t[:4]}-{t[4:6]}-{t[6:8]}", float(row["DATA_VALUE"])))
    if len(obs) < 2:
        raise RuntimeError(f"ECOS {stat}/{item}: 유효 관측치 부족 ({len(obs)}개)")
    return sorted(obs)[-n:]
