from pathlib import Path

from scripts.install_daily_timer import _build_daily_times, _build_daily_times_window


def test_build_daily_times() -> None:
    times = _build_daily_times("08:00", 3, 120)
    assert times == ["08:00", "10:00", "12:00"]


def test_build_daily_times_wraps_day() -> None:
    times = _build_daily_times("23:30", 3, 60)
    assert times == ["23:30", "00:30", "01:30"]


def test_build_daily_times_window() -> None:
    times = _build_daily_times_window("08:00", "12:00", 120)
    assert times == ["08:00", "10:00", "12:00"]
