import pytest
import requests

from src.brief import generate as base
from src.overnight import generate as og
from src.overnight import render
from test_overnight import DATA as NUM

CANDS = [
    {"id": 1, "source": "WSJ Markets", "tier": 2, "topic": "equity", "lang": "en", "title": "Jobs rose 29,000 in September",
     "summary": "Unemployment rate rose to 4.2%", "published_utc": "2026-10-13T08:00", "url": "https://www.wsj.com/a"},
    {"id": 2, "source": "한국경제 금융", "tier": 2, "topic": "ficc", "lang": "ko", "title": "국채 금리 하락",
     "summary": "", "published_utc": "2026-10-13T07:00", "url": "https://www.hankyung.com/b"},
    {"id": 3, "source": "FT", "tier": 2, "topic": "both", "lang": "en", "title": "Oil rises", "summary": "",
     "published_utc": "2026-10-13T06:00", "url": "https://www.ft.com/c"},
]
SPX = {"key": "spx", "name": "S&P500", "name_en": "S&P 500", "last": 7807.24, "change_pct": -0.06}
DATA = {**NUM, "indices": NUM["indices"] + [SPX], "news": {"candidates": CANDS}}
RAW_OK = {
    "summary": {"ko": "S&P500 -0.06%, 유가 상승", "en": "S&P 500 slips 0.06% as oil rises"},
    "equity": [{"id": 1, "ko": "미 9월 고용 29,000명 증가, 실업률 4.2%", "en": "US payrolls rise 29,000; jobless rate 4.2%"}],
    "ficc": [{"id": 2, "ko": "국채 금리 하락", "en": "Treasury yields fall"}],
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("테스트에서 실제 네트워크 호출이 발생함")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests, "post", boom)


def test_payload_has_market_numbers_and_no_urls():
    p = og.build_payload(DATA)
    assert all("url" not in n for n in p["news"])
    assert p["market"]["indices"][0] == {"name": "다우", "last": 51850.55, "change_pct": 0.38}


def test_clean_picks_requires_both_languages_and_valid_ids():
    raw = {"summary": {"ko": "a", "en": "b"},
           "equity": [{"id": 1, "ko": "가", "en": "a"}, {"id": 99, "ko": "x", "en": "x"}, {"id": 3, "ko": "", "en": "oil"}],
           "ficc": [{"id": 1, "ko": "중복", "en": "dup"}, {"id": 2, "ko": "나", "en": "b"}]}
    picks, problems = og.clean_picks(raw, DATA)
    assert [p["id"] for p in picks["equity"]] == [1] and [p["id"] for p in picks["ficc"]] == [2]
    assert any("99" in p for p in problems) and any("중복" in p for p in problems) and any("비어" in p for p in problems)


def fake_client(monkeypatch, responses):
    calls = []

    class U:  # usage
        input_tokens, output_tokens = 1000, 500

    def fake_call(client, system, user_text, schema=None):
        calls.append(user_text)
        return responses[len(calls) - 1], U()

    monkeypatch.setattr(og.base, "_call", fake_call)
    monkeypatch.setattr(og.anthropic, "Anthropic", lambda: object())
    monkeypatch.setattr(og, "load_dotenv", lambda *a, **k: None)
    return calls


def test_generate_passes_without_retry_when_numbers_are_grounded(monkeypatch):
    calls = fake_client(monkeypatch, [RAW_OK])
    r = og.generate(DATA)
    assert not r["retried"] and len(calls) == 1
    assert r["unverified_numbers"] == [] and r["summary"]["en"].startswith("S&P 500")


def test_generate_retries_once_on_invented_number_then_succeeds(monkeypatch):
    bad = {**RAW_OK, "equity": [{"id": 1, "ko": "미 9월 고용 2.9만명 증가", "en": "US payrolls rise 29.5K"}]}
    calls = fake_client(monkeypatch, [bad, RAW_OK])
    r = og.generate(DATA)
    assert r["retried"] is True and len(calls) == 2
    assert "29.5" in str(r["first_attempt"]["unverified_numbers"])
    assert r["unverified_numbers"] == []


