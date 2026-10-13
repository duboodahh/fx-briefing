import copy

import pytest
import requests

from src import notify
from src.brief.generate import BriefingError
from src.overnight import main as m
from test_overnight_generate import CANDS, DATA, RAW_OK

NORMAL = {"window": ["2026-10-12"], "kr_new": True, "us_new": True, "us_session": True, "kr_closed": [], "us_closed": [], "skip": False}
NO_US = {**NORMAL, "us_session": False, "us_new": False, "skip": False, "window": ["2026-11-26"]}
RESULT = {
    "summary": RAW_OK["summary"],
    "picks": {"equity": [{"id": 1, **{k: RAW_OK["equity"][0][k] for k in ("ko", "en")}}],
              "ficc": [{"id": 2, **{k: RAW_OK["ficc"][0][k] for k in ("ko", "en")}}]},
    "problems": [], "unverified_numbers": [], "retried": False, "first_attempt": None,
    "usage": {"input_tokens": 100, "output_tokens": 50, "est_cost_usd": 0.01},
}


def news_data(cands=CANDS, errors=None):
    return {"window_hours": 90, "collected": 10, "excluded_no_original": 1, "candidates": cands, "by_source": {}, "errors": errors or {}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """네트워크·텔레그램·Claude·data/ 를 모두 가짜로 바꾼다. 호출 기록은 calls에 남는다."""
    calls = {"collect": 0, "generate": 0, "sent": []}

    def boom(*a, **k):
        raise AssertionError("테스트에서 실제 네트워크 호출이 발생함")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(m, "DATA", tmp_path)
    monkeypatch.setattr(m.events_mod, "today_kst", lambda: __import__("datetime").date(2026, 10, 13))
    monkeypatch.setattr(m.market_calendar, "status", lambda today: dict(NORMAL))

    def fake_collect(today):
        calls["collect"] += 1
        d = copy.deepcopy(DATA)
        d.pop("news", None)
        return d
    monkeypatch.setattr(m.collect, "collect", fake_collect)
    monkeypatch.setattr(m.collect, "us_session_date", lambda today: __import__("datetime").date(2026, 10, 12))
    monkeypatch.setattr(m.onews, "collect_news", lambda session: news_data())

    def fake_generate(data):
        calls["generate"] += 1
        return copy.deepcopy(RESULT)
    monkeypatch.setattr(m.generate, "generate", fake_generate)

    from src.send import telegram
    monkeypatch.setattr(telegram, "send", lambda text, **k: calls["sent"].append(text) or 1)
    return calls


def test_send_sends_korean_then_english_as_two_messages(env):
    m.main(["--send"])
    assert len(env["sent"]) == 2
    ko, en = env["sent"]
    assert ko.startswith("Overnight Market Briefing\n2026.10.13(화)") and "[증시]" in ko
    assert en.startswith("Overnight Market Briefing\nTue, Oct 13, 2026") and "[Equities]" in en
    assert "https://www.wsj.com/a" in ko and "https://www.wsj.com/a" in en       # 원문 링크는 두 판 모두에


def test_without_send_nothing_is_sent_but_files_are_written(env, tmp_path):
    m.main([])
    assert env["sent"] == []
    assert (tmp_path / "overnight_ko.txt").exists() and (tmp_path / "overnight_en.txt").exists()
    assert (tmp_path / "overnight_result.json").exists() and (tmp_path / "overnight_input.json").exists()


def test_no_us_trading_day_skips_everything_before_any_fetch(env, monkeypatch):
    monkeypatch.setattr(m.market_calendar, "status", lambda today: dict(NO_US))
    m.main(["--send"])
    assert env["collect"] == 0 and env["generate"] == 0 and env["sent"] == []


def test_force_overrides_skip(env, monkeypatch):
    monkeypatch.setattr(m.market_calendar, "status", lambda today: dict(NO_US))
    m.main(["--send", "--force"])
    assert env["collect"] == 1 and len(env["sent"]) == 2


def test_claude_failure_still_sends_numbers_in_both_languages_then_exits_1(env, monkeypatch):
    monkeypatch.setattr(m.generate, "generate", lambda d: (_ for _ in ()).throw(BriefingError("API 오류")))
    with pytest.raises(SystemExit) as e:
        m.main(["--send"])
    assert e.value.code == 1
    ko, en = env["sent"]
    assert "• 뉴스 요약 생성 실패" in ko and "• News summary unavailable" in en
    assert "• 다우 51,850.55 (+0.38%)" in ko and "• 다우 51,850.55 (+0.38%)" in en


def test_claude_failure_without_send_raises(env, monkeypatch):
    monkeypatch.setattr(m.generate, "generate", lambda d: (_ for _ in ()).throw(BriefingError("x")))
    with pytest.raises(BriefingError):
        m.main([])


def test_no_candidates_skips_claude_and_reports_empty_not_failure(env, monkeypatch):
    monkeypatch.setattr(m.onews, "collect_news", lambda session: news_data(cands=[]))
    m.main(["--send"])                                  # 정상 종료(예외 없음)
    assert env["generate"] == 0 and len(env["sent"]) == 2
    assert "• 오늘 선별된 주요 뉴스 없음" in env["sent"][0]


def test_no_candidates_because_feeds_failed_is_flagged_as_failure(env, monkeypatch):
    monkeypatch.setattr(m.onews, "collect_news", lambda session: news_data(cands=[], errors={"WSJ": "HTTP 500"}))
    with pytest.raises(SystemExit) as e:
        m.main(["--send"])
    assert e.value.code == 1 and env["generate"] == 0 and "• 뉴스 요약 생성 실패" in env["sent"][0]


def test_send_with_no_llm_is_refused(env):
    with pytest.raises(SystemExit):
        m.main(["--send", "--no-llm"])


def test_failure_alert_names_the_workflow():
    env_vars = {"GITHUB_WORKFLOW": "Overnight Market Briefing", "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "me/fx", "GITHUB_RUN_ID": "9"}
    msg = notify.build_message(env_vars)
    assert msg.startswith("Overnight Market Briefing 자동 실행에 실패했습니다.") and "actions/runs/9" in msg
    assert notify.build_message({}).startswith("브리핑 자동 실행에 실패했습니다.")
