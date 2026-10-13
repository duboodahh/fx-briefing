"""브리핑 최종 텍스트 조립. 제목·수치·일정·기준일은 코드가 만들고, 뉴스 한 줄 요약만 LLM 결과를 받는다.

텔레그램은 일반 텍스트로 보낸다. (마크다운 특수문자 오류 방지, 4,096자 제한)
뉴스 원문 주소는 기사 바로 아래 줄에 그대로 적는다. (텔레그램이 자동으로 눌러지는 링크로 바꿔 주고, 미리보기는 끈다)
"""
from datetime import date, datetime

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
    """표시한 지표들의 기준을 같은 시점끼리 묶어 한 줄로. (기준이 서로 다른 것이 정상이므로 숨기지 않는다.)

    금리는 거래일 기준일(예: 10/12), 환율·유가는 수집 시점의 최신 시세라 수집 시각(예: 10/13 07시)으로 표기한다.
    """
    y, m = data["rates"]["yields"], data["markets"]
    snap = data.get("snapshot_kst")
    us_hide, kr_hide = _hidden(data)  # 숨긴 수치는 기준 줄에서도 뺀다
    entries = []  # (이름, 표기, 정렬키)

    def rate(name, keys, hide):
        dates = [] if hide else [y[k]["asof"] for k in keys if k in y]
        if dates:
            entries.append((name, _md(max(dates)), max(dates)))

    rate("미국채", ("us2y", "us10y"), us_hide)
    rate("국고채", ("kr3y", "kr10y"), kr_hide)
    for name, key in (("원/달러", "usdkrw"), ("달러/엔", "usdjpy"), ("DXY", "dxy"), ("WTI", "wti")):
        if key in m:
            label, sort_key = _quote_label(m[key]["asof"], snap)
            entries.append((name, label, sort_key))

    groups = {}
    for name, label, sort_key in entries:
        g = groups.setdefault(label, {"names": [], "key": sort_key})
        g["names"].append(name)
        g["key"] = max(g["key"], sort_key)
    parts = [
        f"{DOT.join(g['names']).replace(f'미국채{DOT}국고채', '금리')} {label}"
        for label, g in sorted(groups.items(), key=lambda kv: kv[1]["key"], reverse=True)
    ]
    return "*기준: " + " / ".join(parts) if parts else ""


def _quote_label(asof_iso, snapshot_iso):
    """(표기, 정렬키). 시세가 최근(수집일 기준 4일 이내)이면 수집 시각 '10/13 07시', 오래됐으면 봉 날짜."""
    if snapshot_iso:
        snap = datetime.fromisoformat(snapshot_iso)
        if 0 <= (snap.date() - date.fromisoformat(asof_iso)).days <= 4:
            return f"{snap.month}/{snap.day} {snap.hour:02d}시", snapshot_iso
    return _md(asof_iso), asof_iso


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


def _news_block(title, picks, items_by_id, empty_text, show_links=True):
    lines = [f"[{title}]"]
    if not picks:
        lines.append(f"{BULLET} {empty_text}")
    for p in picks[:NEWS_PER_REGION]:
        item = items_by_id[p["id"]]
        lines.append(f"{BULLET} {p['summary'].strip()} ({item['source']})")
        if show_links and item.get("url"):
            lines.append(f"  {item['url']}")
    return lines


def render(data, picks, empty_news_text="오늘 선별된 주요 뉴스 없음", show_links=True):
    """data: build_input.build 결과, picks: {'intl': [{id, summary}], 'kr': [...]}. 반환: 전송용 텍스트.

    뉴스 요약을 만들지 못했을 때는 empty_news_text로 사유를 밝혀 수치만이라도 보낼 수 있게 한다.
    """
    items_by_id = {n["id"]: n for n in data["news_intl"] + data["news_kr"]}
    d = date.fromisoformat(data["today_kst"])

    sections = [
        [TITLE, f"{d.year}.{d.month:02d}.{d.day:02d}({WEEKDAYS[d.weekday()]})"],
        _news_block("국외", picks.get("intl", []), items_by_id, empty_news_text, show_links),
        _news_block("국내", picks.get("kr", []), items_by_id, empty_news_text, show_links),
        _rate_lines(data),
        _market_lines(data),
        _event_lines(data),
        [_basis_line(data)],
    ]
    return "\n\n".join("\n".join(line for line in sec if line) for sec in sections if any(sec)).strip()
