"""브리핑 본문의 숫자가 입력 데이터에 있는 값인지 대조한다. (환각 방지 2차 장치)

대조 대상은 '숫자처럼 보이는 것' 중 소수점이 있거나, 천 단위 쉼표가 있거나, %·bp가 붙은 값이다.
날짜(10/28)·시각(21:30)·연도·단순 개수(3개)는 대상이 아니다.
허용 값 = 입력 JSON의 모든 숫자(부호 무시) + 뉴스·일정 문자열에 들어 있는 숫자.
본문 숫자는 적힌 자릿수까지 반올림했을 때 허용 값과 같으면 통과한다. (1,345 ← 1345.08)
"""
import json
import re
from decimal import Decimal

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+"
# 선택 부호 + 숫자 + 선택 단위
_TOKEN = re.compile(rf"(?<![\w.\-/:])([+\-−]?)({_NUM})(?![\w/:]*\d)(\s?(?:%|bp|bps))?")


def _to_decimal(s):
    return Decimal(s.replace(",", ""))


def _decimals(s):
    return len(s.split(".")[1]) if "." in s else 0


def _extract(text, only_checkable):
    out = []
    for m in _TOKEN.finditer(text):
        num, unit = m.group(2), (m.group(3) or "").strip()
        has_dec, has_comma = "." in num, "," in num
        value = _to_decimal(num)
        if only_checkable:
            is_year = (not has_dec and not has_comma and 1900 <= value <= 2100)
            if is_year or not (has_dec or has_comma or unit):
                continue
        out.append((num, value))
    return out


def _walk_numbers(obj, acc):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        acc.add(abs(Decimal(str(obj))))
    elif isinstance(obj, str):
        for _, v in _extract(obj, only_checkable=False):
            acc.add(abs(v))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_numbers(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _walk_numbers(v, acc)


def allowed_numbers(data):
    acc = set()
    _walk_numbers(data, acc)
    return acc


def find_unverified(text, data):
    """입력에 근거가 없는 숫자 문자열 목록(중복 제거, 등장 순서 유지)."""
    allowed = allowed_numbers(data)
    bad = []
    for raw, value in _extract(text, only_checkable=True):
        v = abs(value)
        tol = Decimal(5) / (Decimal(10) ** (_decimals(raw) + 1))  # 0.5 * 10^-자릿수
        if not any(abs(v - a) <= tol for a in allowed) and raw not in bad:
            bad.append(raw)
    return bad


def check(text, data):
    return find_unverified(text, json.loads(json.dumps(data)))
