"""Claude API로 뉴스 선별·한 줄 요약만 생성한다. (제목·수치·일정은 render가 코드로 채운다.)

결과는 JSON 스키마로 강제하고, 기사 id가 후보에 있는지·요약 속 숫자가 기사에 있는지 코드로 다시 검증한다.
"""
import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from src.brief import build_input, render, verify

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "prompts" / "briefing.md"

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_TOKENS = 16000
# 서버 측 폴백(안전 분류기가 요청을 거절할 때 Anthropic이 권장하는 모델로 같은 호출 안에서 재시도). 평소엔 영향 없음.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
PRICE_PER_MTOK = {"input": 4.0, "output": 20.0}  # USD, Claude Opus 5.5 (생각 토큰은 output에 포함)

_ITEM = {
    "type": "object",
    "properties": {"id": {"type": "integer"}, "summary": {"type": "string"}},
    "required": ["id", "summary"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {"intl": {"type": "array", "items": _ITEM}, "kr": {"type": "array", "items": _ITEM}},
    "required": ["intl", "kr"],
    "additionalProperties": False,
}


class BriefingError(RuntimeError):
    pass


def _call(client, system, user_text):
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_text}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        category = getattr(resp.stop_details, "category", None)
        raise BriefingError(f"모델이 응답을 거절함 (category={category})")
    if resp.stop_reason == "max_tokens":
        raise BriefingError("max_tokens에 도달해 응답이 잘림")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    try:
        return json.loads(text), resp.usage
    except json.JSONDecodeError:
        raise BriefingError("응답이 올바른 JSON이 아님") from None


def _cost(usage):
    return (usage.input_tokens * PRICE_PER_MTOK["input"] + usage.output_tokens * PRICE_PER_MTOK["output"]) / 1_000_000


def clean_picks(raw, data):
    """모델 결과를 정리한다. 후보에 없는 id·다른 지역 id·중복은 버리고, 개수는 지역당 최대 3개로 자른다.

    반환: (picks, problems). problems는 재시도 시 모델에게 알려줄 문제 목록.
    """
    valid = {"intl": {n["id"] for n in data["news_intl"]}, "kr": {n["id"] for n in data["news_kr"]}}
    picks, problems, seen = {"intl": [], "kr": []}, [], set()
    for region in ("intl", "kr"):
        for p in raw.get(region, []):
            if p["id"] not in valid[region]:
                problems.append(f"id {p['id']}는 {region} 후보에 없음")
            elif p["id"] in seen:
                problems.append(f"id {p['id']} 중복")
            elif not p["summary"].strip():
                problems.append(f"id {p['id']}의 요약이 비어 있음")
            else:
                seen.add(p["id"])
                picks[region].append({"id": p["id"], "summary": p["summary"].strip()})
        picks[region] = picks[region][: render.NEWS_PER_REGION]
    return picks, problems


def _check(raw, data):
    picks, problems = clean_picks(raw, data)
    summaries = " ".join(p["summary"] for r in picks.values() for p in r)
    # 요약 속 숫자는 뉴스 후보(제목·요약)에 있는 것이어야 한다
    unverified = verify.find_unverified(summaries, build_input.llm_payload(data))
    return picks, problems, unverified


def generate(data):
    """data(build_input.build 결과)로 뉴스 섹션을 만든다."""
    load_dotenv(ROOT / ".env")  # ANTHROPIC_API_KEY (값은 출력하지 않는다)
    client = anthropic.Anthropic()
    system = PROMPT.read_text(encoding="utf-8")
    user_text = "오늘 수집된 데이터:\n" + json.dumps(build_input.llm_payload(data), ensure_ascii=False, indent=1)

    try:
        raw, usage = _call(client, system, user_text)
        in_tok, out_tok, cost = usage.input_tokens, usage.output_tokens, _cost(usage)
        picks, problems, unverified = _check(raw, data)

        retried, first_attempt = False, None
        if problems or unverified:  # 한 번만 재시도: 문제를 알려주고 다시 고르게 한다
            retried = True
            first_attempt = {"problems": problems, "unverified_numbers": unverified}
            notes = problems + ([f"기사에 없는 숫자: {', '.join(unverified)}"] if unverified else [])
            raw, usage2 = _call(
                client, system, f"{user_text}\n\n[검토 결과] 이전 응답의 문제: {'; '.join(notes)}.\n"
                "문제를 고쳐서 다시 응답하라. 요약에는 해당 기사의 title/summary에 있는 숫자만 쓴다."
            )
            in_tok += usage2.input_tokens
            out_tok += usage2.output_tokens
            cost += _cost(usage2)
            picks, problems, unverified = _check(raw, data)
    except anthropic.APIStatusError as e:
        raise BriefingError(f"Claude API 오류 (HTTP {e.status_code}): {e.message}") from None
    except anthropic.APIConnectionError:
        raise BriefingError("Claude API 연결 실패") from None

    return {
        "picks": picks,
        "problems": problems,
        "unverified_numbers": unverified,
        "retried": retried,
        "first_attempt": first_attempt,  # 재시도한 경우 첫 시도에서 걸린 문제 (프롬프트 개선용)
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok, "est_cost_usd": round(cost, 4)},
    }
