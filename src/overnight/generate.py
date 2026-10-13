"""오버나잇 브리핑의 뉴스 부분을 Claude로 생성한다: 한 줄 요약 + 증시·FICC 뉴스 각 3개 선별·요약.

숫자·원문 링크는 코드가 채운다. 모델 응답은 JSON 스키마로 강제하고, 기사 id 유효성·요약 속 숫자의 근거를 코드가 다시 검증한다.
"""
import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from src.brief import generate as base
from src.brief import verify

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "prompts" / "overnight.md"
PER_SECTION = 3

_ITEM = {
    "type": "object",
    "properties": {"id": {"type": "integer"}, "ko": {"type": "string"}, "en": {"type": "string"}},
    "required": ["id", "ko", "en"],
    "additionalProperties": False,
}
_SUMMARY = {
    "type": "object",
    "properties": {"ko": {"type": "string"}, "en": {"type": "string"}},
    "required": ["ko", "en"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": _SUMMARY,
        "equity": {"type": "array", "items": _ITEM},
        "ficc": {"type": "array", "items": _ITEM},
    },
    "required": ["summary", "equity", "ficc"],
    "additionalProperties": False,
}


def build_payload(data):
    """LLM에 주는 입력: 마감 시점 시세 요약 + 뉴스 후보(원문 링크는 제외)."""
    def row(r, *keys):
        return {"name": r["name"], **{k: r[k] for k in keys}} if "error" not in r else {"name": r["name"], "error": "수집 실패"}

    rates = data["rates"]
    ok = [r for r in rates if "error" not in r]
    closed = bool(ok) and all(r["status"] == "closed" for r in ok)
    return {
        "today_kst": data["today_kst"],
        "session_date": data["session_date"],
        "market": {
            "indices": [row(r, "last", "change_pct") for r in data["indices"]],
            "treasury": "휴장" if closed else [row(r, "last", "change_bp") for r in rates],
            "fx": [row(r, "last", "change_pct") for r in data["fx"]],
            "energy": [row(r, "last", "change_pct") for r in data["energy"]],
        },
        "news": [
            {k: c[k] for k in ("id", "source", "tier", "topic", "lang", "title", "summary", "published_utc")}
            for c in data["news"]["candidates"]
        ],
    }


def clean_picks(raw, data):
    """후보에 없는 id·중복·빈 요약은 버리고 섹션당 3개로 자른다. 반환: (picks, problems)."""
    valid = {c["id"] for c in data["news"]["candidates"]}
    picks, problems, seen = {"equity": [], "ficc": []}, [], set()
    for section in ("equity", "ficc"):
        for p in raw.get(section, []):
            if p["id"] not in valid:
                problems.append(f"id {p['id']}는 후보에 없음")
            elif p["id"] in seen:
                problems.append(f"id {p['id']} 중복")
            elif not p["ko"].strip() or not p["en"].strip():
                problems.append(f"id {p['id']}의 한국어/영어 요약이 비어 있음")
            else:
                seen.add(p["id"])
                picks[section].append({"id": p["id"], "ko": p["ko"].strip(), "en": p["en"].strip()})
        picks[section] = picks[section][:PER_SECTION]
    return picks, problems


def _check(raw, data, payload):
    picks, problems = clean_picks(raw, data)
    summary = raw.get("summary", {})
    texts = [summary.get("ko", ""), summary.get("en", "")] + [p[lang] for s in picks.values() for p in s for lang in ("ko", "en")]
    problems = problems + (["한 줄 요약(ko/en)이 비어 있음"] if not summary.get("ko", "").strip() or not summary.get("en", "").strip() else [])
    return picks, problems, verify.find_unverified(" ".join(texts), payload)


def generate(data):
    load_dotenv(ROOT / ".env")
    client = anthropic.Anthropic()
    system = PROMPT.read_text(encoding="utf-8")
    payload = build_payload(data)
    user_text = "오늘 수집된 데이터:\n" + json.dumps(payload, ensure_ascii=False, indent=1)

    try:
        raw, usage = base._call(client, system, user_text, SCHEMA)
        in_tok, out_tok, cost = usage.input_tokens, usage.output_tokens, base._cost(usage)
        picks, problems, unverified = _check(raw, data, payload)

        retried, first_attempt = False, None
        if problems or unverified:  # 한 번만 재시도
            retried, first_attempt = True, {"problems": problems, "unverified_numbers": unverified}
            notes = problems + ([f"입력에 없는 숫자: {', '.join(unverified)}"] if unverified else [])
            raw, usage2 = base._call(
                client, system,
                f"{user_text}\n\n[검토 결과] 이전 응답의 문제: {'; '.join(notes)}.\n"
                "문제를 고쳐 다시 응답하라. 숫자는 market의 값이나 기사의 title/summary에 있는 것만 쓴다.",
                SCHEMA,
            )
            in_tok += usage2.input_tokens
            out_tok += usage2.output_tokens
            cost += base._cost(usage2)
            picks, problems, unverified = _check(raw, data, payload)
    except anthropic.APIStatusError as e:
        raise base.BriefingError(f"Claude API 오류 (HTTP {e.status_code}): {e.message}") from None
    except anthropic.APIConnectionError:
        raise base.BriefingError("Claude API 연결 실패") from None

    return {
        "summary": {k: raw.get("summary", {}).get(k, "").strip() for k in ("ko", "en")},
        "picks": picks,
        "problems": problems,
        "unverified_numbers": unverified,
        "retried": retried,
        "first_attempt": first_attempt,
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok, "est_cost_usd": round(cost, 4)},
    }
