from __future__ import annotations

import pandas as pd

from uac_analytics.analysis import aggregate_periods, forecast_eligibility, identify_sustained_positive_windows


def test_monthly_summary_shows_observed_count_and_calendar_coverage() -> None:
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-03"]),
            "cbp_custody": [2, 4],
            "hhs_care": [10, 12],
            "transfers_to_hhs": [3, 2],
            "hhs_discharges": [1, 4],
        }
    )

    summary = aggregate_periods(data, "monthly", range_start="2024-01-01", range_end="2024-01-04")

    assert summary.loc[0, "observed_records"] == 2
    assert summary.loc[0, "possible_calendar_days"] == 4
    assert summary.loc[0, "coverage_pct"] == 50
    assert summary.loc[0, "transfers_observed_sum"] == 5


def test_sustained_pressure_windows_require_a_covered_seven_day_window() -> None:
    data = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=10, freq="D"),
            "hhs_net_intake_pressure": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
        }
    )

    windows = identify_sustained_positive_windows(data, window_days=7, min_coverage=0.8)

    assert windows[0]["start"] == pd.Timestamp("2024-01-01")
    assert windows[0]["end"] == pd.Timestamp("2024-01-10")
    assert windows[0]["window_days"] == 7
    assert windows[0]["minimum_coverage_pct"] == 100


def test_forecast_gate_uses_target_coverage_and_maximum_gap() -> None:
    daily = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=365, freq="D"),
            "is_observed": [True] * 365,
            "cbp_custody": [10] * 365,
            "hhs_care": [20] * 365,
        }
    )
    daily.loc[100:109, "hhs_care"] = pd.NA

    result = forecast_eligibility(daily, target="total_system_load")

    assert result["source_coverage_pct"] == 100
    assert result["target_coverage_pct"] < 100
    assert result["max_missing_streak_days"] == 10
    assert not result["eligible"]

