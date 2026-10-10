"""Metric definitions for observed stock and flow records."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import DEFAULT_ROLLING_COVERAGE


@dataclass(frozen=True)
class KPIResult:
    """A KPI value together with its unit and interpretation caveat."""

    value: float | None
    reason: str
    unit: str = "children"
    as_of: pd.Timestamp | None = None


def rolling_mean(
    series: pd.Series,
    window_days: int,
    min_coverage: float = DEFAULT_ROLLING_COVERAGE,
) -> pd.Series:
    """Calculate a calendar-day rolling mean only when enough days were observed.

    The input must use a DatetimeIndex. It is reindexed to every calendar day
    between its endpoints; missing dates remain NaN and do not count as zero.
    """

    if window_days <= 0:
        raise ValueError("window_days must be a positive integer")
    if not 0 < min_coverage <= 1:
        raise ValueError("min_coverage must be greater than 0 and at most 1")
    if not isinstance(series.index, pd.DatetimeIndex):
        raise TypeError("rolling_mean requires a DatetimeIndex")
    values = pd.to_numeric(series, errors="coerce").sort_index()
    values = values.loc[~values.index.duplicated(keep=False)]
    if values.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], name=series.index.name))
    daily_index = pd.date_range(values.index.min(), values.index.max(), freq="D", name=values.index.name)
    values = values.reindex(daily_index)
    min_observations = max(1, math.ceil(window_days * min_coverage))
    result = values.rolling(window=window_days, min_periods=min_observations).mean()
    result.iloc[: window_days - 1] = np.nan
    return result


def rolling_coverage(series: pd.Series, window_days: int) -> pd.Series:
    """Return observed-date share for each calendar rolling window."""

    if window_days <= 0:
        raise ValueError("window_days must be a positive integer")
    if not isinstance(series.index, pd.DatetimeIndex):
        raise TypeError("rolling_coverage requires a DatetimeIndex")
    values = pd.to_numeric(series, errors="coerce").sort_index()
    values = values.loc[~values.index.duplicated(keep=False)]
    if values.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], name=series.index.name))
    daily_index = pd.date_range(values.index.min(), values.index.max(), freq="D", name=values.index.name)
    values = values.reindex(daily_index)
    result = values.notna().astype(float).rolling(window=window_days, min_periods=1).sum() / window_days
    result.iloc[: window_days - 1] = np.nan
    return result


def derive_metrics(data: pd.DataFrame) -> pd.DataFrame:
    """Add stock, flow, growth, cumulative-observed, and rolling measures.

    ``total_system_load`` is the sum of CBP and HHS active stocks. HHS net
    intake pressure is transfers to HHS minus HHS discharges. Growth is only
    calculated against the immediately preceding calendar day.
    """

    result = data.copy()
    if "date" not in result:
        raise ValueError("Derived metrics require a date column")
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.sort_values("date", kind="stable", na_position="last").reset_index(drop=True)
    for column in ("cbp_daily_intake", "cbp_custody", "hhs_care", "transfers_to_hhs", "hhs_discharges"):
        if column not in result:
            result[column] = np.nan

    result["total_system_load"] = result["cbp_custody"] + result["hhs_care"]
    result["hhs_net_intake_pressure"] = result["transfers_to_hhs"] - result["hhs_discharges"]
    previous_date = result["date"].shift(1)
    previous_load = result["total_system_load"].shift(1)
    consecutive = result["date"].sub(previous_date).dt.days.eq(1)
    valid_growth = consecutive & previous_load.notna() & previous_load.ne(0) & result["total_system_load"].notna()
    result["care_load_growth_rate"] = np.nan
    result.loc[valid_growth, "care_load_growth_rate"] = (
        result.loc[valid_growth, "total_system_load"] / previous_load.loc[valid_growth] - 1
    )
    result["cumulative_observed_net_pressure"] = result["hhs_net_intake_pressure"].cumsum()
    result["cumulative_observed_cbp_stock"] = result["cbp_custody"].cumsum()
    result["cumulative_observed_hhs_stock"] = result["hhs_care"].cumsum()
    result["cumulative_observed_total_stock"] = result["total_system_load"].cumsum()

    if not result["date"].dropna().duplicated().any() and result["date"].notna().any():
        indexed = result.set_index("date")
        for metric in (
            "total_system_load", "cbp_custody", "hhs_care", "cbp_daily_intake",
            "transfers_to_hhs", "hhs_discharges", "hhs_net_intake_pressure",
        ):
            values = indexed[metric]
            for window in (7, 14):
                rolled = rolling_mean(values, window)
                coverage = rolling_coverage(values, window)
                result[f"{metric}_rolling_{window}d_mean"] = result["date"].map(rolled)
                result[f"{metric}_rolling_{window}d_coverage"] = result["date"].map(coverage)
    else:
        for metric in (
            "total_system_load", "cbp_custody", "hhs_care", "cbp_daily_intake",
            "transfers_to_hhs", "hhs_discharges", "hhs_net_intake_pressure",
        ):
            for window in (7, 14):
                result[f"{metric}_rolling_{window}d_mean"] = np.nan
                result[f"{metric}_rolling_{window}d_coverage"] = np.nan
    return result


def compute_kpis(data: pd.DataFrame) -> dict[str, KPIResult]:
    """Calculate the five requested KPIs for the selected observed records."""

    source = data.copy()
    if "date" in source:
        source["date"] = pd.to_datetime(source["date"], errors="coerce")
        source = source.loc[source["date"].notna()]
    if "is_observed" in source:
        source = source.loc[source["is_observed"].fillna(False)]
    if "duplicate_date" in source:
        source = source.loc[~source["duplicate_date"].fillna(False)]
    elif "date" in source and source["date"].duplicated(keep=False).any():
        source = source.loc[~source["date"].duplicated(keep=False)]
    metrics = derive_metrics(source)

    valid_load = metrics.loc[metrics["total_system_load"].notna()]
    if valid_load.empty:
        total = KPIResult(None, "No date has both CBP and HHS active-load values.")
    else:
        latest = valid_load.sort_values("date").iloc[-1]
        total = KPIResult(
            float(latest["total_system_load"]),
            "Latest date with both active-load values; CBP custody + HHS care.",
            as_of=pd.Timestamp(latest["date"]),
        )

    pressure = metrics["hhs_net_intake_pressure"].dropna()
    net = (
        KPIResult(
            float(pressure.sum()),
            f"Sum across {len(pressure)} observed reporting records. Positive means transfers exceeded discharges; negative means discharges exceeded transfers. Not a measured backlog.",
            "children across observed records",
        )
        if not pressure.empty
        else KPIResult(None, "No observed transfer and discharge pair is available.", "children across observed records")
    )

    load = valid_load["total_system_load"].dropna()
    load_mean = float(load.mean()) if not load.empty else 0.0
    volatility = (
        KPIResult(float(load.std(ddof=1) / load_mean * 100), "Sample standard deviation of valid observed Total System Load divided by its mean, multiplied by 100. Descriptive variability, not an official HHS standard.", "percent coefficient of variation")
        if len(load) >= 2 and load_mean != 0
        else KPIResult(None, "At least two valid load values and a nonzero mean are needed.", "percent coefficient of variation")
    )

    positive_pressure = pressure.loc[pressure > 0]
    backlog_rate = (
        KPIResult(
            float(positive_pressure.mean()),
            f"Mean of {len(positive_pressure)} positive HHS net-flow observations; a pressure proxy, not a directly measured backlog or calendar-day rate.",
            "children per observed reporting record",
        )
        if not positive_pressure.empty
        else KPIResult(None, "No positive observed HHS net-flow value is available.", "children per observed reporting record")
    )

    transfers = metrics["transfers_to_hhs"].dropna().sum(min_count=1)
    discharges = metrics["hhs_discharges"].dropna().sum(min_count=1)
    if pd.isna(transfers) or transfers == 0:
        offset = KPIResult(None, "Ratio is undefined because observed transfers sum to zero.", "ratio")
    elif pd.isna(discharges):
        offset = KPIResult(None, "No observed HHS discharge values are available.", "ratio")
    else:
        offset = KPIResult(
            float(discharges / transfers * 100),
            "Observed-record HHS discharges divided by observed-record transfers to HHS, multiplied by 100; not a placement success rate.",
            "percent",
        )

    return {
        "total_children_under_care": total,
        "net_intake_pressure": net,
        "care_load_volatility_index": volatility,
        "backlog_accumulation_rate": backlog_rate,
        "discharge_offset_ratio": offset,
    }
