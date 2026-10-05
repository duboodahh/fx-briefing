"""텔레그램 전송. 일반 텍스트로 보낸다. (마크다운 특수문자 오류 방지, 메시지당 4,096자 제한 대응)

토큰이 URL에 포함되므로, 예외·로그에 URL이 섞여 출력되지 않게 직접 메시지를 만든다.

사용:
  python -m src.send.telegram                 # data/briefing.txt를 전송
  python -m src.send.telegram 파일경로         # 지정한 텍스트 파일을 전송
"""
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
API = "https://api.telegram.org/bot{token}/sendMessage"
LIMIT = 4096
CHUNK = 4000  # 여유를 둔다


def split_message(text, limit=CHUNK):
    """limit자 이하로 나눈다. 빈 줄(문단) 경계를 우선하고, 그래도 길면 줄 단위로, 한 줄이 너무 길면 글자 단위로 자른다."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(para) <= limit:
            current = para
            continue
        for line in para.split("\n"):  # 문단 하나가 한도를 넘으면 줄 단위
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) <= limit:
                current = candidate
            else:
                chunks.append(current)
                current = line
    if current:
        chunks.append(current)
    return chunks


def send(text, token=None, chat_id=None):
    """text를 전송하고 보낸 메시지 수를 반환한다. 실패하면 RuntimeError."""
    if token is None or chat_id is None:
        load_dotenv(ROOT / ".env")
        token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 없음")
    if not text.strip():
        raise RuntimeError("보낼 내용이 비어 있음")

    parts = split_message(text.strip())
    for i, part in enumerate(parts, 1):
        try:
            r = requests.post(
                API.format(token=token),
                data={"chat_id": chat_id, "text": part, "disable_web_page_preview": "true"},
                timeout=20,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"텔레그램 요청 실패 ({type(e).__name__}) [{i}/{len(parts)}]") from None
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code != 200 or not body.get("ok"):
            raise RuntimeError(
                f"텔레그램 전송 실패 (HTTP {r.status_code}: {body.get('description', '응답 없음')}) [{i}/{len(parts)}]"
            )
    return len(parts)


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "briefing.txt"
    text = path.read_text(encoding="utf-8")
    n = send(text)
    print(f"전송 완료: {path.name} ({len(text)}자, 메시지 {n}개)")


if __name__ == "__main__":
    main()
