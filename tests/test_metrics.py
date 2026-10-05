import pytest

from src.analyze import metrics


def test_level_change_bp():
    s = [("2026-09-30", 4.88), ("2026-10-01", 4.78)]
    r = metrics.level_change(s)
    assert r["last"] == 4.78
    assert r["change_bp"] == -10.0
    assert (r["asof"], r["prev_asof"]) == ("2026-10-01", "2026-09-30")


def test_spread_bp_and_change():
    a = [("2026-09-30", 5.29), ("2026-10-01", 5.24)]  # 10Y
    b = [("2026-09-30", 4.88), ("2026-10-01", 4.78)]  # 2Y
    r = metrics.spread(a, b)
    assert r["last_bp"] == 46.0   # 5.24 - 4.78
    assert r["prev_bp"] == 41.0   # 5.29 - 4.88
    assert r["change_bp"] == 5.0


def test_spread_uses_common_dates_only():
    # a는 10-02까지, b는 10-01까지 → 10-02는 건너뛰고 공통 날짜(09-30, 10-01)로 계산
    a = [("2026-09-30", 3.00), ("2026-10-01", 3.10), ("2026-10-02", 3.50)]
    b = [("2026-09-29", 9.99), ("2026-09-30", 2.00), ("2026-10-01", 2.20)]
    r = metrics.spread(a, b)
    assert r["asof"] == "2026-10-01"
    assert r["prev_asof"] == "2026-09-30"
    assert r["last_bp"] == 90.0
    assert r["change_bp"] == -10.0


def test_spread_negative_value_is_kept():
    r = metrics.spread([("d1", 3.0), ("d2", 3.1)], [("d1", 4.0), ("d2", 4.2)])
    assert r["last_bp"] == -110.0


def test_spread_needs_two_common_dates():
    with pytest.raises(ValueError):
        metrics.spread([("2026-10-01", 3.0)], [("2026-10-01", 2.0), ("2026-10-02", 2.1)])
