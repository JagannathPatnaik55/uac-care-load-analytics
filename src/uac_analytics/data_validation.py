"""Transparent row-level and dataset-level diagnostics."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .config import COUNT_COLUMNS, FLOW_COLUMNS, STOCK_COLUMNS
from .data_loader import DatasetBundle

FLAG_COLUMNS = ["source_row", "date", "metric", "rule", "severity", "value", "explanation"]


def _flag(
    rows: list[dict[str, Any]],
    *,
    source_row: Any = pd.NA,
    date: Any = pd.NaT,
    metric: str = "",
    rule: str,
    severity: str,
    value: Any = "",
    explanation: str,
) -> None:
    rows.append(
        {
            "source_row": source_row,
            "date": date,
            "metric": metric,
            "rule": rule,
            "severity": severity,
            "value": value,
            "explanation": explanation,
        }
    )


def _add_change_outliers(records: pd.DataFrame, flags: list[dict[str, Any]]) -> None:
    eligible = records.loc[
        records["date"].notna() & ~records["duplicate_date"]
    ].sort_values("date")
    for metric in (*STOCK_COLUMNS, *FLOW_COLUMNS):
        valid = eligible.loc[eligible[metric].notna(), ["date", "source_row", metric]].copy()
        valid["previous_date"] = valid["date"].shift(1)
        valid["change"] = valid[metric].diff()
        consecutive = valid["date"].sub(valid["previous_date"]).dt.days.eq(1)
        changes = valid.loc[consecutive, "change"].dropna()
        if len(changes) < 20:
            continue
        q1, q3 = changes.quantile([0.25, 0.75])
        spread = q3 - q1
        if spread == 0:
            continue
        lower, upper = q1 - 1.5 * spread, q3 + 1.5 * spread
        outliers = valid.loc[consecutive & valid["change"].notna()]
        outliers = outliers.loc[(outliers["change"] < lower) | (outliers["change"] > upper)]
        for row in outliers.itertuples(index=False):
            _flag(
                flags,
                source_row=int(row.source_row),
                date=row.date,
                metric=metric,
                rule="day_to_day_change_outlier",
                severity="review",
                value=float(row.change),
                explanation=(
                    "Consecutive-calendar-day change is outside the observed 1.5-IQR range. "
                    "This is an inspection flag; the value is retained."
                ),
            )


def validate_dataset(bundle: DatasetBundle) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return detailed flags and a human-readable aggregate quality summary."""

    flags: list[dict[str, Any]] = []
    records = bundle.records

    if bundle.unexpected_columns:
        _flag(
            flags,
            rule="unexpected_columns",
            severity="info",
            value=", ".join(bundle.unexpected_columns),
            explanation="Extra source columns were preserved in the raw input but are not used in core metrics.",
        )
    if bundle.source_not_ascending:
        _flag(
            flags,
            rule="source_not_chronological",
            severity="info",
            explanation="Source rows were not in oldest-to-newest order; analytical records were sorted by date.",
        )

    for row in records.itertuples(index=False):
        source_row = int(row.source_row)
        date = row.date
        if pd.isna(date):
            raw_date = str(row.date_raw).strip()
            _flag(
                flags,
                source_row=source_row,
                metric="date",
                rule="invalid_date",
                severity="error" if raw_date else "warning",
                value=raw_date,
                explanation="Date is blank or could not be parsed; the source row is retained outside date-indexed metrics.",
            )
        if bool(row.exact_duplicate):
            _flag(
                flags,
                source_row=source_row,
                date=date,
                rule="exact_duplicate_row",
                severity="review",
                explanation="This source row exactly duplicates another nonblank source row; neither copy was removed.",
            )
        if bool(row.duplicate_date):
            _flag(
                flags,
                source_row=source_row,
                date=date,
                rule="duplicate_date",
                severity="review",
                explanation="Multiple source records share this date; they are retained and are not summed or averaged.",
            )

        for metric in COUNT_COLUMNS:
            raw_value = str(getattr(row, f"raw_{metric}")).strip()
            value = getattr(row, metric)
            if raw_value == "":
                _flag(
                    flags,
                    source_row=source_row,
                    date=date,
                    metric=metric,
                    rule="missing_numeric_value",
                    severity="warning",
                    explanation="Required count is blank; it remains missing and is not converted to zero.",
                )
                continue
            if pd.isna(value):
                _flag(
                    flags,
                    source_row=source_row,
                    date=date,
                    metric=metric,
                    rule="numeric_conversion_failure",
                    severity="error",
                    value=raw_value,
                    explanation="Count could not be converted to a number; the original value is preserved in the raw data.",
                )
                continue
            if float(value) < 0:
                _flag(
                    flags,
                    source_row=source_row,
                    date=date,
                    metric=metric,
                    rule="negative_count",
                    severity="review",
                    value=float(value),
                    explanation="Count fields are expected to be non-negative; the source value is retained.",
                )
            if not float(value).is_integer():
                _flag(
                    flags,
                    source_row=source_row,
                    date=date,
                    metric=metric,
                    rule="fractional_count",
                    severity="review",
                    value=float(value),
                    explanation="Count fields are expected to be whole numbers; the source value is retained without rounding.",
                )

        if pd.notna(row.transfers_to_hhs) and pd.notna(row.cbp_custody) and row.transfers_to_hhs > row.cbp_custody:
            _flag(
                flags,
                source_row=source_row,
                date=date,
                metric="transfers_to_hhs",
                rule="transfer_exceeds_cbp_custody_review",
                severity="review",
                value=float(row.transfers_to_hhs),
                explanation=(
                    "The DOCX comparison transfers_to_hhs <= cbp_custody is exceeded. Transfers are a daily flow "
                    "and custody is an active stock, so reporting conventions may make this comparison non-equivalent."
                ),
            )
        if pd.notna(row.hhs_discharges) and pd.notna(row.hhs_care) and row.hhs_discharges > row.hhs_care:
            _flag(
                flags,
                source_row=source_row,
                date=date,
                metric="hhs_discharges",
                rule="discharges_exceed_hhs_care",
                severity="review",
                value=float(row.hhs_discharges),
                explanation="The DOCX comparison hhs_discharges <= hhs_care is exceeded; values are retained for review.",
            )

    if not bundle.daily_index.empty:
        missing_days = bundle.daily_index.loc[~bundle.daily_index["is_observed"]]
        for date in missing_days["date"]:
            _flag(
                flags,
                date=date,
                rule="missing_calendar_date",
                severity="data_gap",
                explanation="No source record exists for this calendar date; it remains missing rather than zero-filled.",
            )

    _add_change_outliers(records, flags)
    flag_frame = pd.DataFrame(flags, columns=FLAG_COLUMNS)
    if not flag_frame.empty:
        flag_frame["date"] = pd.to_datetime(flag_frame["date"], errors="coerce")
        flag_frame = flag_frame.sort_values(
            ["date", "source_row", "rule"], na_position="last", kind="stable"
        ).reset_index(drop=True)

    valid_dates = records.loc[records["date"].notna(), "date"]
    possible_days = len(bundle.daily_index)
    observed_days = int(bundle.daily_index["is_observed"].sum()) if possible_days else 0
    duplicate_dates = int(records.loc[records["date"].notna(), "date"].duplicated(keep=False).sum())
    count_values = records[list(COUNT_COLUMNS)]
    raw_count_values = records[[f"raw_{metric}" for metric in COUNT_COLUMNS]]
    missing_numeric = int(sum(raw_count_values[column].astype("string").str.strip().eq("").sum() for column in raw_count_values))
    conversion_failures = int(
        sum(
            (raw_count_values[f"raw_{metric}"].astype("string").str.strip().ne("") & count_values[metric].isna()).sum()
            for metric in COUNT_COLUMNS
        )
    )
    negative_count = int((count_values < 0).sum().sum())
    fractional_count = int(((count_values.notna()) & (count_values.mod(1).ne(0))).sum().sum())
    summary_items: list[tuple[str, Any, str]] = [
        ("raw_rows", bundle.raw_row_count, "Rows read from the CSV body, including completely blank rows."),
        ("blank_rows_removed", bundle.blank_rows_removed, "Completely blank rows excluded from analytical records."),
        ("observed_records", len(records), "Nonblank source rows retained, including rows with invalid dates."),
        ("valid_dates", int(valid_dates.notna().sum()), "Retained records with a parsed reporting date."),
        ("invalid_dates", int(records["date"].isna().sum()), "Rows with blank or unparseable dates."),
        ("date_start", valid_dates.min().date().isoformat() if not valid_dates.empty else "Not available", "Earliest parsed reporting date."),
        ("date_end", valid_dates.max().date().isoformat() if not valid_dates.empty else "Not available", "Latest parsed reporting date."),
        ("possible_calendar_days", possible_days, "Calendar dates from the minimum through maximum parsed date, inclusive."),
        ("observed_calendar_days", observed_days, "Distinct dates with at least one valid-date source record."),
        ("missing_calendar_days", max(possible_days - observed_days, 0), "Dates with no source record; not zero-filled."),
        ("calendar_coverage_pct", round(observed_days / possible_days * 100, 2) if possible_days else "Not available", "Observed distinct dates divided by possible dates."),
        ("duplicate_date_rows", duplicate_dates, "Rows on dates appearing more than once; records are not aggregated."),
        ("exact_duplicate_rows", int(records["exact_duplicate"].sum()), "Rows identical across all required source columns; none removed."),
        ("missing_numeric_values", missing_numeric, "Blank values across required count fields."),
        ("numeric_conversion_failures", conversion_failures, "Nonblank count values that could not be parsed."),
        ("negative_counts", negative_count, "Count values below zero."),
        ("fractional_counts", fractional_count, "Count values that are not whole numbers."),
        ("transfers_exceed_cbp_custody_review_flags", int((flag_frame["rule"] == "transfer_exceeds_cbp_custody_review").sum()) if not flag_frame.empty else 0, "Flow-versus-stock comparison from the DOCX; flags require review and values are not changed."),
        ("discharges_exceed_hhs_care_flags", int((flag_frame["rule"] == "discharges_exceed_hhs_care").sum()) if not flag_frame.empty else 0, "DOCX discharge comparison flags; values are not changed."),
        ("day_to_day_change_outliers", int((flag_frame["rule"] == "day_to_day_change_outlier").sum()) if not flag_frame.empty else 0, "Consecutive-day changes outside 1.5 IQR; inspection flags only."),
        ("unexpected_columns", ", ".join(bundle.unexpected_columns) if bundle.unexpected_columns else "None", "Extra source columns are retained in raw input and excluded from core calculations."),
        ("source_arrival_order", bundle.source_order, "Analytical records are sorted chronologically regardless of source order."),
    ]
    summary = pd.DataFrame(summary_items, columns=["check", "value", "explanation"])
    return flag_frame, summary


def data_quality_by_date(bundle: DatasetBundle, flags: pd.DataFrame) -> pd.DataFrame:
    """Attach date-level flag counts and rule names to the complete calendar index."""

    daily = bundle.daily_index.copy()
    if daily.empty:
        return daily
    date_flags = flags.loc[flags["date"].notna()].groupby("date").agg(
        quality_flag_count=("rule", "size"),
        quality_rules=("rule", lambda values: "; ".join(sorted(set(values)))),
    )
    daily = daily.merge(date_flags, how="left", left_on="date", right_index=True)
    daily["quality_flag_count"] = daily["quality_flag_count"].fillna(0).astype(int)
    daily["quality_rules"] = daily["quality_rules"].fillna("")
    return daily
