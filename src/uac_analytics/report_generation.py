"""Generate data-backed Markdown reports from the processed source records."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .analysis import aggregate_periods, forecast_eligibility, identify_sustained_positive_windows
from .config import FORECAST_MIN_COVERAGE
from .metrics import compute_kpis


def _summary_value(summary: pd.DataFrame, check: str, default: object = "Not available") -> object:
    found = summary.loc[summary["check"] == check, "value"]
    return found.iloc[0] if not found.empty else default


def _fmt(value: object, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "Not available"
    if isinstance(value, (float, np.floating)):
        return f"{value:,.{digits}f}"
    if isinstance(value, (int, np.integer)):
        return f"{value:,}"
    return str(value)


def _pct(value: object) -> str:
    return f"{_fmt(value, 1)}%" if value is not None and not pd.isna(value) else "Not available"


def _markdown_table(frame: pd.DataFrame, columns: list[str], headers: list[str]) -> str:
    if frame.empty:
        return "_No rows available for this summary._"
    head = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"
    rows = []
    for _, row in frame[columns].iterrows():
        rows.append("| " + " | ".join(_fmt(value, 1) for value in row.tolist()) + " |")
    return "\n".join([head, separator, *rows])


def _longest_gap(daily_index: pd.DataFrame) -> int:
    if daily_index.empty:
        return 0
    missing = (~daily_index["is_observed"].fillna(False).astype(bool)).astype(int)
    groups = missing.ne(missing.shift(fill_value=0)).cumsum()
    streaks = missing.groupby(groups).sum()
    return int(streaks.max()) if not streaks.empty else 0


def generate_reports(
    metrics: pd.DataFrame,
    daily_index: pd.DataFrame,
    flags: pd.DataFrame,
    quality_summary: pd.DataFrame,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write a research paper, executive brief, and quality report with actual results."""

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M %Z")
    dated = metrics.loc[pd.to_datetime(metrics["date"], errors="coerce").notna()].copy() if not metrics.empty else metrics.copy()
    if not dated.empty:
        dated["date"] = pd.to_datetime(dated["date"])
        dated = dated.sort_values("date")
        if "duplicate_date" in dated:
            dated = dated.loc[~dated["duplicate_date"].fillna(False)].copy()
        elif dated["date"].duplicated(keep=False).any():
            dated = dated.loc[~dated["date"].duplicated(keep=False)].copy()
        start, end = dated["date"].min(), dated["date"].max()
        load_rows = dated.loc[dated["total_system_load"].notna()]
    else:
        start = end = pd.NaT
        load_rows = dated

    kpis = compute_kpis(dated)
    best = load_rows.loc[load_rows["total_system_load"].idxmax()] if not load_rows.empty else None
    lowest = load_rows.loc[load_rows["total_system_load"].idxmin()] if not load_rows.empty else None
    latest = load_rows.iloc[-1] if not load_rows.empty else None
    high_threshold = float(load_rows["total_system_load"].quantile(0.90)) if not load_rows.empty else np.nan
    high_count = int((load_rows["total_system_load"] >= high_threshold).sum()) if not load_rows.empty else 0
    net = dated["hhs_net_intake_pressure"].dropna() if not dated.empty else pd.Series(dtype=float)
    positive_records = int((net > 0).sum())
    zero_negative_records = int((net <= 0).sum())
    windows = identify_sustained_positive_windows(dated, window_days=7, min_coverage=0.8) if not dated.empty else []
    yearly = aggregate_periods(dated, "yearly", start, end) if not dated.empty else pd.DataFrame()
    forecast = forecast_eligibility(daily_index)

    coverage = _summary_value(quality_summary, "calendar_coverage_pct")
    missing_days = _summary_value(quality_summary, "missing_calendar_days")
    observed_records = _summary_value(quality_summary, "observed_records")
    raw_rows = _summary_value(quality_summary, "raw_rows")
    blanks = _summary_value(quality_summary, "blank_rows_removed")
    transfer_flags = _summary_value(quality_summary, "transfers_exceed_cbp_custody_review_flags", 0)
    discharge_flags = _summary_value(quality_summary, "discharges_exceed_hhs_care_flags", 0)
    possible = _summary_value(quality_summary, "possible_calendar_days")
    observed_days = _summary_value(quality_summary, "observed_calendar_days")
    invalid_dates = _summary_value(quality_summary, "invalid_dates", 0)
    duplicate_rows = _summary_value(quality_summary, "duplicate_date_rows", 0)
    if pd.notna(start):
        period_text = f"{start:%B %d, %Y} through {end:%B %d, %Y}"
        start_iso, end_iso = start.date().isoformat(), end.date().isoformat()
    else:
        period_text = "no valid dated observations"
        start_iso = end_iso = "Not available"
    latest_date = latest["date"].date().isoformat() if latest is not None else "Not available"
    latest_load = _fmt(latest["total_system_load"], 0) if latest is not None else "Not available"
    peak_text = (
        f"{_fmt(best['total_system_load'], 0)} children on {best['date']:%B %d, %Y}"
        if best is not None
        else "Not available"
    )
    low_text = (
        f"{_fmt(lowest['total_system_load'], 0)} children on {lowest['date']:%B %d, %Y}"
        if lowest is not None
        else "Not available"
    )
    ratio = kpis["discharge_offset_ratio"]
    ratio_text = f"{_fmt(ratio.value, 1)}%" if ratio.value is not None else "Not available"
    volatility = kpis["care_load_volatility_index"]
    volatility_text = f"{_fmt(volatility.value, 1)}%" if volatility.value is not None else "Not available"
    backlog_rate = kpis["backlog_accumulation_rate"]
    backlog_text = (
        f"{_fmt(backlog_rate.value, 1)} children per positive observed reporting record"
        if backlog_rate.value is not None
        else "Not available"
    )
    kpi_table = pd.DataFrame(
        [
            ["Total Children Under Care", f"{latest_load} on {latest_date}", kpis["total_children_under_care"].reason],
            ["Net Intake Pressure", _fmt(kpis["net_intake_pressure"].value, 0), kpis["net_intake_pressure"].reason],
            ["Care Load Volatility Index", volatility_text, volatility.reason],
            ["Backlog Accumulation Rate", backlog_text, backlog_rate.reason],
            ["Discharge Offset Ratio", ratio_text, ratio.reason],
        ],
        columns=["kpi", "result", "definition_and_basis"],
    )
    kpi_md = _markdown_table(
        kpi_table,
        ["kpi", "result", "definition_and_basis"],
        ["KPI", "Computed result", "Definition and time basis"],
    )

    descriptive_columns = [
        "cbp_daily_intake", "cbp_custody", "transfers_to_hhs", "hhs_care", "hhs_discharges",
        "total_system_load", "hhs_net_intake_pressure",
    ]
    descriptive_rows = []
    for metric in descriptive_columns:
        values = dated[metric].dropna() if metric in dated else pd.Series(dtype=float)
        descriptive_rows.append(
            {
                "metric": metric,
                "n": len(values),
                "mean": values.mean() if len(values) else np.nan,
                "median": values.median() if len(values) else np.nan,
                "std": values.std(ddof=1) if len(values) >= 2 else np.nan,
                "min": values.min() if len(values) else np.nan,
                "p25": values.quantile(0.25) if len(values) else np.nan,
                "p75": values.quantile(0.75) if len(values) else np.nan,
                "p95": values.quantile(0.95) if len(values) else np.nan,
                "max": values.max() if len(values) else np.nan,
            }
        )
    descriptive = pd.DataFrame(descriptive_rows)
    descriptive_md = _markdown_table(
        descriptive,
        ["metric", "n", "mean", "median", "std", "min", "p25", "p75", "p95", "max"],
        ["Measure", "N", "Mean", "Median", "SD", "Min", "P25", "P75", "P95", "Max"],
    )
    monthly = aggregate_periods(dated, "monthly", start, end) if not dated.empty else pd.DataFrame()
    monthly_md = _markdown_table(
        monthly,
        ["period_start", "observed_records", "possible_calendar_days", "coverage_pct", "total_system_load_mean", "net_pressure_observed_sum"],
        ["Month", "Observed dates", "Possible dates", "Coverage (%)", "Mean load", "Net pressure sum*"],
    ) if not monthly.empty else "_No monthly summary is available._"
    if not dated.empty:
        complete_loads = dated.loc[dated["total_system_load"].notna() & dated["total_system_load"].ne(0)]
        cbp_share = (complete_loads["cbp_custody"] / complete_loads["total_system_load"] * 100).mean() if not complete_loads.empty else np.nan
        hhs_share = (complete_loads["hhs_care"] / complete_loads["total_system_load"] * 100).mean() if not complete_loads.empty else np.nan
    else:
        cbp_share = hhs_share = np.nan

    year_table = yearly.rename(
        columns={
            "period_start": "year",
            "observed_records": "records",
            "coverage_pct": "coverage_pct",
            "total_system_load_mean": "mean_load",
            "total_system_load_max": "max_load",
            "net_pressure_observed_sum": "net_pressure",
        }
    )
    year_md = _markdown_table(
        year_table,
        ["year", "records", "possible_calendar_days", "coverage_pct", "mean_load", "max_load", "net_pressure"],
        ["Year", "Observed dates", "Possible dates", "Coverage (%)", "Mean load", "Max load", "Net pressure sum*"],
    ) if not year_table.empty else "_No year summary is available._"

    windows_md = (
        "\n".join(
            f"- {window['start']:%Y-%m-%d} to {window['end']:%Y-%m-%d}: positive 7-day observed-record mean HHS net flow; "
            f"{window['qualifying_windows']} consecutive qualifying window endpoints and minimum coverage {window['minimum_coverage_pct']:.1f}%."
            for window in windows[:10]
        )
        if windows
        else "- No 7-day window with positive mean HHS net flow and at least 80% calendar-date coverage was identified."
    )
    figure_links = "\n".join(
        [
            "![Total System Load](figures/total_system_load.png)",
            "![CBP and HHS Active Loads](figures/cbp_vs_hhs_load.png)",
            "![Transfers and HHS Discharges](figures/transfers_and_discharges.png)",
            "![HHS Net Intake Pressure](figures/hhs_net_intake_pressure.png)",
            "![Monthly Reporting-Date Coverage](figures/monthly_reporting_coverage.png)",
            "![Distribution of Total System Load](figures/total_load_distribution.png)",
        ]
    )

    research = f"""# System Capacity & Care Load Analytics for Unaccompanied Children

**Generated:** {generated}  
**Reporting dates:** {period_text}  
**Source:** supplied `HHS_Unaccompanied_Alien_Children_Program.csv`; specification context from `Project 3.docx`.

## Abstract

This analysis describes aggregate CBP and HHS active-load counts, daily intake and transfer/discharge flows, relative load variation, and source-data coverage. It retains source values and missing reporting dates, and computes daily growth only across consecutive calendar dates. The file contains {observed_records} nonblank source records across {possible} possible calendar dates ({_pct(coverage)} coverage), with {missing_days} unreported dates. Therefore, flow totals are observed-record sums and relative peaks cannot establish facility capacity, overcrowding, delay, harm, or causal policy effects.

## Background and objectives

The supplied project specification frames the program as an operational care pipeline and calls for monitoring active load, intake/outflow balance, temporal pressure, and data quality. This analysis supports that monitoring purpose using only the provided aggregate counts. It asks: (1) how observed CBP and HHS active loads changed; (2) how recorded transfers compare with HHS discharges; (3) when observed load was relatively high or net flow positive; and (4) how incomplete reporting affects those readings.

The specification also describes potential staffing and shelter planning uses. The available fields do not include facility capacity, staffing, length of stay, location, health outcomes, or individual records, so this work does not evaluate adequacy or service performance.

## Dataset and source fields

The CSV contains {raw_rows} raw data rows, including {blanks} completely blank rows. After excluding only those blank rows, {observed_records} records remain. Parsed reporting dates span {period_text}. The file is newest-first; the analysis sorts valid dates chronologically. Source row references retain CSV body line numbers.

| Source field | Internal name | Interpretation used |
| --- | --- | --- |
| `Date` | `date` | Reporting date |
| `Children apprehended and placed in CBP custody*` | `cbp_daily_intake` | Daily intake flow; the asterisk has no supplied footnote |
| `Children in CBP custody` | `cbp_custody` | Active CBP stock |
| `Children transferred out of CBP custody` | `transfers_to_hhs` | Daily transfer flow into HHS, following the DOCX wording |
| `Children in HHS Care` | `hhs_care` | Active HHS stock |
| `Children discharged from HHS Care` | `hhs_discharges` | Daily HHS discharge flow |

## Cleaning and reproducibility

The loader reads all source cells as text, counts fully blank rows, preserves the raw frame in memory, maps headings to stable internal names, parses dates, and removes commas before safe numeric conversion. It retains rows with invalid dates or count values and emits source-row flags. It sorts dated records and builds a complete calendar index from the minimum through maximum valid date. Inserted calendar rows remain `NaN` and are marked `is_observed = false`; no zero-fill, interpolation, or forward-fill is used. Duplicate dates are flagged and retained; duplicate-date values are not summed or averaged in the calendar index or period summaries.

Run `python -m uac_analytics.cli` from the project root to reproduce the processed CSVs, figures, and reports from the packaged raw file. Use `--input PATH` for an alternate CSV with the same required source headings.

## Data-quality assessment

- Calendar coverage is {_pct(coverage)}: {observed_days} observed dates of {possible} possible; {missing_days} dates have no source row. The longest missing-date streak is {_longest_gap(daily_index)} calendar days.
- Invalid dates: {invalid_dates}; duplicate-date rows: {duplicate_rows}; exact duplicate source rows: {_fmt(_summary_value(quality_summary, 'exact_duplicate_rows', 0), 0)}.
- Missing count cells: {_fmt(_summary_value(quality_summary, 'missing_numeric_values', 0), 0)}; nonblank numeric conversion failures: {_fmt(_summary_value(quality_summary, 'numeric_conversion_failures', 0), 0)}; negative counts: {_fmt(_summary_value(quality_summary, 'negative_counts', 0), 0)}; fractional counts: {_fmt(_summary_value(quality_summary, 'fractional_counts', 0), 0)}.
- The requested `transfers_to_hhs <= cbp_custody` comparison is exceeded on {transfer_flags} rows. Transfers are a flow and CBP custody a stock, so the test is retained as a review flag rather than treated as a semantically definitive error.
- The requested `hhs_discharges <= hhs_care` comparison is exceeded on {discharge_flags} rows.
- Consecutive-day changes outside the observed 1.5-IQR range are flagged for inspection and are never removed automatically.

The incomplete date series limits calendar-based rollups, especially weekly/monthly flow totals. Period flow sums below include observed reporting records only; they are not complete-period totals where coverage is below 100%.

## Metric definitions

| Metric | Formula and interpretation |
| --- | --- |
| Total System Load | `cbp_custody + hhs_care`, a sum of the two active stocks on the same observed date. |
| HHS Net Intake Pressure | `transfers_to_hhs - hhs_discharges`, a daily flow balance on an observed record. Positive values indicate recorded transfers exceeded recorded discharges for that record. |
| Care Load Growth Rate | `(total_system_load_t / total_system_load_(t-1)) - 1`; calculated only when both loads exist on consecutive calendar dates and the prior load is nonzero. |
| Cumulative observed-record pressure | Running sum of HHS Net Intake Pressure across observed records. It is a derived flow sum, not a measured backlog. |
| Cumulative observed stock sum | Running sum of observed Total System Load snapshots, in child-observations; not unique children or a complete person-day total. |
| Care Load Volatility Index | Sample standard deviation of valid observed Total System Load divided by its mean, multiplied by 100 (coefficient of variation). This descriptive statistic is not an official HHS standard. |
| Backlog Accumulation Rate | Mean of positive HHS Net Intake Pressure values per observed reporting record. This is a pressure proxy, not a direct backlog count or calendar-day rate. |
| Discharge Offset Ratio | 100 × sum of observed HHS discharges ÷ sum of observed transfers to HHS. Undefined when the transfer denominator is zero; not a placement success rate. |
| Rolling means | Calendar rolling 7-day/14-day averages for Total System Load, active stocks, intake, transfers, discharges, and HHS Net Intake Pressure; displayed only when at least 80% of dates in each window are observed. Coverage is provided alongside each rolling value. |
| Sustained positive-pressure window | Positive trailing 7-day mean HHS Net Intake Pressure with at least 80% calendar-date coverage; a pressure proxy, not a direct backlog. |
| Relative high-load threshold | The selected historical percentile of observed Total System Load. It is relative to this dataset and is not authorized capacity. |

## Methods

Daily plots use the complete calendar index and break lines at missing dates. Weekly and monthly stock summaries use means of observed reporting dates; flow sums are explicitly observed-record sums. Coverage is observed distinct dates divided by possible calendar dates in the selected period. Sustained positive-pressure windows require a positive trailing 7-day mean and at least 80% coverage of the seven calendar dates. Year summaries report observation counts and coverage. No forecasting model is fit: the conservative eligibility gate requires at least {FORECAST_MIN_COVERAGE:.0%} coverage both overall and for the trailing 365 days, plus no reporting gap longer than {7} days.

## Results

### KPI summary

{kpi_md}

### Active loads and relative highs/lows

The latest date with both active-load components is **{latest_date}**, with a computed Total System Load of **{latest_load} children**. The largest observed total was **{peak_text}**; the smallest was **{low_text}**. These are extrema among observed values only. The 90th percentile of observed Total System Load is **{_fmt(high_threshold, 0)} children**; **{high_count}** observations are at or above it. This is a historical relative threshold, not an overcapacity finding. Across dates with both stocks, mean observed load composition was **{_pct(cbp_share)} CBP** and **{_pct(hhs_share)} HHS**.

The sum of observed Total System Load snapshots is **{_fmt(dated['cumulative_observed_total_stock'].dropna().iloc[-1] if not dated.empty and 'cumulative_observed_total_stock' in dated and dated['cumulative_observed_total_stock'].notna().any() else np.nan, 0)} child-observations** across reported dates. This sums repeated active-stock snapshots; it is not a count of unique children or a complete person-day total.

![Total System Load over time](figures/total_system_load.png)

![CBP and HHS active loads](figures/cbp_vs_hhs_load.png)

### Transfers, discharges, and pressure

Across observed records, net HHS flow pressure sums to **{_fmt(net.sum(), 0) if not net.empty else 'Not available'} children**; **{positive_records}** observed records had positive pressure and **{zero_negative_records}** had zero or negative pressure. The aggregate discharge offset ratio is **{ratio_text}**. The running observed-record flow sum is not a directly measured backlog and does not account for unreported dates.

{windows_md}

The table below reports descriptive statistics for observed count/flow fields and the derived stock/pressure measures. These summarize reporting records, not children uniquely served.

{descriptive_md}

![Transfers and discharges](figures/transfers_and_discharges.png)

![HHS net intake pressure](figures/hhs_net_intake_pressure.png)

### Annual comparison

The date boundaries are calendar years intersected with the observed source span. Coverage and observed-date counts are included because differences in reporting completeness affect comparisons. `Net pressure sum*` is a sum of observed reporting records, not a complete annual total.

{year_md}

Monthly row counts, coverage, mean load, and observed-record flow sums are provided below. Partial first/last months are clipped to the source reporting-date span.

{monthly_md}

### Coverage and load distribution

![Monthly reporting-date coverage](figures/monthly_reporting_coverage.png)

![Observed total-load distribution](figures/total_load_distribution.png)

## Operational interpretation and options for review

The observed counts can support situational awareness about the size and direction of recorded load and flow. Operational reviewers could compare the high-load dates with authorized facility-level capacity, staffing, and placement data if those sources are available; review whether the transfer and custody measures use compatible reporting windows; and prioritize restoration of a complete daily reporting series. The data do not establish which operational response caused a change or whether a particular count exceeded capacity.

## Limitations and responsible use

1. **Missing dates:** {missing_days} of {possible} calendar dates lack a record. Period flow sums may omit unreported activity, and missing dates are never interpreted as zero.
2. **Flow-versus-stock comparison:** daily transfers and active CBP custody are different measure types; the flagged comparison may depend on source reporting conventions.
3. **No capacity denominator:** no authorized bed or facility capacity is supplied. No capacity percentage or overcapacity claim is possible.
4. **Unexplained asterisk:** the intake heading includes `*`, but the supplied material gives no corresponding footnote; its meaning is not inferred.
5. **Aggregate scope:** no facility, location, staffing, length-of-stay, health outcome, or individual-level fields are provided.
6. **No causal design or forecast:** the analysis is descriptive. Incomplete reporting fails the configured daily-forecast coverage gate ({forecast['overall_coverage_pct']:.1f}% overall and {forecast['trailing_365_coverage_pct']:.1f}% in the trailing 365 days; longest gap {forecast['max_missing_streak_days']} days), so a forecast is disabled.

## Recommendations for reporting and monitoring

- Improve daily date completeness and publish the expected reporting calendar so coverage can be distinguished from zero activity.
- Document the reporting windows and definitions for intake, transfers, custody snapshots, and discharges, including the unexplained intake asterisk.
- Add authorized capacity and facility-level staffing context in a separate, governed source before evaluating capacity utilization or staffing adequacy.
- Review flagged anomalies with source owners; preserve original values and record any approved corrections through a documented revision process.
- Continue describing relative peaks as observed historical comparisons and pair them with coverage before operational interpretation.

## Conclusion

The supplied CSV supports transparent aggregate monitoring of active load and recorded flows, but not a finding about capacity stress, care delay, harm, or policy effectiveness. Daily coverage and measurement definitions are the main constraints on stronger operational inference.

## References

- `Project 3.docx`, supplied project specification and source-field dictionary.
- `HHS_Unaccompanied_Alien_Children_Program.csv`, supplied aggregate operational data.
"""

    executive = f"""# Executive Summary: System Capacity & Care Load Analytics

**Generated:** {generated}  
**Data period:** {period_text}  
**Latest valid observed load date:** {latest_date}

> **Coverage caveat:** Only {observed_days} of {possible} calendar dates have a source record ({_pct(coverage)}); {missing_days} dates are missing. Flow sums below describe observed reporting records, not complete daily or period totals.

## What the analysis shows

This review uses aggregate daily counts for CBP custody, HHS care, intake, transfers, and discharges. On the latest date with both active-load counts, **{latest_load} children** were in the two reported active stocks combined. Total System Load was highest at **{peak_text}** and lowest at **{low_text}** among observed reporting dates. The 90th percentile threshold was **{_fmt(high_threshold, 0)} children**, a relative comparison within this historical file rather than a capacity limit.

- Recorded HHS transfers minus discharges summed to **{_fmt(net.sum(), 0) if not net.empty else 'Not available'} children across observed records**; {positive_records} records were positive and {zero_negative_records} were zero or negative.
- The Care Load Volatility Index was **{volatility_text}**, the coefficient of variation of observed Total System Load. The Backlog Accumulation Rate proxy was **{backlog_text}**; it averages positive observed net-flow records and is not a direct backlog measure.
- The aggregate discharge offset ratio was **{ratio_text}** (observed discharges divided by observed transfers). It is not a placement success rate.
- The requested transfer-versus-CBP comparison was flagged on **{transfer_flags} records**. Because transfers are daily flows and custody is an active stock, source reporting definitions should be checked before interpreting these flags as errors.
- No daily forecast is shown: coverage is {forecast['overall_coverage_pct']:.1f}% overall and {forecast['trailing_365_coverage_pct']:.1f}% in the trailing year, below the configured {FORECAST_MIN_COVERAGE:.0%} threshold; the longest gap is {forecast['max_missing_streak_days']} days.

## What these measures can and cannot establish

The counts describe reported aggregate load and movement on dates with records. They do not provide authorized capacity, facility-level conditions, staffing, length of stay, health outcomes, or individual histories. A historical high is not evidence of overcrowding, delayed care, harm, or program performance. Missing dates can also understate observed-record flow totals.

## Suggested next steps

1. Improve daily reporting completeness and make expected reporting dates explicit.
2. Confirm definitions and reporting windows for daily transfers versus custody snapshots, discharge counts, and the intake-field asterisk.
3. If capacity review is needed, compare these aggregate trends with authorized facility capacity and staffing data at a compatible time and geographic level.
4. Review flagged records with source owners while retaining original values and documenting any authorized correction.

The dashboard and processed CSVs provide date-level flags, coverage, and reproducible formulas for continued review.
"""

    flag_counts = (
        flags.groupby(["rule", "severity"], dropna=False).size().reset_index(name="rows")
        if not flags.empty
        else pd.DataFrame(columns=["rule", "severity", "rows"])
    )
    flag_table = _markdown_table(flag_counts, ["rule", "severity", "rows"], ["Rule", "Severity", "Flagged rows"])
    quality_report = f"""# Data Quality Report

**Generated:** {generated}  
**Source file:** packaged or uploaded CSV  
**Date span:** {period_text}

## Summary

| Check | Result | Meaning |
| --- | --- | --- |
""" + "\n".join(
        f"| {row.check} | {_fmt(row.value, 2)} | {row.explanation} |"
        for row in quality_summary.itertuples(index=False)
    ) + f"""

## Flag counts by rule

{flag_table}

## Interpretation notes

- Completely blank rows are counted and excluded from analytical records; partial rows are retained and flagged.
- Missing calendar dates remain missing. Calendar coverage is {_pct(coverage)} and the longest missing run is {_longest_gap(daily_index)} days.
- `transfers_to_hhs <= cbp_custody` is a review comparison, not an automatic rejection, because the compared columns represent a flow and a stock.
- Duplicate dates are retained and are not combined. Their values are left out of date-indexed and period calculations until a source owner resolves the ambiguity.
- Outlier and logical-constraint flags do not alter or remove source values.
- No single data-quality score is calculated; individual dimensions remain visible.
"""

    paths = {
        "research_paper": target / "research_paper.md",
        "executive_summary": target / "executive_summary.md",
        "data_quality_report": target / "data_quality_report.md",
    }
    paths["research_paper"].write_text(research, encoding="utf-8")
    paths["executive_summary"].write_text(executive, encoding="utf-8")
    paths["data_quality_report"].write_text(quality_report, encoding="utf-8")
    return paths
