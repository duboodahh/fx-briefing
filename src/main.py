"""파이프라인: 수집 → 입력 조립 → 뉴스 선별(Claude) → 템플릿 렌더링. (텔레그램 전송은 5단계에서 연결)

사용:
  python -m src.main               # 새로 수집하고 브리핑 생성
  python -m src.main --no-fetch    # 저장된 data/*.json을 그대로 써서 생성 (프롬프트 조정할 때)
  python -m src.main --input-only  # API 호출 없이 입력만 data/briefing_input.json에 저장
  python -m src.main --no-llm      # API 호출 없이 뉴스 섹션을 비운 채 템플릿만 확인
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

from src.brief import build_input, generate, render

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TELEGRAM_LIMIT = 4096


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="수집을 건너뛰고 저장된 data/*.json 사용")
    ap.add_argument("--input-only", action="store_true", help="API를 호출하지 않고 입력 JSON만 저장")
    ap.add_argument("--no-llm", action="store_true", help="API를 호출하지 않고 템플릿(뉴스 비움)만 출력")
    ap.add_argument("--send", action="store_true", help="생성한 브리핑을 텔레그램으로 전송 (기본은 전송 안 함)")
    args = ap.parse_args()
    if args.send and (args.no_llm or args.input_only):
        ap.error("--send는 --no-llm / --input-only와 함께 쓸 수 없음 (뉴스가 빈 브리핑이 전송되는 것을 막기 위함)")

    if not (args.no_fetch or args.input_only or args.no_llm):
        import fetch_context
        import fetch_data
        import fetch_rates

        for mod in (fetch_data, fetch_rates, fetch_context):
            mod.main()
            print("-" * 60)

    data = build_input.build()
    DATA.mkdir(exist_ok=True)
    (DATA / "briefing_input.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"입력 조립 완료: 시장 {len(data['markets'])}개, 금리 {len(data['rates']['yields'])}개, "
          f"스프레드 {len(data['rates']['spreads'])}개, 뉴스 국외 {len(data['news_intl'])}/국내 {len(data['news_kr'])}건, "
          f"이슈 {len(data['data_issues'])}건")
    for issue in data["data_issues"]:
        print(f"  - 이슈: {issue}")
    if args.input_only:
        return

    empty_result = {"picks": {"intl": [], "kr": []}, "problems": [], "unverified_numbers": [], "retried": False,
                    "usage": {"input_tokens": 0, "output_tokens": 0, "est_cost_usd": 0}}
    degraded = False  # 뉴스 요약 생성에 실패해 수치만 보내는 경우
    if args.no_llm:
        result = empty_result
    else:
        try:
            result = generate.generate(data)
        except generate.BriefingError as e:
            if not args.send:
                raise
            print(f"뉴스 요약 생성 실패: {e}")
            result, degraded = empty_result, True

    text = render.render(data, result["picks"], "뉴스 요약 생성 실패" if degraded else "오늘 선별된 주요 뉴스 없음")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    (DATA / "briefing.txt").write_text(text, encoding="utf-8")
    (DATA / f"briefing_{stamp}.json").write_text(
        json.dumps({**result, "text": text}, ensure_ascii=False, indent=1), encoding="utf-8")

    print("=" * 60)
    print(text)
    print("=" * 60)
    u = result["usage"]
    print(f"길이 {len(text)}자 (텔레그램 한도 {TELEGRAM_LIMIT}자 초과: {len(text) > TELEGRAM_LIMIT}) | "
          f"토큰 입력 {u['input_tokens']:,} / 출력 {u['output_tokens']:,} | 추정 비용 ${u['est_cost_usd']}"
          f"{' | 재시도 1회' if result['retried'] else ''}")
    if result.get("first_attempt"):
        print(f"첫 시도에서 걸린 문제(재시도함): {result['first_attempt']}")
    if result["problems"] or result["unverified_numbers"]:
        print(f"경고: id 문제 {result['problems']}, 기사에 근거 없는 숫자 {result['unverified_numbers']}")
    elif not args.no_llm:
        print("검증: 통과 (기사 id 유효, 요약 속 숫자는 모두 기사에 근거)")

    if args.send:
        from src.send import telegram

        n = telegram.send(text)
        print(f"텔레그램 전송 완료 (메시지 {n}개)")

    if degraded:  # 수치는 보냈지만 비정상 실행이므로 종료 코드 1 → 워크플로의 실패 알림이 따로 간다
        raise SystemExit(1)


if __name__ == "__main__":
    main()
