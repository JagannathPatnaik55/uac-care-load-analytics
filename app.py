"""Streamlit dashboard for coverage-aware UAC care-load monitoring."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from uac_analytics.analysis import aggregate_periods, forecast_eligibility, identify_sustained_positive_windows
from uac_analytics.charts import COLORS, make_plotly_figure
from uac_analytics.config import METRIC_LABELS, RAW_DATA_PATH
from uac_analytics.data_loader import DatasetBundle, load_dataset
from uac_analytics.data_validation import validate_dataset
from uac_analytics.feature_engineering import add_derived_metrics
from uac_analytics.metrics import KPIResult, compute_kpis


SERIES_OPTIONS = {
    "Total System Load": "total_system_load",
    "CBP Active Load": "cbp_custody",
    "HHS Active Load": "hhs_care",
    "CBP Daily Intake": "cbp_daily_intake",
    "Transfers to HHS": "transfers_to_hhs",
    "HHS Discharges": "hhs_discharges",
    "HHS Net Intake Pressure": "hhs_net_intake_pressure",
}
DEFAULT_SERIES = ["Total System Load", "CBP Active Load", "HHS Active Load"]


@st.cache_data(show_spinner=False)
def _analyze_source(csv_bytes: bytes, source_name: str) -> tuple[DatasetBundle, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Cache by uploaded bytes so a replacement file cannot reuse stale results."""

    bundle = load_dataset(BytesIO(csv_bytes))
    bundle.source_name = source_name
    flags, quality = validate_dataset(bundle)
    observed_metrics = add_derived_metrics(bundle.records)
    daily_metrics = add_derived_metrics(bundle.daily_index)
    return bundle, flags, quality, observed_metrics, daily_metrics


def _format_value(result: KPIResult) -> str:
    if result.value is None:
        return "Not available"
    if result.unit in {"percent", "percent coefficient of variation"}:
        return f"{result.value:.1f}%"
    if result.unit == "children per observed reporting record":
        return f"{result.value:,.1f}"
    return f"{result.value:,.0f}"


def _selection_frame(
    observed: pd.DataFrame,
    daily: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    granularity: str,
) -> pd.DataFrame:
    if granularity == "daily":
        return daily.loc[daily["date"].between(start, end)].copy()
    period = aggregate_periods(observed, granularity, start, end)
    if period.empty:
        return pd.DataFrame(columns=["date", *SERIES_OPTIONS.values()])
    rename = {
        "period_start": "date",
        "total_system_load_mean": "total_system_load",
        "cbp_custody_mean": "cbp_custody",
        "hhs_care_mean": "hhs_care",
        "transfers_observed_sum": "transfers_to_hhs",
        "discharges_observed_sum": "hhs_discharges",
        "net_pressure_observed_sum": "hhs_net_intake_pressure",
    }
    selected = period.rename(columns=rename).copy()
    selected["cbp_daily_intake"] = np.nan
    return selected


