# System Capacity & Care Load Analytics for Unaccompanied Children

This Python project turns the supplied aggregate CSV into a coverage-aware analysis, a Streamlit dashboard, reproducible data-quality outputs, and three generated reports. It is intended as a monitoring aid for operational review. It does not estimate facility capacity or make causal, individual-level, or care-outcome claims.

## Project structure

```text
uac-care-load-analytics/
├── app.py
├── pyproject.toml
├── requirements.txt
├── data/
│   ├── raw/HHS_Unaccompanied_Alien_Children_Program.csv
│   └── processed/                  # regenerated CSV outputs
├── reports/
│   ├── research_paper.md
│   ├── executive_summary.md
│   ├── data_quality_report.md
│   └── figures/                    # generated PNG figures
├── src/uac_analytics/              # loaders, validation, metrics, analysis, reports
├── tests/
└── outputs/                        # optional user exports
```

The packaged raw CSV is an unchanged copy of the supplied source. The DOCX was read for its field dictionary, objectives, metric names, and comparison rules; its unsupported statements about risks are not treated as findings from this dataset.

## Setup

Requires Python 3.11 or newer. Python 3.12 was used for project verification.

### Windows PowerShell

```powershell
cd D:\Jagannath\Projects\uac-care-load-analytics
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### macOS/Linux

```bash
cd uac-care-load-analytics
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Dependencies are pinned in `pyproject.toml` and include pandas, NumPy, Streamlit, Plotly, Matplotlib, and pytest.

## Run the dashboard

From the project root with the environment active:

```bash
streamlit run app.py
```

The dashboard defaults to the packaged CSV. Use **Use a replacement CSV** to upload another file with the six required source headings. The upload is analyzed in memory; caching is keyed by file bytes so a new upload receives fresh calculations.

The sidebar provides a date range, daily/weekly/monthly granularity, metric-series selection, and a relative high-load percentile. Tabs cover system overview, CBP and HHS active stocks, daily flows/net pressure, temporal summaries, data quality, and methodology. CSV downloads reflect the selected dates.

## Regenerate processed data, figures, and reports

Run from the project root:

```powershell
python -m uac_analytics.cli
```

Use a replacement CSV from the command line with:

```powershell
python -m uac_analytics.cli --input "C:\path\to\replacement.csv"
```

Optional `--processed-dir` and `--reports-dir` arguments change output locations. Missing processed/report folders are created automatically. The command writes:

- `data/processed/cleaned_observed_records.csv`
- `data/processed/full_daily_index.csv`
- `data/processed/derived_metrics.csv`
- `data/processed/data_quality_flags.csv`
- `data/processed/data_quality_report.csv`
- `data/processed/data_quality_by_date.csv`
- `data/processed/period_summaries.csv` (monthly/yearly row counts, coverage, loads, and observed flow sums)
- `reports/research_paper.md`
- `reports/executive_summary.md`
- `reports/data_quality_report.md`
- six PNG figures under `reports/figures/`

The CSV outputs are deterministic for a fixed input. Markdown reports include a generation timestamp.

## Metric definitions

All formulas use normalized source fields. `CBP custody` and `HHS care` are active stocks; intake, transfers, and discharges are flows.

| KPI / metric | Definition |
| --- | --- |
| Total Children Under Care / Total System Load | Latest date with both active stocks: `cbp_custody + hhs_care`. |
| Net Intake Pressure | Sum of `transfers_to_hhs - hhs_discharges` over observed records in the selected dates. It is not a measured backlog. |
| Care Load Volatility Index | Sample standard deviation of observed Total System Load divided by its mean × 100 (coefficient of variation); descriptive, not an official HHS standard. |
| Backlog Accumulation Rate | Mean of positive HHS net-flow values per observed reporting record. This is a pressure proxy, not a direct backlog or a calendar-day rate. |
| Discharge Offset Ratio | 100 × sum of observed `hhs_discharges` ÷ sum of observed `transfers_to_hhs`. It is undefined when observed transfers sum to zero and is not a placement success rate. |
| Care Load Growth Rate | `(total_system_load_t / total_system_load_(t-1)) - 1`, calculated only when both dates are consecutive and the previous load is nonzero. |
| Cumulative observed-record pressure | Running sum of HHS net pressure across observed records; not an independently measured backlog. |
| Cumulative observed stock sum | Running sum of observed Total System Load snapshots in child-observations; not unique children or a complete person-day total. |
| Rolling means | Calendar 7-day and 14-day means for loads and flows, shown only when at least 80% of dates in the rolling window have observations; coverage is included in processed outputs. |

Weekly and monthly stock summaries are means over observed reporting dates. Flow summaries are sums of observed reporting records and are labeled as such; incomplete periods are not presented as complete totals.

## Data handling and limitations

- Fully blank rows are counted and excluded from analytical records. Partial rows remain and receive flags.
- Comma-formatted count strings are parsed after removing thousands separators. Non-numeric values remain missing; they are not converted to zero.
- Records are sorted chronologically. Invalid dates are retained in cleaned observed records and quality flags but cannot be placed on the calendar index.
- A complete date index is created between the minimum and maximum valid reporting dates. Dates without source records remain `NaN` and have `is_observed = false`.
- Duplicate dates and exact duplicate rows are flagged. Duplicate-date rows are retained; ambiguous values are not summed or averaged into the daily index or period summaries.
- Negative, fractional, non-numeric, logically flagged, and unusual consecutive-day changes are reported for review. No values are auto-corrected or removed.
- The requested `transfers_to_hhs <= cbp_custody` check is only a review flag: transfers are a daily flow, while custody is an active stock. The source's exact reporting convention is not supplied.
- The asterisk in the CBP intake heading has no explained footnote in the supplied material.
- No authorized facility capacity is present, so the dashboard does not show capacity utilization or infer overcapacity.
- The file contains only aggregate counts. It has no facility, location, staffing, length-of-stay, health outcome, or individual-level data. The analysis does not establish overcrowding, delayed care, harm, causation, or policy effectiveness.

### Forecasting

Forecasting is intentionally disabled unless the dataset has at least 90% daily coverage overall and in the trailing 365 days, and no missing-date streak longer than seven days. No imputation or forward-fill is used. If the gate is met in a future replacement dataset, the project still requires a chronological holdout and a baseline comparison before a forecast should be presented.

## Tests

```powershell
pytest
```

The test suite covers loading, blank rows, comma-formatted counts, date ordering/indexing, duplicate dates, invalid counts, review flags, core metrics, coverage-aware aggregation, report generation, and dashboard import.

## Troubleshooting

- **Missing required columns:** preserve the exact source headings shown in the supplied CSV, including the asterisk in the CBP intake column.
- **No valid dates:** check that `Date` values are parseable reporting dates. Invalid rows are retained and identified in the quality report.
- **Dashboard says a metric is unavailable:** check whether the selected date range contains complete values or whether a ratio denominator is zero.
- **No output folders:** run the regeneration command from any directory after installing the package; output paths are resolved from the project package location by default.
- **Forecast disabled:** review the reported date coverage and maximum gap; the project does not fill missing days to make a model eligible.
- **Package installation fails:** use Python 3.11+ and verify the environment can reach the configured Python package index.