def test_render_both_languages_same_facts_and_links():
    r = {"summary": RAW_OK["summary"], "picks": {"equity": [{"id": 1, **{k: RAW_OK["equity"][0][k] for k in ("ko", "en")}}],
                                                  "ficc": [{"id": 2, **{k: RAW_OK["ficc"][0][k] for k in ("ko", "en")}}]}}
    ko = render.render(DATA, r, lang="ko").split("\n")
    en = render.render(DATA, r, lang="en").split("\n")
    assert ko[0] == en[0] == "Overnight Market Briefing"
    assert ko[1] == "2026.10.13(화) | 미국장 10/12(월) 마감 기준"
    assert en[1] == "Tue, Oct 13, 2026 | US close of Mon, Oct 12"
    assert '"S&P500 -0.06%, 유가 상승"' in ko and '"S&P 500 slips 0.06% as oil rises"' in en
    assert "[증시]" in ko and "[Equities]" in en and "[FICC]" in ko and "[FICC]" in en
    # 같은 기사, 같은 원문 링크가 두 언어판에 모두 붙는다
    assert "• 미 9월 고용 29,000명 증가, 실업률 4.2% (WSJ Markets)" in ko and "  https://www.wsj.com/a" in ko
    assert "• US payrolls rise 29,000; jobless rate 4.2% (WSJ Markets)" in en and "  https://www.wsj.com/a" in en
    # 수치는 코드가 두 언어판에서 똑같이 만든다
    assert "• 다우 51,850.55 (+0.38%)" in ko and "• 다우 51,850.55 (+0.38%)" in en
    assert "• 달러/원 1,335.10원 (-7.70원)" in ko and "• 달러/원 1,335.10 (-7.70 won)" in en
    assert "• WTI 93.74달러 (+2.06%)" in ko and "• WTI $93.74 (+2.06%)" in en


# ---- 한 발행처 편중 방지 ----
def _cnbc(i, topic="both"):
    return {"id": i, "source": f"CNBC Feed{i}", "publisher": "CNBC", "tier": 2, "topic": topic, "lang": "en",
            "title": f"t{i}", "summary": "", "published_utc": "2026-10-13T08:00", "url": f"https://www.cnbc.com/{i}"}


def test_clean_picks_limits_same_publisher_to_two_across_all_six():
    cands = [_cnbc(1), _cnbc(2), _cnbc(3), _cnbc(4)] + [
        {**_cnbc(5), "source": "WSJ Markets", "publisher": "WSJ"}, {**_cnbc(6), "source": "FT", "publisher": "FT"}]
    d = {**DATA, "news": {"candidates": cands}}
    raw = {"summary": {"ko": "a", "en": "b"},
           "equity": [{"id": i, "ko": "가", "en": "a"} for i in (1, 2, 3)],       # 같은 CNBC 3건
           "ficc": [{"id": 4, "ko": "나", "en": "b"}, {"id": 5, "ko": "다", "en": "c"}, {"id": 6, "ko": "라", "en": "d"}]}
    picks, problems = og.clean_picks(raw, d)
    ids = [p["id"] for s in picks.values() for p in s]
    assert ids == [1, 2, 5, 6]                       # CNBC는 2건까지(1,2), 3·4번은 제외, WSJ·FT는 통과
    assert any("CNBC" in p and "최대 2건" in p for p in problems)


def test_payload_exposes_publisher_with_source_fallback():
    p = og.build_payload({**DATA, "news": {"candidates": [_cnbc(1), CANDS[0]]}})
    assert p["news"][0]["publisher"] == "CNBC" and p["news"][1]["publisher"] == "WSJ Markets"   # publisher 없으면 source
