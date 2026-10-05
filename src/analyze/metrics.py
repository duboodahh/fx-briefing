"""금리 계산 모듈. 브리핑에 쓰이는 숫자는 전부 여기서 계산한다. (LLM은 계산하지 않음)

시계열은 [(YYYY-MM-DD, 값(%)), ...] 오름차순 리스트. 변화·스프레드는 bp 단위.
"""


def _bp(x):
    return round(x * 100, 1)


def level_change(series):
    """최근 값과 직전 관측일 대비 변화(bp)."""
    (prev_d, prev), (last_d, last) = series[-2], series[-1]
    return {
        "last": last,
        "prev": prev,
        "change_bp": _bp(last - prev),
        "asof": last_d,
        "prev_asof": prev_d,
    }


def spread(a, b):
    """a - b 스프레드(bp). 두 시계열이 모두 값을 가진 최근 두 날짜끼리만 비교한다.

    발표 시차로 두 시계열의 마지막 날짜가 다를 수 있어, 공통 날짜 기준으로 계산하고
    사용한 기준일(asof, prev_asof)을 함께 돌려준다.
    """
    bd = dict(b)
    common = [(d, v - bd[d]) for d, v in a if d in bd]
    if len(common) < 2:
        raise ValueError("공통 날짜가 2개 미만이라 스프레드를 계산할 수 없음")
    (prev_d, prev), (last_d, last) = common[-2], common[-1]
    return {
        "last_bp": _bp(last),
        "prev_bp": _bp(prev),
        "change_bp": _bp(last - prev),
        "asof": last_d,
        "prev_asof": prev_d,
    }
