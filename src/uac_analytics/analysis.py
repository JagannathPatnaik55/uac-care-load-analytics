"""Coverage-aware period summaries, pressure windows, and forecast gating."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import FORECAST_MAX_GAP_DAYS, FORECAST_MIN_COVERAGE
from .metrics import derive_metrics, rolling_coverage, rolling_mean


def _unique_dated_records(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    dated = data.loc[pd.to_datetime(data["date"], errors="coerce").notna()].copy()
    dated["date"] = pd.to_datetime(dated["date"])
    duplicate = dated["date"].duplicated(keep=False)
    if "duplicate_date" in dated:
        duplicate |= dated["duplicate_date"].fillna(False).astype(bool)
    ambiguous = dated.loc[duplicate, "date"]
    return dated.loc[~duplicate].copy(), ambiguous


def _period_start(dates: pd.Series, granularity: str) -> pd.Series:
    if granularity == "daily":
        return dates.dt.normalize()
    if granularity == "weekly":
        return dates.dt.to_period("W-SUN").dt.start_time
    if granularity == "monthly":
        return dates.dt.to_period("M").dt.start_time
    if granularity == "yearly":
        return dates.dt.to_period("Y").dt.start_time
    raise ValueError("granularity must be daily, weekly, monthly, or yearly")


def aggregate_periods(
    data: pd.DataFrame,
    granularity: str,
    range_start: Any | None = None,
    range_end: Any | None = None,
) -> pd.DataFrame:
    """Summarize observed rows and report coverage for each calendar period.

    Flow totals are sums of observed reporting records. Duplicate dates are
    excluded from period calculations and counted as ambiguous dates.
    """

    if data.empty:
        return pd.DataFrame(
            columns=[
                "period_start", "period_end", "observed_records", "possible_calendar_days",
                "coverage_pct", "ambiguous_duplicate_days", "cbp_custody_mean", "hhs_care_mean",
                "total_system_load_mean", "total_system_load_max", "transfers_observed_sum",
                "discharges_observed_sum", "net_pressure_observed_sum", "net_pressure_mean",
            ]
        )
    clean, ambiguous_dates = _unique_dated_records(data)
    lower = pd.Timestamp(range_start).normalize() if range_start is not None else pd.to_datetime(data["date"], errors="coerce").min().normalize()
    upper = pd.Timestamp(range_end).normalize() if range_end is not None else pd.to_datetime(data["date"], errors="coerce").max().normalize()
    if pd.isna(lower) or pd.isna(upper) or upper < lower:
        return pd.DataFrame()
    clean = clean.loc[clean["date"].between(lower, upper)].copy()
    if clean.empty and ambiguous_dates.empty:
        return pd.DataFrame()
    if not clean.empty:
        clean = derive_metrics(clean)
        clean["period_start"] = _period_start(clean["date"], granularity)
        grouped = {key: value for key, value in clean.groupby("period_start", sort=True)}
    else:
        grouped = {}
    ambiguous_dates = pd.Series(pd.to_datetime(ambiguous_dates).dropna().unique())
    for date in ambiguous_dates:
        date = pd.Timestamp(date)
        if lower <= date <= upper:
            key = _period_start(pd.Series([date]), granularity).iloc[0]
            grouped.setdefault(key, pd.DataFrame())

    rows: list[dict[str, Any]] = []
    for key in sorted(grouped):
        group = grouped[key]
        if granularity == "daily":
            natural_end = key
        elif granularity == "weekly":
            natural_end = key + pd.Timedelta(days=6)
        elif granularity == "monthly":
            natural_end = key + pd.offsets.MonthEnd(0)
        else:
            natural_end = key + pd.offsets.YearEnd(0)
        period_lower = max(key, lower)
        period_upper = min(natural_end, upper)
        possible = max((period_upper - period_lower).days + 1, 0)
        in_period_ambiguous = int(((ambiguous_dates >= period_lower) & (ambiguous_dates <= period_upper)).sum())

        def mean_if_available(column: str) -> float:
            return float(group[column].mean()) if not group.empty and column in group and group[column].notna().any() else np.nan

        def sum_if_available(column: str) -> float:
            return float(group[column].sum(min_count=1)) if not group.empty and column in group else np.nan

        rows.append(
            {
                "period_start": key,
                "period_end": natural_end,
                "observed_records": int(group["date"].nunique()) if not group.empty else 0,
                "possible_calendar_days": possible,
                "coverage_pct": round((group["date"].nunique() / possible * 100), 2) if possible else np.nan,
                "ambiguous_duplicate_days": in_period_ambiguous,
                "cbp_custody_mean": mean_if_available("cbp_custody"),
                "hhs_care_mean": mean_if_available("hhs_care"),
                "total_system_load_mean": mean_if_available("total_system_load"),
                "total_system_load_max": float(group["total_system_load"].max()) if not group.empty and group["total_system_load"].notna().any() else np.nan,
                "transfers_observed_sum": sum_if_available("transfers_to_hhs"),
                "discharges_observed_sum": sum_if_available("hhs_discharges"),
                "net_pressure_observed_sum": sum_if_available("hhs_net_intake_pressure"),
                "net_pressure_mean": mean_if_available("hhs_net_intake_pressure"),
            }
        )
    return pd.DataFrame(rows).sort_values("period_start").reset_index(drop=True)


def identify_sustained_positive_windows(
    data: pd.DataFrame,
    window_days: int = 7,
    min_coverage: float = 0.8,
) -> list[dict[str, Any]]:
    """Find periods with positive rolling HHS net flow and qualifying coverage.

    Each returned span groups consecutive calendar dates whose trailing
    ``window_days`` observed-record mean is positive. Every evaluated window
    must meet ``min_coverage``; missing days remain absent from the denominator.
    """

    if window_days <= 0:
        raise ValueError("window_days must be positive")
    if not 0 < min_coverage <= 1:
        raise ValueError("min_coverage must be greater than 0 and at most 1")
    if data.empty or "hhs_net_intake_pressure" not in data:
        return []
    clean, _ = _unique_dated_records(data)
    clean = clean.sort_values("date")
    if clean.empty:
        return []
    pressure = clean.set_index("date")["hhs_net_intake_pressure"]
    rolling = rolling_mean(pressure, window_days, min_coverage)
    coverage = rolling_coverage(pressure, window_days)
    qualifying = rolling.notna() & rolling.gt(0) & coverage.ge(min_coverage)
    windows: list[dict[str, Any]] = []
    run: list[pd.Timestamp] = []
    run_coverage: list[float] = []
    for date in qualifying.index:
        if bool(qualifying.loc[date]):
            run.append(date)
            run_coverage.append(float(coverage.loc[date]))
        elif run:
            windows.append(
                {
                    "start": run[0] - pd.Timedelta(days=window_days - 1),
                    "end": run[-1],
                    "days": (run[-1] - run[0]).days + window_days,
                    "window_days": window_days,
                    "qualifying_windows": len(run),
                    "minimum_coverage_pct": round(min(run_coverage) * 100, 1),
                }
            )
            run, run_coverage = [], []
    if run:
        windows.append(
            {
                "start": run[0] - pd.Timedelta(days=window_days - 1),
                "end": run[-1],
                "days": (run[-1] - run[0]).days + window_days,
                "window_days": window_days,
                "qualifying_windows": len(run),
                "minimum_coverage_pct": round(min(run_coverage) * 100, 1),
            }
        )
    return windows


def forecast_eligibility(daily_index: pd.DataFrame, target: str = "total_system_load") -> dict[str, Any]:
    """Apply a conservative target-specific daily-coverage gate; no model is fit."""

    if daily_index.empty:
        return {
            "eligible": False,
            "overall_coverage_pct": 0.0,
            "source_coverage_pct": 0.0,
            "target_coverage_pct": 0.0,
            "trailing_365_coverage_pct": 0.0,
            "max_missing_streak_days": 0,
            "target": target,
            "reason": "No valid dated observations are available.",
        }
    data = daily_index.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if target not in data:
        data = derive_metrics(data)
    if target not in data:
        raise ValueError(f"Forecast target is not available: {target}")
    source_observed = data["is_observed"].fillna(False).astype(bool)
    target_observed = source_observed & data[target].notna()
    if "duplicate_date" in data:
        target_observed &= ~data["duplicate_date"].fillna(False).astype(bool)
    source_coverage = float(source_observed.mean() * 100)
    overall = float(target_observed.mean() * 100)
    end = pd.Timestamp(data["date"].max())
    trailing_mask = data["date"].between(end - pd.Timedelta(days=364), end)
    trailing = data.loc[trailing_mask]
    trailing_target_observed = target_observed.loc[trailing_mask]
    trailing_coverage = float(trailing_target_observed.mean() * 100) if not trailing.empty else 0.0
    full_trailing_window = len(trailing) == 365
    missing = (~target_observed).astype(int)
    groups = missing.ne(missing.shift(fill_value=0)).cumsum()
    streaks = missing.groupby(groups).sum()
    max_gap = int(streaks.max()) if not streaks.empty else 0
    eligible = overall >= FORECAST_MIN_COVERAGE * 100 and full_trailing_window and trailing_coverage >= FORECAST_MIN_COVERAGE * 100 and max_gap <= FORECAST_MAX_GAP_DAYS
    reasons = []
    if overall < FORECAST_MIN_COVERAGE * 100:
        reasons.append(f"{target} full-span coverage is {overall:.1f}% (requires at least {FORECAST_MIN_COVERAGE:.0%})")
    if trailing_coverage < FORECAST_MIN_COVERAGE * 100:
        reasons.append(f"{target} trailing-365-day coverage is {trailing_coverage:.1f}% (requires at least {FORECAST_MIN_COVERAGE:.0%})")
    if not full_trailing_window:
        reasons.append(f"only {len(trailing)} calendar days are available in the trailing window (requires 365)")
    if max_gap > FORECAST_MAX_GAP_DAYS:
        reasons.append(f"the longest reporting gap is {max_gap} days (maximum allowed is {FORECAST_MAX_GAP_DAYS})")
    return {
        "eligible": eligible,
        "overall_coverage_pct": overall,
        "source_coverage_pct": source_coverage,
        "target_coverage_pct": overall,
        "trailing_365_coverage_pct": trailing_coverage,
        "max_missing_streak_days": max_gap,
        "target": target,
        "reason": "Coverage meets the configured gate." if eligible else "; ".join(reasons),
    }
