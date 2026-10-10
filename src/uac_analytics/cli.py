"""Command-line entry point for processed outputs, figures, and reports."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from .analysis import aggregate_periods
from .charts import generate_static_figures
from .config import PROCESSED_DIR, RAW_DATA_PATH, REPORTS_DIR
from .data_loader import DatasetBundle, load_dataset
from .data_validation import data_quality_by_date, validate_dataset
from .feature_engineering import add_derived_metrics
from .report_generation import generate_reports

LOGGER = logging.getLogger("uac_analytics")


def _csv_ready(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    if "date" in result:
        result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return result


def write_processed_outputs(
    bundle: DatasetBundle,
    flags: pd.DataFrame,
    quality: pd.DataFrame,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Save normalized observed, complete-calendar, metric, and quality CSVs."""

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    observed = add_derived_metrics(bundle.records)
    daily = add_derived_metrics(bundle.daily_index)
    date_quality = data_quality_by_date(bundle, flags)
    outputs = {
        "cleaned_observed_records": target / "cleaned_observed_records.csv",
        "full_daily_index": target / "full_daily_index.csv",
        "derived_metrics": target / "derived_metrics.csv",
        "data_quality_flags": target / "data_quality_flags.csv",
        "data_quality_summary": target / "data_quality_report.csv",
        "data_quality_by_date": target / "data_quality_by_date.csv",
        "period_summaries": target / "period_summaries.csv",
    }
    observed_columns = [
        "source_row", "date_raw", "date", "cbp_daily_intake", "cbp_custody", "transfers_to_hhs",
        "hhs_care", "hhs_discharges", "is_observed", "duplicate_date", "exact_duplicate",
    ]
    metric_columns = [
        "source_row", "date", "cbp_daily_intake", "cbp_custody", "transfers_to_hhs", "hhs_care",
        "hhs_discharges", "total_system_load", "hhs_net_intake_pressure", "care_load_growth_rate",
        "cumulative_observed_net_pressure", "cumulative_observed_cbp_stock", "cumulative_observed_hhs_stock",
        "cumulative_observed_total_stock",
    ]
    daily_columns = [column for column in daily.columns if not column.startswith("raw_")]
    _csv_ready(observed[observed_columns]).to_csv(outputs["cleaned_observed_records"], index=False, na_rep="")
    _csv_ready(daily[daily_columns]).to_csv(outputs["full_daily_index"], index=False, na_rep="")
    rolling_columns = sorted(column for column in observed.columns if "_rolling_" in column)
    available_metrics = [column for column in metric_columns if column in observed] + rolling_columns
    _csv_ready(observed[available_metrics]).to_csv(outputs["derived_metrics"], index=False, na_rep="")
    _csv_ready(flags).to_csv(outputs["data_quality_flags"], index=False, na_rep="")
    quality.to_csv(outputs["data_quality_summary"], index=False, na_rep="")
    _csv_ready(date_quality).to_csv(outputs["data_quality_by_date"], index=False, na_rep="")
    if not observed.empty and observed["date"].notna().any():
        start, end = observed["date"].min(), observed["date"].max()
        period_frames = []
        for granularity in ("monthly", "yearly"):
            period_frame = aggregate_periods(observed, granularity, start, end)
            period_frame.insert(0, "granularity", granularity)
            period_frames.append(period_frame)
        period_summary = pd.concat(period_frames, ignore_index=True)
    else:
        period_summary = pd.DataFrame()
    _csv_ready(period_summary).to_csv(outputs["period_summaries"], index=False, na_rep="")
    return outputs


def run_analysis(
    input_path: str | Path = RAW_DATA_PATH,
    processed_dir: str | Path = PROCESSED_DIR,
    reports_dir: str | Path = REPORTS_DIR,
) -> dict[str, object]:
    """Run the complete reproducible analysis from a source CSV."""

    bundle = load_dataset(input_path)
    flags, quality = validate_dataset(bundle)
    processed_paths = write_processed_outputs(bundle, flags, quality, processed_dir)
    figures = generate_static_figures(bundle.daily_index, Path(reports_dir) / "figures")
    report_paths = generate_reports(
        add_derived_metrics(bundle.records), bundle.daily_index, flags, quality, reports_dir
    )
    LOGGER.info(
        "Analyzed %s: %d raw rows, %d blank rows, %d observed records, %d flags",
        bundle.source_name,
        bundle.raw_row_count,
        bundle.blank_rows_removed,
        len(bundle.records),
        len(flags),
    )
    return {
        "bundle": bundle,
        "flags": flags,
        "quality": quality,
        "processed_paths": processed_paths,
        "figure_paths": figures,
        "report_paths": report_paths,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate UAC care-load metrics, quality outputs, figures, and reports.")
    parser.add_argument("--input", type=Path, default=RAW_DATA_PATH, help="CSV with the required supplied source headings.")
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR, help="Directory for derived CSV outputs.")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR, help="Directory for Markdown reports and figures.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = run_analysis(args.input, args.processed_dir, args.reports_dir)
    bundle = result["bundle"]
    quality = result["quality"]
    print(f"Source: {bundle.source_name}")
    print(f"Observed records: {len(bundle.records):,}; blank rows removed: {bundle.blank_rows_removed:,}")
    print("Generated processed CSVs:")
    for path in result["processed_paths"].values():
        print(f"  {path}")
    print("Generated reports:")
    for path in result["report_paths"].values():
        print(f"  {path}")
    print(f"Static figures: {len(result['figure_paths'])}")
    for _, row in quality.loc[quality["check"].isin(["calendar_coverage_pct", "missing_calendar_days", "transfers_exceed_cbp_custody_review_flags"])].iterrows():
        print(f"{row['check']}: {row['value']}")


if __name__ == "__main__":
    main()
