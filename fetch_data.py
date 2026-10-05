"""1단계: yfinance로 FX/원자재/위험선호 지표의 최근 종가와 전일 대비 변화를 수집해 data/market_data.json으로 저장.

숫자(변동폭·변동률)는 여기서 계산한다. 이후 LLM에는 이 JSON만 전달한다.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml
import yfinance as yf

ROOT = Path(__file__).parent
CONFIG = ROOT / "config" / "indicators.yaml"
OUT = ROOT / "data" / "market_data.json"


def fetch_one(item):
    """종가 2개(최근, 직전)를 가져와 변화량을 계산. 실패하면 error만 담아 반환."""
    result = {"name": item["name"], "ticker": item["ticker"], "group": item["group"]}
    try:
        hist = yf.Ticker(item["ticker"]).history(period="10d", auto_adjust=False)
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            raise ValueError(f"종가 데이터 부족 ({len(closes)}개)")
        last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
        d = item["decimals"]
        result.update(
            {
                "last": round(last, d),
                "prev": round(prev, d),
                "change": round(last - prev, d),
                "change_pct": round((last / prev - 1) * 100, 2),
                "asof": closes.index[-1].strftime("%Y-%m-%d"),
                "prev_asof": closes.index[-2].strftime("%Y-%m-%d"),
            }
        )
    except Exception as e:  # yfinance는 비공식이라 지표별로 실패를 격리한다
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def main():
    items = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["market"]
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "indicators": {item["key"]: fetch_one(item) for item in items},
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    for key, v in data["indicators"].items():
        if "error" in v:
            print(f"{v['name']:<8} ERROR  {v['error']}")
        else:
            print(f"{v['name']:<8} {v['last']:>10}  {v['change']:+}  ({v['change_pct']:+.2f}%)  {v['asof']}")
    failed = [k for k, v in data["indicators"].items() if "error" in v]
    print(f"\n저장: {OUT.relative_to(ROOT)}  | 성공 {len(items) - len(failed)}/{len(items)}")


if __name__ == "__main__":
    main()
