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
    "ficc": [{"ko": "국채 금리 하락 속 DXY +0.36%", "en": "DXY +0.36% as Treasury yields fall", "kind": "mixed", "ids": [2]}],
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
           "ficc": [{"ko": "중복 근거", "en": "dup", "kind": "news", "ids": [1]},      # equity에서 이미 쓴 기사 → 근거로 못 씀 → 문장 제외
                    {"ko": "나", "en": "b", "kind": "news", "ids": [2]}]}
    picks, problems = og.clean_picks(raw, DATA)
    assert [p["id"] for p in picks["equity"]] == [1] and [p["ids"] for p in picks["ficc"]] == [[2]]
    assert any("99" in p for p in problems) and any("비어" in p for p in problems) and any("근거 기사 id가 없음" in p for p in problems)


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
                                                  "ficc": [RAW_OK["ficc"][0]]}}
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


def test_clean_picks_limits_same_publisher_to_two_across_equity_and_ficc():
    cands = [_cnbc(1), _cnbc(2), _cnbc(3), _cnbc(4)] + [
        {**_cnbc(5), "source": "WSJ Markets", "publisher": "WSJ"}, {**_cnbc(6), "source": "FT", "publisher": "FT"}]
    d = {**DATA, "news": {"candidates": cands}}
    raw = {"summary": {"ko": "a", "en": "b"},
           "equity": [{"id": i, "ko": "가", "en": "a"} for i in (1, 2, 3)],                    # 같은 CNBC 3건
           "ficc": [{"ko": "나", "en": "b", "kind": "news", "ids": [4, 5]},                    # 4번(CNBC)은 이미 2건 초과 → 5번(WSJ)만
                    {"ko": "다", "en": "c", "kind": "news", "ids": [6]}]}
    picks, problems = og.clean_picks(raw, d)
    assert [p["id"] for p in picks["equity"]] == [1, 2]                      # CNBC는 2건까지
    assert [s["ids"] for s in picks["ficc"]] == [[5], [6]]                   # WSJ·FT는 통과
    assert any("CNBC" in p and "최대 2건" in p for p in problems)


def test_ficc_sentence_without_evidence_is_dropped_but_data_sentence_is_kept():
    raw = {"summary": {"ko": "a", "en": "b"}, "equity": [],
           "ficc": [{"ko": "근거 없는 인과", "en": "x", "kind": "mixed", "ids": [99]},        # 유효 근거 없음 → 제외
                    {"ko": "DXY +0.36%", "en": "DXY +0.36%", "kind": "data", "ids": []}]}   # 시세만 → 근거 없이 허용
    picks, problems = og.clean_picks(raw, DATA)
    assert [s["ko"] for s in picks["ficc"]] == ["DXY +0.36%"]
    assert any("근거 기사 id가 없음" in p for p in problems)


def test_ficc_limits_evidence_to_two_ids_per_sentence_and_caps_three_sentences():
    cands = [{**_cnbc(i), "source": f"S{i}", "publisher": f"P{i}"} for i in range(1, 8)]
    d = {**DATA, "news": {"candidates": cands}}
    raw = {"summary": {"ko": "a", "en": "b"}, "equity": [],
           "ficc": [{"ko": "1", "en": "1", "kind": "news", "ids": [1, 2, 3]},
                    {"ko": "2", "en": "2", "kind": "news", "ids": [4]},
                    {"ko": "3", "en": "3", "kind": "news", "ids": [5]},
                    {"ko": "4", "en": "4", "kind": "news", "ids": [6]}]}
    picks, _ = og.clean_picks(raw, d)
    assert [s["ids"] for s in picks["ficc"]] == [[1, 2], [4], [5]]


def test_ficc_render_shows_sources_and_links_only_for_cited_sentences():
    r = {"summary": RAW_OK["summary"], "picks": {"equity": [], "ficc": [
        {"ko": "사건 속 DXY +0.36%", "en": "DXY +0.36% on event", "kind": "mixed", "ids": [1, 3]},
        {"ko": "시세만 문장", "en": "data only", "kind": "data", "ids": []}]}}
    ko = render.render(DATA, r, lang="ko").split("\n")
    i = ko.index("• 사건 속 DXY +0.36% (WSJ Markets, FT)")
    assert ko[i + 1] == "  https://www.wsj.com/a" and ko[i + 2] == "  https://www.ft.com/c"
    assert "• 시세만 문장" in ko and not ko[ko.index("• 시세만 문장") + 1].startswith("  http")   # 출처·주소 줄이 붙지 않음


def test_payload_exposes_publisher_with_source_fallback():
    p = og.build_payload({**DATA, "news": {"candidates": [_cnbc(1), CANDS[0]]}})
    assert p["news"][0]["publisher"] == "CNBC" and p["news"][1]["publisher"] == "WSJ Markets"   # publisher 없으면 source


def test_english_edition_uses_english_source_names():
    cands = [{**CANDS[1], "source": "한국경제 금융", "source_en": "Hankyung"}, CANDS[0]]
    d = {**DATA, "news": {"candidates": cands}}
    r = {"summary": RAW_OK["summary"], "picks": {"equity": [], "ficc": [
        {"ko": "금리 하락", "en": "Yields fall", "kind": "news", "ids": [2]}]}}
    assert "• 금리 하락 (한국경제 금융)" in render.render(d, r, lang="ko").split("\n")
    assert "• Yields fall (Hankyung)" in render.render(d, r, lang="en").split("\n")
