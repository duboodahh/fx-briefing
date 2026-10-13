"""수집된 JSON 3개(market/rates/context)를 하나로 합친다. 숫자는 여기서 건드리지 않는다.

반환 dict 중 LLM에는 뉴스(news_intl/news_kr)만 전달하고, 시세·금리·일정은 템플릿(render)이 그대로 쓴다.
"""
import json
from datetime import datetime
from pathlib import Path

from src.collect import events as events_mod
from src.collect import market_calendar

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
WEEKDAYS = "월화수목금토일"

NEWS_PER_SOURCE = 8   # 한 매체가 입력을 독점하지 않도록
NEWS_MAX_TOTAL = {"intl": 36, "kr": 24}
SUMMARY_CHARS = 200


def _load(name):
    path = DATA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def select_news(items, max_total=60, id_start=1):
    """매체별 최신 NEWS_PER_SOURCE개만 남기고, 전체를 최신순으로 max_total개까지. id는 id_start부터 부여."""
    count, picked = {}, []
    for it in sorted(items, key=lambda x: x["published"], reverse=True):
        if count.get(it["source"], 0) >= NEWS_PER_SOURCE:
            continue
        count[it["source"]] = count.get(it["source"], 0) + 1
        picked.append(it)
    picked = picked[:max_total]
    return [
        {
            "id": id_start + i,
            "source": it["source"],
            "title": it["title"],
            "summary": it["summary"][:SUMMARY_CHARS],
            "published_utc": it["published"],
            "url": it.get("link", ""),  # 원문 링크: 렌더링에서만 쓰고 LLM에는 주지 않는다
        }
        for i, it in enumerate(picked)
    ]


def build(today=None):
    market, rates, context = _load("market_data.json"), _load("rates_data.json"), _load("context_data.json")
    today = today or events_mod.today_kst()
    issues = []

    markets, snapshot_kst = {}, None
    if market:
        snapshot_kst = (
            datetime.fromisoformat(market["generated_at"]).astimezone(events_mod.KST).strftime("%Y-%m-%dT%H:%M")
        )
        for key, v in market["indicators"].items():
            if "error" in v:
                issues.append(f"{v['name']}: 수집 실패")
            else:
                markets[key] = {k: v[k] for k in ("name", "last", "change", "change_pct", "asof")}
    else:
        issues.append("시장 지표 파일 없음")

    yields, spreads = {}, {}
    if rates:
        yields = {k: {x: v[x] for x in ("name", "last", "change_bp", "asof")} for k, v in rates["yields"].items()}
        spreads = {k: {x: v[x] for x in ("name", "last_bp", "change_bp", "asof")} for k, v in rates["spreads"].items()}
        issues += [f"{k}: {msg}" for k, msg in rates["errors"].items()]
    else:
        issues.append("금리 파일 없음")

    news_intl, news_kr = [], []
    if context:
        items = context["news"]
        news_intl = select_news([i for i in items if i.get("region") == "intl"], NEWS_MAX_TOTAL["intl"], 1)
        news_kr = select_news(
            [i for i in items if i.get("region") == "kr"], NEWS_MAX_TOTAL["kr"], len(news_intl) + 1
        )
        issues += [f"뉴스 {k}: {msg}" for k, msg in context["errors"].items()]
    else:
        issues.append("뉴스 파일 없음")

    return {
        "today_kst": today.isoformat(),
        "weekday": WEEKDAYS[today.weekday()],
        "markets": markets,
        "snapshot_kst": snapshot_kst,  # 환율·유가 등 시세를 수집한 시각(KST)
        "rates": {"yields": yields, "spreads": spreads},
        "events": events_mod.upcoming(events_mod.load_events(), today, days=14),
        "calendar": market_calendar.status(today),
        "news_intl": news_intl,
        "news_kr": news_kr,
        "data_issues": issues,
    }


def llm_payload(data):
    """LLM에 전달하는 부분: 오늘 날짜와 뉴스 후보만. (수치는 코드가 채우므로 주지 않는다.)"""
    def strip(items):
        return [{k: v for k, v in n.items() if k != "url"} for n in items]

    return {
        "today_kst": data["today_kst"],
        "weekday": data["weekday"],
        "news_intl": strip(data["news_intl"]),
        "news_kr": strip(data["news_kr"]),
    }
