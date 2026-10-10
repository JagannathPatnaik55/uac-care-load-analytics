from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uac_analytics.metrics import compute_kpis, derive_metrics, rolling_mean


def daily_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="D"),
            "is_observed": [True, True, False, True],
            "cbp_custody": [4, 5, np.nan, 3],
            "hhs_care": [6, 7, np.nan, 8],
            "transfers_to_hhs": [3, 5, np.nan, 0],
            "hhs_discharges": [1, 1, np.nan, 0],
        }
    )


def test_total_load_net_pressure_and_growth_require_consecutive_calendar_days() -> None:
    metrics = derive_metrics(daily_fixture())

    assert metrics.loc[0, "total_system_load"] == 10
    assert metrics.loc[0, "hhs_net_intake_pressure"] == 2
    assert metrics.loc[1, "care_load_growth_rate"] == pytest.approx(0.2)
    assert pd.isna(metrics.loc[2, "care_load_growth_rate"])
    assert pd.isna(metrics.loc[3, "care_load_growth_rate"])


def test_rolling_mean_requires_configured_calendar_coverage() -> None:
    series = pd.Series([1, 2, 3, 4, 5, 6, np.nan], index=pd.date_range("2024-01-01", periods=7))
    rolling = rolling_mean(series, window_days=7, min_coverage=0.8)
    assert rolling.iloc[-1] == 3.5

    series.iloc[1:3] = np.nan
    rolling = rolling_mean(series, window_days=7, min_coverage=0.8)
    assert pd.isna(rolling.iloc[-1])


def test_discharge_offset_ratio_is_unavailable_when_transfers_are_zero() -> None:
    data = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-01-01")],
            "cbp_custody": [2],
            "hhs_care": [10],
            "transfers_to_hhs": [0],
            "hhs_discharges": [3],
        }
    )
    result = compute_kpis(data)
    assert result["discharge_offset_ratio"].value is None
    assert "zero" in result["discharge_offset_ratio"].reason.lower()


def test_volatility_is_total_load_coefficient_of_variation_and_ratio_is_percent() -> None:
    data = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=2, freq="D"),
            "cbp_custody": [5, 10],
            "hhs_care": [5, 10],
            "transfers_to_hhs": [4, 6],
            "hhs_discharges": [2, 4],
        }
    )

    result = compute_kpis(data)

    assert result["care_load_volatility_index"].value == pytest.approx((np.std([10, 20], ddof=1) / 15) * 100)
    assert result["discharge_offset_ratio"].value == pytest.approx(60.0)
    assert result["discharge_offset_ratio"].unit == "percent"
    assert result["backlog_accumulation_rate"].value == pytest.approx(2.0)


def test_calendar_rolling_features_include_flow_series_and_coverage() -> None:
    data = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=7, freq="D"),
            "cbp_custody": [1, 2, 3, 4, 5, 6, 7],
            "hhs_care": [10, 10, 10, 10, 10, 10, 10],
            "cbp_daily_intake": [1, 1, 1, 1, 1, 1, 1],
            "transfers_to_hhs": [2, 2, 2, 2, 2, 2, 2],
            "hhs_discharges": [1, 1, 1, 1, 1, 1, 1],
        }
    )

    metrics = derive_metrics(data)

    assert metrics.loc[6, "cbp_daily_intake_rolling_7d_mean"] == 1
    assert metrics.loc[6, "transfers_to_hhs_rolling_7d_coverage"] == 1
    assert metrics.loc[6, "hhs_discharges_rolling_7d_mean"] == 1


def test_duplicate_dates_are_excluded_from_kpis_until_resolved() -> None:
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02"]),
            "cbp_custody": [2, 200, 2],
            "hhs_care": [10, 1000, 10],
            "transfers_to_hhs": [3, 300, 5],
            "hhs_discharges": [1, 100, 1],
        }
    )

    result = compute_kpis(data)

    assert result["net_intake_pressure"].value == 4
    assert result["total_children_under_care"].value == 12

