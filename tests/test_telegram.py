import pytest
import requests

from src.send import telegram


@pytest.fixture(autouse=True)
def never_hit_network(monkeypatch):
    """이 파일의 모든 테스트는 실제 네트워크 호출을 막는다. (실수로 메시지가 가지 않도록)"""
    def boom(*a, **k):
        raise AssertionError("테스트에서 실제 requests.post가 호출됨")
    monkeypatch.setattr(requests, "post", boom)


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body if body is not None else {"ok": True}

    def json(self):
        return self._body


def test_short_text_is_single_message():
    assert telegram.split_message("안녕\n\n세계") == ["안녕\n\n세계"]


def test_long_text_splits_on_paragraphs_under_limit():
    paras = ["가" * 1500 for _ in range(5)]
    chunks = telegram.split_message("\n\n".join(paras), limit=4000)
    assert all(len(c) <= 4000 for c in chunks)
    assert "".join(chunks).replace("\n", "") == "".join(paras)   # 내용 손실 없음
    assert len(chunks) == 3


def test_single_huge_line_is_hard_split():
    chunks = telegram.split_message("나" * 9000, limit=4000)
    assert [len(c) for c in chunks] == [4000, 4000, 1000]


def test_send_posts_plain_text_without_parse_mode(monkeypatch):
    calls = []

    def fake_post(url, data, timeout):
        calls.append((url, data))
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)
    n = telegram.send("브리핑 본문", token="T0KEN", chat_id="42")
    assert n == 1
    url, data = calls[0]
    assert url.endswith("/botT0KEN/sendMessage")
    assert data["chat_id"] == "42" and data["text"] == "브리핑 본문"
    assert "parse_mode" not in data


def test_api_error_message_does_not_leak_token(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(401, {"ok": False, "description": "Unauthorized"}))
    with pytest.raises(RuntimeError) as e:
        telegram.send("x", token="SECRET-TOKEN", chat_id="1")
    assert "401" in str(e.value) and "SECRET-TOKEN" not in str(e.value)


def test_network_error_does_not_leak_token(monkeypatch):
    def fail(*a, **k):
        raise requests.ConnectionError("https://api.telegram.org/botSECRET-TOKEN/sendMessage failed")

    monkeypatch.setattr(requests, "post", fail)
    with pytest.raises(RuntimeError) as e:
        telegram.send("x", token="SECRET-TOKEN", chat_id="1")
    assert "SECRET-TOKEN" not in str(e.value)


def test_empty_text_and_missing_credentials_rejected(monkeypatch):
    with pytest.raises(RuntimeError):
        telegram.send("   ", token="t", chat_id="1")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(telegram, "load_dotenv", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        telegram.send("x")
