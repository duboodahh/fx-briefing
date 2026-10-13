"""오버나잇 브리핑 실행: 수집 → 뉴스 선별·요약(Claude, 한·영) → 렌더링 → 텔레그램 전송(한국어, 영어 별도 메시지 2개).

사용:
  python -m src.overnight.main            # 수집하고 한국어·영어판을 출력, data/overnight_*.json·txt 저장 (전송 안 함)
  python -m src.overnight.main --send     # 위에 더해 텔레그램으로 한국어판 → 영어판 순서로 전송
  python -m src.overnight.main --no-llm   # Claude를 호출하지 않고 수치만 출력
  python -m src.overnight.main --force    # 새 미국 거래일이 없는 날에도 계속 진행

실패 처리: Claude 호출이 실패하면(--send일 때) 수치만 담아 보내고 종료 코드 1로 끝낸다 → 워크플로의 실패 알림이 따로 간다.
"""
import argparse
import json
import sys
from pathlib import Path

from src.brief.generate import BriefingError
from src.collect import events as events_mod
from src.collect import market_calendar
from src.overnight import collect, generate, render
from src.overnight import news as onews

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
LANGS = ("ko", "en")  # 전송 순서
EMPTY_RESULT = {"summary": {"ko": "", "en": ""}, "picks": {"equity": [], "ficc": []}, "problems": [],
                "unverified_numbers": [], "retried": False, "first_attempt": None,
                "usage": {"input_tokens": 0, "output_tokens": 0, "est_cost_usd": 0}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="텔레그램으로 전송 (기본은 전송 안 함)")
    ap.add_argument("--force", action="store_true", help="새 미국 거래일이 없는 날에도 계속 진행")
    ap.add_argument("--no-llm", action="store_true", help="Claude를 호출하지 않고 수치만 출력")
    args = ap.parse_args(argv)
    if args.send and args.no_llm:
        ap.error("--send는 --no-llm과 함께 쓸 수 없음 (뉴스가 빈 브리핑이 전송되는 것을 막기 위함)")

    today = events_mod.today_kst()
    # 직전 영업일 이후 미국 거래일이 없으면(공휴일 등) 보낼 새 데이터가 없다. 수집·API 호출 전에 종료한다.
    cal = market_calendar.status(today)
    if not cal["us_session"] and not args.force:
        print(f"발송 건너뜀: {cal['window'][0]} ~ {cal['window'][-1]} 사이에 미국 거래일이 없음")
        return

    data = collect.collect(today)
    news_data = onews.collect_news(collect.us_session_date(today))
    data["news"] = news_data

    result, degraded = None, False   # degraded: 뉴스 요약을 만들지 못해 수치만 보내는 경우
    if not args.no_llm:
        if not news_data["candidates"]:
            result, degraded = EMPTY_RESULT, bool(news_data["errors"])    # 후보가 없으면 API를 부르지 않는다
        else:
            try:
                result = generate.generate(data)
            except BriefingError as e:
                if not args.send:
                    raise
                print(f"뉴스 요약 생성 실패: {e}")
                result, degraded = EMPTY_RESULT, True

    DATA.mkdir(exist_ok=True)
    (DATA / "overnight_input.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    texts = {lang: render.render(data, result, lang=lang, news_failed=degraded) for lang in LANGS}
    for lang, text in texts.items():
        (DATA / f"overnight_{lang}.txt").write_text(text, encoding="utf-8")
    if result is not None:
        (DATA / "overnight_result.json").write_text(json.dumps({**result, "text": texts}, ensure_ascii=False, indent=1), encoding="utf-8")

    for lang, text in texts.items():
        print("=" * 60 + f"  [{lang.upper()}]")
        print(text)
    print("=" * 60)
    print(f"길이 한국어 {len(texts['ko'])}자 / 영어 {len(texts['en'])}자 | 기준 세션 {data['session_date']} | 이슈 {len(data['issues'])}건")
    print(f"뉴스 후보: 수집 {news_data['collected']}건(최근 {news_data['window_hours']}시간) | 원문 링크 없어 제외 {news_data['excluded_no_original']}건 | 후보 {len(news_data['candidates'])}건")
    for k, v in news_data["errors"].items():
        print(f"  피드 오류 {k}: {v}")
    for issue in data["issues"]:
        print(f"  - {issue}")
    if result is not None and result["usage"]["input_tokens"]:
        u = result["usage"]
        print(f"토큰 입력 {u['input_tokens']:,} / 출력 {u['output_tokens']:,} | 추정 비용 ${u['est_cost_usd']}{' | 재시도 1회' if result['retried'] else ''}")
        if result.get("first_attempt"):
            print(f"첫 시도에서 걸린 문제(재시도함): {result['first_attempt']}")
        if result["problems"] or result["unverified_numbers"]:
            print(f"경고: id 문제 {result['problems']}, 근거 없는 숫자 {result['unverified_numbers']}")
        else:
            print("검증: 통과 (기사 id 유효, 요약 속 숫자는 모두 시세 요약·기사에 근거)")

    if args.send:
        from src.send import telegram

        for lang in LANGS:       # 한국어판 먼저, 이어서 영어판
            n = telegram.send(texts[lang])
            print(f"텔레그램 전송 완료 [{lang}] (메시지 {n}개)")

    if degraded:  # 수치는 보냈지만 비정상 실행이므로 종료 코드 1 → 워크플로의 실패 알림이 따로 간다
        sys.exit(1)


if __name__ == "__main__":
    main()
