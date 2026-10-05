"""브리핑 최종 텍스트 조립. 제목·수치·일정·기준일은 코드가 만들고, 뉴스 한 줄 요약만 LLM 결과를 받는다.

텔레그램은 일반 텍스트로 보낸다. (마크다운 특수문자 오류 방지, 4,096자 제한)
"""
from datetime import date

WEEKDAYS = "월화수목금토일"
TITLE = "Daily Macro Issue Briefing"
NEWS_PER_REGION = 3
EVENT_LINES = 3
EVENT_WINDOW_DAYS = 7
BULLET = "•"  # 목록 항목 앞 기호 (U+2022)
DOT = "•"     # [환율•유가], 기준 줄의 구분 점. 얇은 가운뎃점(U+00B7)으로 되돌리려면 여기만 고친다.


def _num(x, nd, sign=False):
    """-0.0 같은 표기를 막고, 부호 표시 여부를 고른다."""
    x = round(x, nd)
    if x == 0:
        x = 0.0
    return f"{x:+,.{nd}f}" if sign else f"{x:,.{nd}f}"


def _md(iso):
    d = date.fromisoformat(iso)
    return f"{d.month}/{d.day}"


def _wd(iso):
    return WEEKDAYS[date.fromisoformat(iso).weekday()]


def _hidden(data):
    """(미국 금리 숨김, 한국 금리 숨김). 캘린더 정보가 없으면 숨기지 않는다."""
    cal = data.get("calendar") or {}
    return not cal.get("us_new", True), not cal.get("kr_new", True)


def _missing(label):
    return f"{BULLET} {label} 수집 실패"


def _rate_lines(data):
    y, s = data["rates"]["yields"], data["rates"]["spreads"]

    def yield_line(key, label):
        v = y.get(key)
        return _missing(label) if not v else f"{BULLET} {label} {_num(v['last'], 2)}% ({_num(v['change_bp'], 1, True)}bp)"

    def spread_line(key, label):
        v = s.get(key)
        return _missing(label) if not v else f"{BULLET} {label} {_num(v['last_bp'], 1, True)}bp ({_num(v['change_bp'], 1, True)}bp)"

    us_hide, kr_hide = _hidden(data)

    def closed_line(name, closed_dates):
        days = ", ".join(_md(d) for d in closed_dates)
        return f"{BULLET} {name} 휴장" + (f" ({days})" if days else "")

    cal = data.get("calendar") or {}
    lines = ["[금리]"]
    if us_hide:  # 직전 영업일 이후 미국 시장에 새 거래일이 없으면 수치를 숨기고 휴장으로 표시
        lines.append(closed_line("미국 채권시장", cal.get("us_closed", [])))
    else:
        lines += [
            yield_line("us10y", "미국 국채 10Y"),
            yield_line("us2y", "미국 국채 2Y"),
            spread_line("us_curve_10y2y", "미 10Y-2Y 장단기 금리차"),
        ]
    if kr_hide:
        lines.append(closed_line("한국 채권시장", cal.get("kr_closed", [])))
    else:
        lines += [
            yield_line("kr3y", "국고채 3Y"),
            yield_line("kr10y", "국고채 10Y"),
            spread_line("kr_curve_10y3y", "국고 10Y-3Y 스프레드"),
        ]
    if not us_hide and not kr_hide:  # 한미 금리차는 양쪽 데이터가 모두 새것일 때만
        lines.append(spread_line("kr_us_10y", "한미 10Y 금리차(국고-미 국채)"))
    return lines


def _market_lines(data):
    m = data["markets"]

    def line(key, label, fmt):
        v = m.get(key)
        return _missing(label) if not v else f"{BULLET} {label} {fmt(v)}"

    return [
        f"[환율{DOT}유가]",
        line("usdkrw", "원/달러", lambda v: f"{_num(v['last'], 2)}원 ({_num(v['change'], 2, True)}원)"),
        line("usdjpy", "달러/엔", lambda v: f"{_num(v['last'], 2)} ({_num(v['change'], 2, True)})"),
        line("dxy", "DXY", lambda v: f"{_num(v['last'], 2)} ({_num(v['change'], 2, True)})"),
        line("wti", "WTI", lambda v: f"{_num(v['last'], 2)}달러 ({_num(v['change'], 2, True)})"),
    ]


