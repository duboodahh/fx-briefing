"""3단계: 이벤트 캘린더(향후 7일, KST 기준)와 영문 RSS 헤드라인을 수집해 data/context_data.json으로 저장."""
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.collect import events, news

ROOT = Path(__file__).parent
CONFIG = ROOT / "config" / "indicators.yaml"
OUT = ROOT / "data" / "context_data.json"


def main():
    today = events.today_kst()
    upcoming = events.upcoming(events.load_events(), today, days=7)

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["news"]
    items, errors = news.collect(cfg["feeds"], max_age_hours=cfg["max_age_hours"])

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today_kst": today.isoformat(),
        "events": upcoming,
        "news": items,
        "errors": errors,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"기준일(KST): {today}  | 향후 7일 이벤트 {len(upcoming)}건")
    for e in upcoming:
        print(f"  D-{e['days_left']} {e['kst_date']} {e['kst_time'] or '종일'}  [{e['country']}] {e['name']}")
    by_src = {}
    for it in items:
        key = f"{it['region']}/{it['source']}"
        by_src[key] = by_src.get(key, 0) + 1
    print(f"뉴스 {len(items)}건 (최근 {cfg['max_age_hours']}시간): {by_src}")
    for it in items[:5]:
        print(f"  - [{it['source']}] {it['title'][:90]}")
    for k, msg in errors.items():
        print(f"ERROR {k}: {msg}")
    print(f"\n저장: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
