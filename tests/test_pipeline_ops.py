import sys

import pytest
import requests

from src import main as main_mod
from src import notify
from src.brief import generate, render
from test_render_pipeline import DATA

NORMAL_DAY = {"window": ["2026-10-01"], "kr_new": True, "us_new": True, "kr_closed": [], "us_closed": [], "skip": False}


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """실제 네트워크·텔레그램·API·data/ 폴더를 건드리지 않게 막는다."""
    def boom(*a, **k):
        raise AssertionError("테스트에서 실제 네트워크 호출이 발생함")
    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(main_mod, "DATA", tmp_path)
    monkeypatch.setattr(main_mod.build_input, "build", lambda: DATA)
    # 실제 오늘 날짜에 따라 결과가 달라지지 않도록 캘린더 판단은 '평범한 영업일'로 고정한다
    monkeypatch.setattr(main_mod.market_calendar, "status", lambda today: dict(NORMAL_DAY))


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["src.main", *args])
    main_mod.main()


def test_claude_failure_still_sends_numbers_then_exits_nonzero(monkeypatch, tmp_path):
    def fail(data):
        raise generate.BriefingError("Claude API 오류 (HTTP 529)")

    sent = []
    monkeypatch.setattr(main_mod.generate, "generate", fail)
    from src.send import telegram
    monkeypatch.setattr(telegram, "send", lambda text, **k: sent.append(text) or 1)

    with pytest.raises(SystemExit) as e:
        run_main(monkeypatch, "--no-fetch", "--send")
    assert e.value.code == 1                                   # 워크플로가 실패로 인식 → 실패 알림
    assert len(sent) == 1
    assert "• 뉴스 요약 생성 실패" in sent[0]                   # 사유를 밝힘
    assert "• 미국 국채 10Y 5.28% (+4.0bp)" in sent[0]          # 수치는 그대로 전송


def test_claude_failure_without_send_raises(monkeypatch):
    monkeypatch.setattr(main_mod.generate, "generate",
                        lambda d: (_ for _ in ()).throw(generate.BriefingError("x")))
    with pytest.raises(generate.BriefingError):
        run_main(monkeypatch, "--no-fetch")


def test_success_path_sends_once_and_exits_cleanly(monkeypatch):
    sent = []
    monkeypatch.setattr(main_mod.generate, "generate", lambda d: {
        "picks": {"intl": [{"id": 1, "summary": "고용 부진"}], "kr": []},
        "problems": [], "unverified_numbers": [], "retried": False, "first_attempt": None,
        "usage": {"input_tokens": 1, "output_tokens": 1, "est_cost_usd": 0.0}})
    from src.send import telegram
    monkeypatch.setattr(telegram, "send", lambda text, **k: sent.append(text) or 1)
    run_main(monkeypatch, "--no-fetch", "--send")
    assert len(sent) == 1 and "• 고용 부진 (CNBC Economy)" in sent[0]


def test_skip_day_sends_nothing_and_never_calls_claude(monkeypatch):
    skip = {**NORMAL_DAY, "kr_new": False, "us_new": False, "skip": True,
            "window": ["2026-12-25", "2026-12-26", "2026-12-27"]}
    monkeypatch.setattr(main_mod.market_calendar, "status", lambda today: skip)
    monkeypatch.setattr(main_mod.generate, "generate", lambda d: (_ for _ in ()).throw(AssertionError("API 호출됨")))
    from src.send import telegram
    monkeypatch.setattr(telegram, "send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("전송됨")))
    run_main(monkeypatch, "--send")            # 예외 없이 조용히 종료해야 한다


def test_force_overrides_skip(monkeypatch):
    skip = {**NORMAL_DAY, "kr_new": False, "us_new": False, "skip": True}
    monkeypatch.setattr(main_mod.market_calendar, "status", lambda today: skip)
    sent = []
    monkeypatch.setattr(main_mod.generate, "generate", lambda d: {
        "picks": {"intl": [], "kr": []}, "problems": [], "unverified_numbers": [], "retried": False,
        "first_attempt": None, "usage": {"input_tokens": 0, "output_tokens": 0, "est_cost_usd": 0}})
    from src.send import telegram
    monkeypatch.setattr(telegram, "send", lambda text, **k: sent.append(text) or 1)
    run_main(monkeypatch, "--no-fetch", "--send", "--force")
    assert len(sent) == 1


def test_send_refused_together_with_no_llm(monkeypatch):
    with pytest.raises(SystemExit):
        run_main(monkeypatch, "--no-llm", "--send")


def test_render_custom_empty_text():
    out = render.render(DATA, {"intl": [], "kr": []}, "뉴스 요약 생성 실패")
    assert out.count("• 뉴스 요약 생성 실패") == 2   # 국외·국내 두 블록


def test_notify_message_has_run_link_and_no_secrets():
    env = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "me/fx", "GITHUB_RUN_ID": "123",
           "TELEGRAM_BOT_TOKEN": "SECRET"}
    msg = notify.build_message(env)
    assert "https://github.com/me/fx/actions/runs/123" in msg and "SECRET" not in msg
    assert "로그 확인" not in notify.build_message({})        # 로컬 실행 등 정보가 없으면 링크 생략
