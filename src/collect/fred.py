"""FRED API에서 일별 시계열을 가져온다. (미 재무부 수익률 등)

API 키가 URL에 포함되므로, 예외 메시지에 URL이 섞여 출력되지 않게 직접 메시지를 만든다.
"""
import requests

URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_series(series_id, api_key, n=10):
    """최근 유효 관측치 n개를 [(날짜, 값), ...] 오름차순으로 반환. 결측('.')은 건너뛴다."""
    try:
        r = requests.get(
            URL,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": n * 2,  # 결측치 여유분
            },
            timeout=20,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"FRED 요청 실패 ({type(e).__name__})") from None
    if r.status_code != 200:
        raise RuntimeError(f"FRED HTTP {r.status_code}")

    obs = [(o["date"], float(o["value"])) for o in r.json()["observations"] if o["value"] != "."]
    if len(obs) < 2:
        raise RuntimeError(f"FRED {series_id}: 유효 관측치 부족 ({len(obs)}개)")
    return sorted(obs[:n])
