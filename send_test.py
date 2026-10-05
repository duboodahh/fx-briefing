import os
import requests
from dotenv import load_dotenv


def main():
    load_dotenv()
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": "FX 브리핑 봇 테스트"},
    )
    print(r.status_code, r.json().get("ok"))


# 직접 실행(python send_test.py)할 때만 전송한다. pytest가 이 파일을 불러와도 메시지가 가지 않도록 가드를 둔다.
if __name__ == "__main__":
    main()
