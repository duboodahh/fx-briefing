"""오버나잇 브리핑 텍스트 조립(한국어·영어). 제목·수치·기준은 코드가 만들고, 뉴스 요약만 LLM 결과를 받는다. (일반 텍스트)

구조: 제목/날짜/한 줄 요약 → [증시] 뉴스 · 주요 지수 → [FICC] 뉴스 · 주요 지수(금리·환율·에너지) → 출처 한 줄
기사 줄 바로 아래에 발행처 원문 주소를 그대로 적는다. 특징주는 2단계에서 붙인다.
수치는 두 언어판에서 똑같이 코드가 만든다. LLM이 쓰는 것은 한 줄 요약과 기사 요약뿐이다.
"""
from datetime import date

WEEKDAYS_KO = "월화수목금토일"
WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TITLE = "Overnight Market Briefing"
BULLET = "•"

LABELS = {
    "ko": {
        "equity": "[증시]", "ficc": "[FICC]", "unch": "UNCH", "empty": "오늘 선별된 주요 뉴스 없음", "failed": "뉴스 요약 생성 실패",
        "missing": "{name} 수집 실패", "bond_closed": "미국 채권시장 휴장 ({d})",
        "stale": "*※ 표시는 기준 세션 봉이 아직 없어 표시한 날짜의 직전 종가입니다",
        "mismatch": "*주의: {name}: 야후·FRED 종가 불일치 ({pct}%)",
        "source": "*지수 종가 야후(FRED 교차검증) · 금리 미 재무부 · 환율 미국 장 종료({h}시 KST) 시점 시세 · 유가 정산가",
        "source_nohour": "*지수 종가 야후(FRED 교차검증) · 금리 미 재무부 · 환율 미국 장 종료 시점 시세 · 유가 정산가",
    },
    "en": {
        "equity": "[Equities]", "ficc": "[FICC]", "unch": "UNCH", "empty": "No major stories selected today", "failed": "News summary unavailable",
        "missing": "{name} unavailable", "bond_closed": "US bond market closed ({d})",
        "stale": "*※ marks a prior close: the bar for the reference session is not yet available (date shown)",
        "mismatch": "*Note: {name}: Yahoo vs FRED close mismatch ({pct}%)",
        "source": "*Indices: Yahoo Finance close (cross-checked vs FRED) · Yields: US Treasury · FX: as of US close ({h}:00 KST) · Oil: settlement price",
        "source_nohour": "*Indices: Yahoo Finance close (cross-checked vs FRED) · Yields: US Treasury · FX: as of US close · Oil: settlement price",
    },
}


def _num(x, nd, sign=False):
    x = round(x, nd)
    if x == 0:
        x = 0.0
    return f"{x:+,.{nd}f}" if sign else f"{x:,.{nd}f}"


def _md(iso, lang):
    d = date.fromisoformat(iso)
    if lang == "ko":
        return f"{d.month}/{d.day}({WEEKDAYS_KO[d.weekday()]})"
    return f"{WEEKDAYS_EN[d.weekday()]}, {MONTHS_EN[d.month - 1]} {d.day}"


def _name(r, lang):
    return r["name"] if lang == "ko" else r.get("name_en", r["name"])


def _mark(r):
    """기준 세션 봉이 없어 더 오래된 봉을 쓴 지표 표시 (예: ' ※10/9')."""
    if not r.get("stale"):
        return ""
    d = date.fromisoformat(r["asof"])
    return f" ※{d.month}/{d.day}"


def _missing(r, lang):
    return f"{BULLET} " + LABELS[lang]["missing"].format(name=_name(r, lang))


def _index_lines(data, lang):
    return [
        _missing(r, lang) if "error" in r
        else f"{BULLET} {_name(r, lang)} {_num(r['last'], 2)} ({_num(r['change_pct'], 2, True)}%){_mark(r)}"
        for r in data["indices"]
    ]


def _rate_lines(data, lang):
    L = LABELS[lang]
    rows = data["rates"]
    ok = [r for r in rows if "error" not in r]
    if ok and all(r["status"] == "closed" for r in ok):
        return [f"{BULLET} " + L["bond_closed"].format(d=_md(data["session_date"], lang))]
    lines = []
    for r in rows:
        if "error" in r:
            lines.append(_missing(r, lang))
            continue
        bp = round(r["change_bp"], 1)
        change = L["unch"] if bp == 0 else f"{_num(bp, 1, True)}bp"
        lines.append(f"{BULLET} {_name(r, lang)} {_num(r['last'], 2)}% ({change})")
    return lines