def _basis_line(data):
    """표시한 지표들의 기준일을 날짜별로 묶어 한 줄로. (기준일이 서로 다른 것이 정상이므로 숨기지 않는다.)"""
    y, m = data["rates"]["yields"], data["markets"]
    us_hide, kr_hide = _hidden(data)  # 숨긴 수치의 날짜는 기준 줄에서도 뺀다
    parts = [
        ("미국채", [] if us_hide else [y[k]["asof"] for k in ("us2y", "us10y") if k in y]),
        ("국고채", [] if kr_hide else [y[k]["asof"] for k in ("kr3y", "kr10y") if k in y]),
        ("원/달러", [m["usdkrw"]["asof"]] if "usdkrw" in m else []),
        ("달러/엔", [m["usdjpy"]["asof"]] if "usdjpy" in m else []),
        ("DXY", [m["dxy"]["asof"]] if "dxy" in m else []),
        ("WTI", [m["wti"]["asof"]] if "wti" in m else []),
    ]
    by_date = {}
    for label, dates in parts:
        if dates:
            by_date.setdefault(max(dates), []).append(label)
    groups = [
        f"{DOT.join(by_date[d]).replace(f'미국채{DOT}국고채', '금리')} {_md(d)}" for d in sorted(by_date, reverse=True)
    ]
    return "*기준: " + " / ".join(groups) if groups else ""


def _event_lines(data):
    """[주요 일정](7일 이내) 또는 [다음 주요 일정](없을 때 가장 가까운 1건) 블록. 일정이 없으면 빈 리스트."""
    evs = data["events"]
    near = [e for e in evs if e["days_left"] <= EVENT_WINDOW_DAYS][:EVENT_LINES]
    if near:
        header, picked = "[주요 일정]", near
    elif evs:
        header, picked = "[다음 주요 일정]", evs[:1]
    else:
        return []

    def fmt(e):
        when = f"{_md(e['kst_date'])}({_wd(e['kst_date'])})"
        return f"{when} {e['kst_time']} {e['name']}" if e["kst_time"] else f"{when} {e['name']}"

    return [header] + [fmt(e) for e in picked]


def _news_block(title, picks, items_by_id, empty_text):
    lines = [f"[{title}]"]
    if not picks:
        lines.append(f"{BULLET} {empty_text}")
    for p in picks[:NEWS_PER_REGION]:
        src = items_by_id[p["id"]]["source"]
        lines.append(f"{BULLET} {p['summary'].strip()} ({src})")
    return lines


def render(data, picks, empty_news_text="오늘 선별된 주요 뉴스 없음"):
    """data: build_input.build 결과, picks: {'intl': [{id, summary}], 'kr': [...]}. 반환: 전송용 텍스트.

    뉴스 요약을 만들지 못했을 때는 empty_news_text로 사유를 밝혀 수치만이라도 보낼 수 있게 한다.
    """
    items_by_id = {n["id"]: n for n in data["news_intl"] + data["news_kr"]}
    d = date.fromisoformat(data["today_kst"])

    sections = [
        [TITLE, f"{d.year}.{d.month:02d}.{d.day:02d}({WEEKDAYS[d.weekday()]})"],
        _news_block("국외", picks.get("intl", []), items_by_id, empty_news_text),
        _news_block("국내", picks.get("kr", []), items_by_id, empty_news_text),
        _rate_lines(data),
        _market_lines(data),
        _event_lines(data),
        [_basis_line(data)],
    ]
    return "\n\n".join("\n".join(line for line in sec if line) for sec in sections if any(sec)).strip()
