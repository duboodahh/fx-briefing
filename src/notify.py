"""GitHub Actions 실행이 실패했을 때 텔레그램으로 경고를 보낸다. (워크플로의 'Alert on failure' 단계)"""
import os

from src.send import telegram


def build_message(env=os.environ):
    server, repo, run_id = env.get("GITHUB_SERVER_URL"), env.get("GITHUB_REPOSITORY"), env.get("GITHUB_RUN_ID")
    name = env.get("GITHUB_WORKFLOW") or "브리핑"   # 워크플로 이름(Daily Macro Issue Briefing / Overnight Market Briefing)
    lines = [f"{name} 자동 실행에 실패했습니다."]
    if server and repo and run_id:
        lines.append(f"로그 확인: {server}/{repo}/actions/runs/{run_id}")
    return "\n".join(lines)


def main():
    telegram.send(build_message())
    print("실패 알림 전송 완료")


if __name__ == "__main__":
    main()
