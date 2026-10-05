"""2단계: 미국(재무부, 예비 FRED)·한국(ECOS) 금리를 수집하고 스프레드를 계산해 data/rates_data.json으로 저장."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.analyze import metrics
from src.collect import ecos, fred, treasury

ROOT = Path(__file__).parent
CONFIG = ROOT / "config" / "indicators.yaml"
OUT = ROOT / "data" / "rates_data.json"

# (결과 키, 표시명, a, b) → a - b
SPREADS = [
    ("us_curve_10y2y", "미국 장단기차 (10Y-2Y)", "us10y", "us2y"),
    ("kr_curve_10y3y", "한국 장단기차 (10Y-3Y)", "kr10y", "kr3y"),
    ("kr_us_10y", "한미 10년 금리차 (KR-US)", "kr10y", "us10y"),
    ("kr_us_short", "한미 단기 금리차 (국고3Y-UST2Y)", "kr3y", "us2y"),
]


def fetch_us(item):
    """재무부 → 실패 시 FRED. 반환: (시계열, 사용한 소스)."""
    try:
        return treasury.fetch_series(item["treasury_field"]), "treasury.gov"
    except RuntimeError as first_error:
        key = os.environ.get("FRED_API_KEY")
        if not key:
            raise RuntimeError(f"{first_error}; FRED 키 없음") from None
        try:
            return fred.fetch_series(item["fred_series"], key), "FRED(예비, 1영업일 지연 가능)"
        except RuntimeError as second_error:
            raise RuntimeError(f"{first_error}; {second_error}") from None


def collect(cfg):
    load_dotenv(ROOT / ".env")
    series, sources, errors = {}, {}, {}
    jobs = [(i, lambda i=i: fetch_us(i)) for i in cfg["us"]]
    jobs += [
        (i, lambda i=i: (ecos.fetch_series(i["stat"], i["item"], os.environ["ECOS_API_KEY"]), "ECOS"))
        for i in cfg["ecos"]
    ]
    for item, job in jobs:
        try:
            series[item["key"]], sources[item["key"]] = job()
        except Exception as e:  # 지표별로 실패를 격리 (메시지에는 키/URL이 없도록 fetch 쪽에서 처리)
            errors[item["key"]] = str(e)
    return series, sources, errors


def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["rates"]
    names = {i["key"]: i["name"] for i in cfg["us"] + cfg["ecos"]}
    series, sources, errors = collect(cfg)

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "unit": "yield %, change/spread bp",
        "yields": {k: {"name": names[k], "source": sources[k], **metrics.level_change(s)} for k, s in series.items()},
        "spreads": {},
        "errors": errors,
    }
    for key, name, a, b in SPREADS:
        if a in series and b in series:
            try:
                data["spreads"][key] = {"name": name, **metrics.spread(series[a], series[b])}
            except ValueError as e:
                data["errors"][key] = str(e)
        else:
            data["errors"][key] = "입력 시계열 누락"

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    for v in data["yields"].values():
        print(f"{v['name']:<12} {v['last']:>6.3f}%  {v['change_bp']:+.1f}bp  {v['asof']}  [{v['source']}]")
    for v in data["spreads"].values():
        print(f"{v['name']:<26} {v['last_bp']:>7.1f}bp  {v['change_bp']:+.1f}bp  {v['asof']}")
    for k, msg in data["errors"].items():
        print(f"ERROR {k}: {msg}")
    print(f"\n저장: {OUT.relative_to(ROOT)}  | 오류 {len(data['errors'])}건")


if __name__ == "__main__":
    main()
