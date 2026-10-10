# Data Quality Report

**Generated:** 2026-10-10 18:05 IST  
**Source file:** packaged or uploaded CSV  
**Date span:** January 12, 2023 through December 21, 2025

## Summary

| Check | Result | Meaning |
| --- | --- | --- |
| raw_rows | 1,170 | Rows read from the CSV body, including completely blank rows. |
| blank_rows_removed | 450 | Completely blank rows excluded from analytical records. |
| observed_records | 720 | Nonblank source rows retained, including rows with invalid dates. |
| valid_dates | 720 | Retained records with a parsed reporting date. |
| invalid_dates | 0 | Rows with blank or unparseable dates. |
| date_start | 2023-01-12 | Earliest parsed reporting date. |
| date_end | 2025-12-21 | Latest parsed reporting date. |
| possible_calendar_days | 1,075 | Calendar dates from the minimum through maximum parsed date, inclusive. |
| observed_calendar_days | 720 | Distinct dates with at least one valid-date source record. |
| missing_calendar_days | 355 | Dates with no source record; not zero-filled. |
| calendar_coverage_pct | 66.98 | Observed distinct dates divided by possible dates. |
| duplicate_date_rows | 0 | Rows on dates appearing more than once; records are not aggregated. |
| exact_duplicate_rows | 0 | Rows identical across all required source columns; none removed. |
| missing_numeric_values | 0 | Blank values across required count fields. |
| numeric_conversion_failures | 0 | Nonblank count values that could not be parsed. |
| negative_counts | 0 | Count values below zero. |
| fractional_counts | 0 | Count values that are not whole numbers. |
| transfers_exceed_cbp_custody_review_flags | 86 | Flow-versus-stock comparison from the DOCX; flags require review and values are not changed. |
| discharges_exceed_hhs_care_flags | 0 | DOCX discharge comparison flags; values are not changed. |
| day_to_day_change_outliers | 309 | Consecutive-day changes outside 1.5 IQR; inspection flags only. |
| unexpected_columns | None | Extra source columns are retained in raw input and excluded from core calculations. |
| source_arrival_order | Newest-first | Analytical records are sorted chronologically regardless of source order. |

## Flag counts by rule

| Rule | Severity | Flagged rows |
| --- | --- | --- |
| day_to_day_change_outlier | review | 309 |
| missing_calendar_date | data_gap | 355 |
| source_not_chronological | info | 1 |
| transfer_exceeds_cbp_custody_review | review | 86 |

## Interpretation notes

- Completely blank rows are counted and excluded from analytical records; partial rows are retained and flagged.
- Missing calendar dates remain missing. Calendar coverage is 67.0% and the longest missing run is 9 days.
- `transfers_to_hhs <= cbp_custody` is a review comparison, not an automatic rejection, because the compared columns represent a flow and a stock.
- Duplicate dates are retained and are not combined. Their values are left out of date-indexed and period calculations until a source owner resolves the ambiguity.
- Outlier and logical-constraint flags do not alter or remove source values.
- No single data-quality score is calculated; individual dimensions remain visible.