def _coverage_text(daily: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> tuple[int, int, float]:
    selected = daily.loc[daily["date"].between(start, end)]
    possible = int((end.normalize() - start.normalize()).days + 1)
    observed = int(selected["is_observed"].fillna(False).sum()) if not selected.empty else 0
    return observed, possible, observed / possible * 100 if possible else 0.0


def _automatic_observation(metrics: pd.DataFrame, observed: int, possible: int, coverage: float) -> str:
    loads = metrics.loc[metrics["total_system_load"].notna()] if not metrics.empty else metrics
    if "duplicate_date" in loads:
        loads = loads.loc[~loads["duplicate_date"].fillna(False)]
    if loads.empty:
        return f"No complete active-load observation is available in this selection. Date coverage is {observed:,}/{possible:,} days ({coverage:.1f}%)."
    peak = loads.loc[loads["total_system_load"].idxmax()]
    median = loads["total_system_load"].median()
    return (
        f"Among {len(loads):,} dates with both active-load counts, the highest observed Total System Load was "
        f"{peak['total_system_load']:,.0f} on {peak['date']:%B %d, %Y}; the observed-date median was {median:,.0f}. "
        f"Coverage was {observed:,}/{possible:,} calendar days ({coverage:.1f}%). These are observed counts, not capacity findings."
    )


def _add_rolling_overlays(figure: go.Figure, data: pd.DataFrame) -> None:
    for column, label, color in (
        ("total_system_load_rolling_7d_mean", "7-day mean (≥80% coverage)", "#D97706"),
        ("total_system_load_rolling_14d_mean", "14-day mean (≥80% coverage)", "#238B78"),
    ):
        if column in data:
            figure.add_trace(
                go.Scatter(
                    x=data["date"], y=data[column], mode="lines", name=label,
                    connectgaps=False, line={"color": color, "width": 2, "dash": "dash"},
                )
            )


def _render_downloads(observed: pd.DataFrame, flags: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> None:
    filtered = observed.loc[observed["date"].between(start, end)].copy()
    filtered_flags = flags.loc[flags["date"].isna() | flags["date"].between(start, end)].copy()
    stem = f"{start:%Y%m%d}_{end:%Y%m%d}"
    st.download_button(
        "Download filtered derived records (CSV)",
        filtered.to_csv(index=False, na_rep="").encode("utf-8"),
        file_name=f"uac_derived_metrics_{stem}.csv",
        mime="text/csv",
        key="download_metrics",
    )
    st.download_button(
        "Download data-quality flags (CSV)",
        filtered_flags.to_csv(index=False, na_rep="").encode("utf-8"),
        file_name=f"uac_data_quality_flags_{stem}.csv",
        mime="text/csv",
        key="download_flags",
    )


def _render_overview(
    observed: pd.DataFrame,
    daily: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    granularity: str,
    selected_columns: list[str],
    percentile: int,
) -> None:
    filtered_records = observed.loc[observed["date"].between(start, end)].copy()
    filtered_daily = daily.loc[daily["date"].between(start, end)].copy()
    analytical_records = filtered_records.loc[~filtered_records["duplicate_date"].fillna(False)] if "duplicate_date" in filtered_records else filtered_records
    observed_days, possible_days, coverage = _coverage_text(daily, start, end)
    kpis = compute_kpis(filtered_records)
    st.subheader("System Load Overview")
    st.caption(
        f"Selected period: {start:%b %d, %Y} – {end:%b %d, %Y} · Latest date with both stock counts: "
        f"{kpis['total_children_under_care'].as_of:%b %d, %Y}" if kpis["total_children_under_care"].as_of is not None else
        f"Selected period: {start:%b %d, %Y} – {end:%b %d, %Y} · No date has both stock counts"
    )
    st.caption(f"Observed reporting dates: {observed_days:,} of {possible_days:,} possible ({coverage:.1f}% coverage).")

    labels = [
        ("Total Children Under Care", "total_children_under_care"),
        ("Net Intake Pressure", "net_intake_pressure"),
        ("Care Load Volatility Index", "care_load_volatility_index"),
        ("Backlog Accumulation Rate", "backlog_accumulation_rate"),
        ("Discharge Offset Ratio", "discharge_offset_ratio"),
    ]
    columns = st.columns(5)
    for column, (label, key) in zip(columns, labels):
        result = kpis[key]
        column.metric(label, _format_value(result), help=f"{result.reason} Unit: {result.unit}.")

    selected_frame = _selection_frame(filtered_records, filtered_daily, start, end, granularity)
    threshold = None
    load_data = analytical_records["total_system_load"].dropna()
    if not load_data.empty:
        threshold = float(load_data.quantile(percentile / 100))
    display_columns = [column for column in selected_columns if column in selected_frame.columns]
    figure = make_plotly_figure(
        selected_frame,
        display_columns,
        "Total System Load and Selected Series",
        "Observed counts / observed-record flows",
        threshold=threshold if "total_system_load" in display_columns else None,
    )
    if granularity == "daily" and "total_system_load" in display_columns:
        _add_rolling_overlays(figure, selected_frame)
    st.plotly_chart(figure, use_container_width=True)
    st.info(_automatic_observation(analytical_records, observed_days, possible_days, coverage))
    st.caption("Daily line gaps indicate dates with no source observation. A period-flow series shows sums of observed reporting records.")


def _render_load_comparison(observed: pd.DataFrame, daily: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, granularity: str, selected_columns: list[str]) -> None:
    st.subheader("CBP vs HHS Active Load")
    records = observed.loc[observed["date"].between(start, end)]
    calendar = daily.loc[daily["date"].between(start, end)]
    frame = _selection_frame(records, calendar, start, end, granularity)
    columns = [column for column in ("cbp_custody", "hhs_care") if column in selected_columns]
    figure = make_plotly_figure(frame, columns, "Active Stock Comparison", "Children in active custody/care")
    st.plotly_chart(figure, use_container_width=True)
    st.caption("These series are active stocks. Daily intake, transfer, and discharge flows are shown separately on the pressure tab.")


def _render_pressure(observed: pd.DataFrame, daily: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, granularity: str, selected_columns: list[str]) -> None:
    st.subheader("Intake, Transfer, and Discharge Pressure")
    records = observed.loc[observed["date"].between(start, end)]
    calendar = daily.loc[daily["date"].between(start, end)]
    frame = _selection_frame(records, calendar, start, end, granularity)
    flow_figure = make_plotly_figure(
        frame,
        [column for column in ("cbp_daily_intake", "transfers_to_hhs", "hhs_discharges") if column in selected_columns],
        "Daily Flows (period totals are observed-record sums)",
        "Children per observed record / observed-record sum",
    )
    st.plotly_chart(flow_figure, use_container_width=True)
    pressure_figure = make_plotly_figure(
        frame,
        ["hhs_net_intake_pressure"] if "hhs_net_intake_pressure" in selected_columns else [],
        "HHS Net Intake Pressure: Transfers to HHS − HHS Discharges",
        "Children per observed reporting record",
        zero_line=True,
    )
    st.plotly_chart(pressure_figure, use_container_width=True)
    if "duplicate_date" in records:
        records = records.loc[~records["duplicate_date"].fillna(False)]
        records = add_derived_metrics(records)
    cumulative = records["cumulative_observed_net_pressure"].dropna()
    if not cumulative.empty:
        st.metric("Cumulative observed-record net flow", f"{cumulative.iloc[-1]:,.0f} children")
        st.caption("This is a running sum of observed daily flows. It is not a directly measured backlog and does not impute missing dates.")
    pressure_windows = identify_sustained_positive_windows(records, window_days=7, min_coverage=0.8)
    st.markdown("**Sustained pressure proxy: positive trailing 7-day mean with at least 80% reporting-date coverage**")
    if pressure_windows:
        st.dataframe(
            pd.DataFrame(pressure_windows).rename(
                columns={
                    "start": "Window start",
                    "end": "Last qualifying endpoint",
                    "days": "Span days",
                    "window_days": "Window length",
                    "qualifying_windows": "Qualifying endpoints",
                    "minimum_coverage_pct": "Minimum window coverage (%)",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No qualifying positive 7-day window was found in this date selection.")


def _render_trends(observed: pd.DataFrame, daily: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, granularity: str, selected_columns: list[str]) -> None:
    st.subheader("Temporal Trends and Variability")
    selected = observed.loc[observed["date"].between(start, end)]
    if "duplicate_date" in selected:
        selected = selected.loc[~selected["duplicate_date"].fillna(False)]
    summary = aggregate_periods(selected, granularity, start, end)
    if not summary.empty:
        visible = summary.rename(
            columns={
                "period_start": "Period starts",
                "observed_records": "Observed dates",
                "possible_calendar_days": "Possible dates",
                "coverage_pct": "Coverage (%)",
                "total_system_load_mean": "Mean total load",
                "total_system_load_max": "Maximum observed load",
                "transfers_observed_sum": "Transfers: observed-record sum",
                "discharges_observed_sum": "Discharges: observed-record sum",
                "net_pressure_observed_sum": "Net pressure: observed-record sum",
            }
        )
        display = [
            "Period starts", "Observed dates", "Possible dates", "Coverage (%)", "Mean total load",
            "Maximum observed load", "Transfers: observed-record sum", "Discharges: observed-record sum",
            "Net pressure: observed-record sum",
        ]
        st.dataframe(visible[display], use_container_width=True, hide_index=True)
    values = selected["total_system_load"].dropna() if "total_system_load" in selected_columns else pd.Series(dtype=float)
    if not values.empty:
        hist = go.Figure(data=[go.Histogram(x=values, nbinsx=30, marker_color="#2F80A7")])
        hist.update_layout(title="Observed Total System Load Distribution", xaxis_title="Children in active CBP custody + HHS care", yaxis_title="Observed dates", margin={"l": 20, "r": 20, "t": 55, "b": 45})
        st.plotly_chart(hist, use_container_width=True)
    st.caption("Weekly/monthly flow sums are observed reporting-record sums. Coverage and observed-date counts accompany each summarized period.")


def _render_quality(bundle: DatasetBundle, flags: pd.DataFrame, quality: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> None:
    st.subheader("Data Quality and Validation")
    st.dataframe(quality, use_container_width=True, hide_index=True)
    selected = flags.loc[flags["date"].isna() | flags["date"].between(start, end)].copy()
    with st.expander(f"Row-level flags for selected period ({len(selected):,})", expanded=False):
        st.dataframe(selected, use_container_width=True, hide_index=True)
    st.warning(
        "The transfer-versus-custody comparison is flagged for review because transfers are a daily flow and custody is an active stock. "
        "Source values are retained. Missing dates are shown as gaps, not zeroes."
    )


def _render_methodology(daily: pd.DataFrame) -> None:
    gate = forecast_eligibility(daily)
    st.subheader("Methodology and Limits")
    st.markdown(
        """
        - **Total System Load:** CBP custody + HHS care on the same reporting date.
        - **HHS Net Intake Pressure:** transfers to HHS − HHS discharges on an observed record.
        - **Care Load Growth Rate:** day-over-day percent change only when consecutive calendar dates are both observed.
        - **Care Load Volatility Index:** sample standard deviation of consecutive-day total-load percent changes, in percentage points per day.
        - **Backlog Accumulation Rate:** mean of positive HHS net-flow values per observed reporting record; a proxy, not a directly measured backlog or calendar-day rate.
        - **Care Load Volatility Index:** coefficient of variation of valid observed Total System Load (sample SD ÷ mean × 100), not an official HHS standard.
        - **Discharge Offset Ratio:** 100 × sum of observed HHS discharges ÷ sum of observed transfers; undefined if the denominator is zero.
        - **Rolling means:** 7/14 calendar days for loads and flows, shown only with at least 80% date coverage in the window; coverage is shown in the processed daily output.
        - **Sustained pressure proxy:** positive trailing 7-day mean HHS Net Intake Pressure with at least 80% calendar-date coverage.
        - **Relative high load:** a percentile of this dataset, not a capacity threshold.

        No facility capacity, staffing, location, length-of-stay, health outcome, or individual-level data are supplied. This dashboard does not establish overcrowding, delayed care, harm, or policy causation.
        """
    )
    st.subheader("Forecasting eligibility")
    st.write(
        f"Forecasting is {'enabled for evaluation' if gate['eligible'] else 'disabled'}: overall coverage {gate['overall_coverage_pct']:.1f}%, "
        f"trailing-365-day coverage {gate['trailing_365_coverage_pct']:.1f}%, longest gap {gate['max_missing_streak_days']} days. {gate['reason']}"
    )


def main() -> None:
    st.set_page_config(page_title="UAC Care Load Analytics", page_icon="📊", layout="wide")
    st.title("System Capacity & Care Load Analytics")
    st.caption("Aggregate operational monitoring · Observed counts only · No capacity or causal conclusions")

    uploaded = st.sidebar.file_uploader("Use a replacement CSV", type=["csv"], help="The file must use the six source headings listed in Methodology.")
    if uploaded is not None:
        csv_bytes = uploaded.getvalue()
        source_name = uploaded.name
    elif RAW_DATA_PATH.exists():
        csv_bytes = RAW_DATA_PATH.read_bytes()
        source_name = RAW_DATA_PATH.name
    else:
        st.error(f"Default source CSV is missing: {RAW_DATA_PATH}. Upload a replacement CSV to continue.")
        return

    try:
        bundle, flags, quality, observed, daily = _analyze_source(csv_bytes, source_name)
    except (ValueError, FileNotFoundError, pd.errors.ParserError) as exc:
        st.error(f"Could not load this CSV: {exc}")
        return
    if daily.empty:
        st.error("The CSV has no valid reporting dates. Check the Date field and upload a corrected file.")
        _render_quality(bundle, flags, quality, pd.Timestamp.min, pd.Timestamp.max)
        return

    date_min, date_max = pd.Timestamp(daily["date"].min()).date(), pd.Timestamp(daily["date"].max()).date()
    st.sidebar.header("View controls")
    date_selection = st.sidebar.date_input(
        "Reporting date range",
        value=(date_min, date_max),
        min_value=date_min,
        max_value=date_max,
        key="date_range",
    )
    if isinstance(date_selection, (tuple, list)) and len(date_selection) == 2:
        start, end = pd.Timestamp(date_selection[0]), pd.Timestamp(date_selection[1])
    else:
        start = end = pd.Timestamp(date_selection)
    granularity = st.sidebar.selectbox("Time granularity", ["daily", "weekly", "monthly"], index=0)
    selected_labels = st.sidebar.multiselect("Metric series", list(SERIES_OPTIONS), default=DEFAULT_SERIES)
    selected_columns = [SERIES_OPTIONS[label] for label in selected_labels]
    percentile = st.sidebar.slider("Relative high-load percentile", min_value=75, max_value=99, value=90, step=1)

    observed_days, possible_days, coverage = _coverage_text(daily, start, end)
    latest_valid = observed.loc[observed["total_system_load"].notna(), "date"]
    latest_text = latest_valid.max().strftime("%b %d, %Y") if not latest_valid.empty else "Not available"
    st.caption(
        f"Source: {bundle.source_name} · Latest valid load date: {latest_text} · "
        f"Selected period coverage: {observed_days:,}/{possible_days:,} dates ({coverage:.1f}%)"
    )

    tabs = st.tabs(["Overview", "CBP vs HHS", "Intake & Discharge Pressure", "Trends & Variability", "Data Quality", "Methodology"])
    with tabs[0]:
        _render_overview(observed, daily, start, end, granularity, selected_columns, percentile)
    with tabs[1]:
        _render_load_comparison(observed, daily, start, end, granularity, selected_columns)
    with tabs[2]:
        _render_pressure(observed, daily, start, end, granularity, selected_columns)
    with tabs[3]:
        _render_trends(observed, daily, start, end, granularity, selected_columns)
    with tabs[4]:
        _render_quality(bundle, flags, quality, start, end)
    with tabs[5]:
        _render_methodology(daily)

    st.divider()
    st.subheader("Downloads")
    _render_downloads(observed, flags, start, end)
    st.caption("Source values are never overwritten. Outputs can be regenerated with `python -m uac_analytics.cli`.")


if __name__ == "__main__":
    main()