def _fx_energy_lines(data, lang):
    pct = lambda r, nd: f"{_num(r['last'], nd)} ({_num(r['change_pct'], 2, True)}%)"
    out = []
    for r in data["fx"]:
        n = _name(r, lang)
        if "error" in r:
            out.append(_missing(r, lang))
        elif r["key"] == "usdkrw":
            unit = ("원", "원") if lang == "ko" else ("", " won")
            out.append(f"{BULLET} {n} {_num(r['last'], 2)}{unit[0]} ({_num(r['change'], 2, True)}{unit[1]}){_mark(r)}")
        elif r["key"] == "eurusd":
            out.append(f"{BULLET} {n} {pct(r, 4)}{_mark(r)}")
        else:
            out.append(f"{BULLET} {n} {pct(r, 2)}{_mark(r)}")
    for r in data["energy"]:
        if "error" in r:
            out.append(_missing(r, lang))
            continue
        price = f"{_num(r['last'], 2)}달러" if lang == "ko" else f"${_num(r['last'], 2)}"
        out.append(f"{BULLET} {_name(r, lang)} {price} ({_num(r['change_pct'], 2, True)}%){_mark(r)}")
    return out


def _notes(data, lang):
    """데이터 품질 주석: 기준 세션 봉 누락(※ 한 줄), 야후·FRED 종가 불일치."""
    L = LABELS[lang]
    notes = []
    if any(r.get("stale") for g in ("indices", "fx", "energy") for r in data[g]):
        notes.append(L["stale"])
    for r in data["indices"]:
        chk = r.get("check") or {}
        if chk.get("status") == "mismatch":
            notes.append(L["mismatch"].format(name=_name(r, lang), pct=chk["diff_pct"]))
    return notes


def _news_lines(picks, candidates, lang, empty_text):
    """선택한 기사 → '• 요약 (출처)' 줄 + 바로 아래 원문 주소 줄. 원문 주소는 후보 데이터에서 id로 찾아 그대로 쓴다."""
    by_id = {c["id"]: c for c in candidates}
    if not picks:
        return [f"{BULLET} {empty_text}"]
    lines = []
    for p in picks:
        c = by_id[p["id"]]
        lines.append(f"{BULLET} {p[lang]} ({c['source']})")
        if c.get("url"):
            lines.append(f"  {c['url']}")
    return lines


def render(data, result=None, lang="ko", news_failed=False):
    """data: collect.collect 결과(+ data['news']), result: generate.generate 결과, lang: 'ko' | 'en'. 반환: 전송용 텍스트.

    result가 없으면 수치만 있는 브리핑(뉴스 블록 생략)을 만든다.
    """
    L = LABELS[lang]
    d = date.fromisoformat(data["today_kst"])
    if lang == "ko":
        date_line = f"{d.year}.{d.month:02d}.{d.day:02d}({WEEKDAYS_KO[d.weekday()]}) | 미국장 {_md(data['session_date'], 'ko')} 마감 기준"
    else:
        date_line = f"{WEEKDAYS_EN[d.weekday()]}, {MONTHS_EN[d.month - 1]} {d.day}, {d.year} | US close of {_md(data['session_date'], 'en')}"
    head = [TITLE, date_line]

    equity_news, ficc_news = [], []
    if result is not None:
        if result["summary"].get(lang):
            head.append(f"\"{result['summary'][lang]}\"")
        cands = data["news"]["candidates"]
        empty = L["failed"] if news_failed else L["empty"]  # 요약 생성에 실패했을 때는 사유를 밝혀 수치만이라도 보낸다
        equity_news = _news_lines(result["picks"]["equity"], cands, lang, empty)
        ficc_news = _news_lines(result["picks"]["ficc"], cands, lang, empty)

    equity = [L["equity"]] + equity_news + _index_lines(data, lang)
    ficc = [L["ficc"]] + ficc_news + _rate_lines(data, lang) + _fx_energy_lines(data, lang)
    hour = data.get("close_kst_hour")
    source = [L["source"].format(h=hour) if hour else L["source_nohour"]] + _notes(data, lang)

    sections = [head, equity, ficc, source]
    return "\n\n".join("\n".join(line for line in sec if line) for sec in sections if any(sec)).strip()
