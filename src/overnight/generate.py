"""오버나잇 브리핑의 글 부분을 Claude로 생성한다.

- 한 줄 요약(ko/en)
- [증시]: 뉴스 3건 선별·요약
- [FICC]: 시황 코멘트 최대 3문장. 헤드라인을 나열하지 않고 '무슨 일이 있었고 시장이 어떻게 반응했는지'를 엮는다.
  원인을 말하는 문장은 근거 기사 id를 반드시 단다. (어조는 기존과 같은 개조식)

숫자·원문 링크는 코드가 채운다. 응답은 JSON 스키마로 강제하고, 기사 id 유효성·문장의 근거·숫자의 근거를 코드가 다시 검증한다.
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
FICC_SENTENCES = 3
MAX_IDS_PER_SENTENCE = 2   # 한 문장에 붙이는 근거 기사 수 (링크가 길어지지 않게)
MAX_PER_PUBLISHER = 2      # 근거로 쓰는 기사 중 같은 발행처는 최대 2건 (한 매체 편중 방지)

_ITEM = {
    "type": "object",
    "properties": {"id": {"type": "integer"}, "ko": {"type": "string"}, "en": {"type": "string"}},
    "required": ["id", "ko", "en"],
    "additionalProperties": False,
}
_SENTENCE = {
    "type": "object",
    "properties": {
        "ko": {"type": "string"},
        "en": {"type": "string"},
        "kind": {"type": "string", "enum": ["data", "news", "mixed"]},   # data: 시세만 / news: 뉴스 사실 / mixed: 둘 다
        "ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["ko", "en", "kind", "ids"],
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
        "ficc": {"type": "array", "items": _SENTENCE},
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
            "fx": [row(r, "last", "change") if r["key"] == "usdkrw" else row(r, "last", "change_pct") for r in data["fx"]],   # 달러/원은 원 단위 변화
            "energy": [row(r, "last", "change_pct") for r in data["energy"]],
        },
        "news": [
            {**{k: c[k] for k in ("id", "source", "tier", "topic", "lang", "title", "summary", "published_utc")},
             "publisher": c.get("publisher") or c["source"]}
            for c in data["news"]["candidates"]
        ],
    }


def clean_picks(raw, data):
    """모델 결과를 정리한다. 반환: (picks, problems). problems는 재시도 때 모델에게 알려줄 문제 목록.

    equity: 후보에 없는 id·중복·빈 요약·발행처 초과를 버리고 3개로 자른다.
    ficc  : 문장마다 근거 id를 검사한다. 뉴스 사실을 말하는 문장(news·mixed)에 유효한 근거가 없으면 문장을 버린다.
            (근거 없는 인과·사실 서술이 나가는 것을 막는 장치)
    """
    valid = {c["id"] for c in data["news"]["candidates"]}
    pub_of = {c["id"]: c.get("publisher") or c["source"] for c in data["news"]["candidates"]}
    pub_count, seen = {}, set()
    picks, problems = {"equity": [], "ficc": []}, []

    def take(pid):
        """근거로 쓸 수 있는 id인지 판단하고, 쓸 수 있으면 발행처 카운트를 올린다."""
        pub = pub_of[pid]
        if pub_count.get(pub, 0) >= MAX_PER_PUBLISHER:
            problems.append(f"{pub} 기사는 전체에서 최대 {MAX_PER_PUBLISHER}건 (id {pid} 제외)")
            return False
        pub_count[pub] = pub_count.get(pub, 0) + 1
        return True

    for p in raw.get("equity", []):
        if p["id"] not in valid:
            problems.append(f"id {p['id']}는 후보에 없음")
        elif p["id"] in seen:
            problems.append(f"id {p['id']} 중복")
        elif not p["ko"].strip() or not p["en"].strip():
            problems.append(f"id {p['id']}의 한국어/영어 요약이 비어 있음")
        elif take(p["id"]):
            seen.add(p["id"])
            picks["equity"].append({"id": p["id"], "ko": p["ko"].strip(), "en": p["en"].strip()})
    picks["equity"] = picks["equity"][:PER_SECTION]

    for n, s in enumerate(raw.get("ficc", []), 1):
        if not s["ko"].strip() or not s["en"].strip():
            problems.append(f"FICC 문장 {n}의 한국어/영어가 비어 있음")
            continue
        ids = []
        for pid in s["ids"]:
            if pid not in valid:
                problems.append(f"FICC 문장 {n}: id {pid}는 후보에 없음")
            elif pid not in ids and pid not in seen and len(ids) < MAX_IDS_PER_SENTENCE and take(pid):
                ids.append(pid)
        if s["kind"] in ("news", "mixed") and not ids:
            problems.append(f"FICC 문장 {n}은 뉴스 사실을 말하지만 유효한 근거 기사 id가 없음 (문장 제외)")
            continue
        seen.update(ids)
        picks["ficc"].append({"ko": s["ko"].strip(), "en": s["en"].strip(), "kind": s["kind"], "ids": ids})
    picks["ficc"] = picks["ficc"][:FICC_SENTENCES]
    return picks, problems


def _check(raw, data, payload):
    picks, problems = clean_picks(raw, data)
    summary = raw.get("summary", {})
    texts = [summary.get("ko", ""), summary.get("en", "")]
    texts += [p[lang] for p in picks["equity"] for lang in ("ko", "en")]
    texts += [p[lang] for p in picks["ficc"] for lang in ("ko", "en")]
    if not summary.get("ko", "").strip() or not summary.get("en", "").strip():
        problems = problems + ["한 줄 요약(ko/en)이 비어 있음"]
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
                "문제를 고쳐 다시 응답하라. 숫자는 market의 값이나 기사의 title/summary에 있는 것만 쓰고, "
                "뉴스 사실을 말하는 FICC 문장에는 근거 기사 id를 반드시 단다.",
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
