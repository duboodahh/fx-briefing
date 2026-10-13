# FX · 매크로 브리핑 텔레그램 봇

공개 데이터로 시황 **수치는 코드가 수집·계산**하고, **Claude는 뉴스 선별과 문장 작성만** 하는 평일 아침 자동 발송 텔레그램 봇입니다.
S&T/FICC 관점에서 쓸 수 있는 도구를 직접 만들어 보는 개인 프로젝트이며, GitHub Actions가 서버에서 돌리므로 컴퓨터를 켜 둘 필요가 없습니다.

> 이어서 작업하려면 [HANDOFF.md](HANDOFF.md)를 먼저 읽으세요. (현재 상태, 확정된 결정, 규칙, 백로그, 새 컴퓨터 세팅)

## 두 가지 브리핑

| 브리핑 | 발송 | 내용 | 진입점 |
|---|---|---|---|
| **Daily Macro Issue Briefing** | 평일 07:07 KST (한국어 1개) | 국외·국내 뉴스 3개씩, 금리·환율·유가 수치, 주요 일정 | `python -m src.main --send` |
| **Overnight Market Briefing** | 평일 06:50 KST 예약 (한국어 → 영어, 메시지 2개) | 미국장 마감 기준 한 줄 요약, 증시 뉴스, 주요 지수, FICC 코멘트, 금리·환율·에너지 | `python -m src.overnight.main --send` |

## 설계 원칙

1. **숫자는 코드, 문장은 LLM.** 변동폭·스프레드·지수·금리는 Python이 계산해서 템플릿에 채웁니다. Claude는 수치를 건드리지 않고, 요약 속 숫자가 입력 데이터(시세 요약·기사 본문)에 있는지 코드가 다시 검증합니다(위반 시 1회 재시도).
2. **원문 우선.** 발행처 도메인으로 직접 연결되는 기사만 후보로 씁니다(구글뉴스 같은 중간 주소는 제외). 요약마다 원문 링크가 바로 아래에 붙습니다.
3. **공개 데이터만.** 비공식·유료·사내 데이터는 쓰지 않습니다.
4. **근거 없는 서술 금지.** 시장이 움직인 원인은 근거 기사가 있을 때만 쓰고, 근거 id가 없는 뉴스성 문장은 코드가 제외합니다.
5. **실패해도 수치는 간다.** Claude나 일부 소스가 실패하면 해당 항목을 "수집 실패"로 표시하고 가능한 수치만 보내며, 별도로 실패 알림을 보냅니다.
6. **휴장일을 안다.** 한국·미국 거래일과 미국 채권시장 휴장(컬럼버스데이 등)을 반영해, 숨기거나 건너뜁니다.

## 구조

```
src/
  collect/      데이터 수집 (재무부, FRED, 한국은행 ECOS, RSS 뉴스, 일정, 시장 캘린더)
  analyze/      금리 변화·스프레드 계산
  brief/        Daily 브리핑: 입력 조립 → Claude → 숫자 검증 → 렌더링
  overnight/    Overnight 브리핑: 수집 → 뉴스 → Claude(한·영) → 렌더링 → 전송
  send/         텔레그램 전송 (일반 텍스트, 분할, 토큰 비노출)
  notify.py     Actions 실패 시 경고 메시지
config/         지표·뉴스 소스·일정 설정 (YAML)
prompts/        Claude 지침 (briefing.md, overnight.md)
.github/workflows/  daily-briefing.yml · overnight.yml · ci.yml
tests/          pytest (네트워크·텔레그램·Claude를 모두 가짜로 막고 검증)
```

데이터 흐름(Overnight 예): `수집(수치+뉴스) → Claude(한 줄 요약·증시 뉴스·FICC 코멘트, 한·영) → 검증 → 렌더링 → 텔레그램`

## 데이터 소스

| 항목 | 소스 | 성격 |
|---|---|---|
| 미국 국채 2·10·30Y | 미 재무부 일일 수익률 곡선 (FRED는 Daily의 예비) | 공식 |
| 국고채 3·10Y | 한국은행 ECOS | 공식 |
| 미국 지수(다우·S&P·나스닥) | 야후 + FRED 교차검증 | 일치 확인 |
| 러셀2000, 환율, DXY, 유가 | 야후 (`yfinance`) | 비공식 참고 시세 |
| 일정(FOMC·금통위·CPI 등) | 연준·한국은행·BLS·BEA 공식 일정을 직접 입력 (`config/events.yaml`) | 수동 관리 |
| 뉴스 | 공개 RSS (연준·ECB, WSJ, MarketWatch, FT, CNBC, Guardian, NYT, 한경·매경·연합 등), 등급제(1 원 출처 > 2 주요 언론 > 3 전문 사이트) | 원문 링크 필수 |

기준 시각: Overnight는 **미국 장 종료(뉴욕 16시 = 서머타임 05시 KST, 이후 06시)** 시점 값입니다. 지수는 공식 종가, 환율·DXY는 1시간봉 기준 종료 시점, 유가는 정산가입니다.

## 로컬 실행

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
touch .env             # 아래 키를 직접 입력 (절대 커밋하지 않음)
.venv/bin/python -m pytest -q                   # 테스트 (전송·API 호출 없음)
.venv/bin/python -m src.overnight.main          # 오버나잇 미리보기 (전송 안 함)
.venv/bin/python -m src.main                    # Daily 미리보기 (전송 안 함)
```

`.env`에 필요한 키: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`, `FRED_API_KEY`, `ECOS_API_KEY`
(`--send`를 붙여야 텔레그램으로 실제 전송합니다.)

## 자동 실행 (GitHub Actions)

- 위 5개 키를 저장소 **Settings → Secrets and variables → Actions**에 같은 이름으로 등록합니다.
- 크론은 UTC 기준입니다. KST 평일 아침은 일~목 밤 UTC입니다.
- 각 실행의 `data/`(수치·뉴스 후보·결과)는 30일간 artifact로 보관되어 나중에 원문과 대조할 수 있습니다.
- 수동 실행: Actions 탭 → 워크플로 선택 → Run workflow.

## 비용

Claude Opus 5.5(effort medium) 기준 Overnight 약 $0.12/회, Daily 약 $0.08/회로 월 $4~5 수준입니다.

## 한계

- 환율·유가·러셀2000은 야후 기반이라 공식 정산·고시와 다를 수 있습니다.
- 공개 소스만 쓰므로 증권사식 해석(투자의견 변경, 컨센서스 등)은 담지 못합니다. 근거 없는 인과는 쓰지 않습니다.
- 일정 파일은 수동 관리라 분기마다 갱신이 필요합니다.
