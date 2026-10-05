"""미 재무부 공식 일일 수익률 곡선(XML). 당일 마감값이 올라오고 API 키가 필요 없다.

FRED(DGS*)는 같은 데이터를 하루 늦게 재배포하기 때문에, 아침 브리핑에서는 이쪽이 더 최신이다.
"""
import xml.etree.ElementTree as ET
from datetime import date

import requests

URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value_month={ym}"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (fx-briefing personal project)"}


def parse_month(xml_bytes, field):
    """한 달치 XML에서 [(YYYY-MM-DD, 값(%)), ...]을 뽑는다. 값이 없는 날(N/A)은 건너뛴다."""
    out = []
    for e in ET.fromstring(xml_bytes).iter():
        if not e.tag.endswith("}properties"):
            continue
        row = {c.tag.split("}")[1]: (c.text or "").strip() for c in e}
        d, v = row.get("NEW_DATE", "")[:10], row.get(field, "")
        if d and v and v.upper() != "N/A":
            out.append((d, float(v)))
    return sorted(out)


def _month_start(today, back):
    y, m = today.year, today.month - back
    while m < 1:
        y, m = y - 1, m + 12
    return f"{y}{m:02d}"


def fetch_series(field, n=10, today=None):
    """최근 관측치 n개 이하를 오름차순으로 반환. 월초에는 전달까지 이어서 가져온다."""
    today = today or date.today()
    obs = []
    for back in (0, 1):
        try:
            r = requests.get(URL.format(ym=_month_start(today, back)), headers=HEADERS, timeout=20)
        except requests.RequestException as e:
            raise RuntimeError(f"Treasury 요청 실패 ({type(e).__name__})") from None
        if r.status_code != 200:
            raise RuntimeError(f"Treasury HTTP {r.status_code}")
        try:
            obs = parse_month(r.content, field) + obs
        except ET.ParseError:
            raise RuntimeError("Treasury XML 파싱 실패") from None
        if len(obs) >= n:
            break
    if len(obs) < 2:
        raise RuntimeError(f"Treasury {field}: 유효 관측치 부족 ({len(obs)}개)")
    return obs[-n:]
