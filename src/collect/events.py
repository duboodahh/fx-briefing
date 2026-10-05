"""config/events.yaml을 읽어 한국시간(KST) 기준으로 다가오는 일정을 골라낸다."""
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

KST = ZoneInfo("Asia/Seoul")
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "events.yaml"
COUNTRY_TZ = {"US": "America/New_York", "KR": "Asia/Seoul"}


def load_events(path=DEFAULT_PATH):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["events"]


def _to_kst(ev):
    """이벤트를 (KST 날짜, KST 시각 또는 None)으로 변환. 시각이 없는 종일 일정은 현지 날짜를 그대로 쓴다."""
    d = date.fromisoformat(ev["date"])
    if not ev.get("time"):
        return d, None
    tz = ZoneInfo(ev.get("tz") or COUNTRY_TZ[ev["country"]])
    local = datetime.combine(d, time.fromisoformat(ev["time"]), tzinfo=tz)
    kst = local.astimezone(KST)
    return kst.date(), kst.strftime("%H:%M")


def upcoming(events, today, days=7):
    """today(KST 날짜)부터 days일 이내의 일정을 시간순으로 반환. days_left 0=오늘, 1=내일."""
    out = []
    for ev in events:
        kst_date, kst_time = _to_kst(ev)
        days_left = (kst_date - today).days
        if 0 <= days_left <= days:
            out.append(
                {
                    "name": ev["name"],
                    "country": ev["country"],
                    "impact": ev.get("impact", "medium"),
                    "kst_date": kst_date.isoformat(),
                    "kst_time": kst_time,  # None이면 종일 일정
                    "days_left": days_left,
                    "source": ev.get("source"),
                }
            )
    return sorted(out, key=lambda e: (e["kst_date"], e["kst_time"] or "", e["name"]))


def today_kst():
    return datetime.now(KST).date()
