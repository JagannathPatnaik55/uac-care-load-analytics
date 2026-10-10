"""Read and deterministically clean the supplied aggregate operational CSV."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, TextIO

import numpy as np
import pandas as pd

from .config import COUNT_COLUMNS, REQUIRED_SOURCE_COLUMNS, SOURCE_TO_INTERNAL


@dataclass
class DatasetBundle:
    """Raw source, normalized observed rows, and a non-imputed calendar index."""

    raw: pd.DataFrame
    records: pd.DataFrame
    daily_index: pd.DataFrame
    raw_row_count: int
    blank_rows_removed: int
    source_name: str
    source_columns: dict[str, str]
    unexpected_columns: list[str]
    source_not_ascending: bool
    source_order: str


def _read_csv(source: str | Path | bytes | TextIO | BinaryIO) -> tuple[pd.DataFrame, str]:
    options = {"dtype": str, "keep_default_na": False, "skip_blank_lines": False}
    if isinstance(source, bytes):
        return pd.read_csv(BytesIO(source), **options), "uploaded.csv"
    if hasattr(source, "read"):
        name = str(getattr(source, "name", "uploaded.csv"))
        return pd.read_csv(source, **options), Path(name).name
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}. Supply a valid CSV path or upload a file.")
    try:
        return pd.read_csv(path, **options), path.name
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"CSV file is empty: {path}") from exc


def _parse_counts(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip().str.replace(",", "", regex=False)
    cleaned = cleaned.mask(cleaned == "", pd.NA)
    return pd.to_numeric(cleaned, errors="coerce")


def _empty_daily_index() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["date", *COUNT_COLUMNS, "source_row", "is_observed", "duplicate_date"]
    ).astype({"date": "datetime64[ns]", "is_observed": bool, "duplicate_date": bool})


def _build_daily_index(records: pd.DataFrame) -> pd.DataFrame:
    valid = records.loc[records["date"].notna()].copy()
    if valid.empty:
        return _empty_daily_index()

    first, last = valid["date"].min(), valid["date"].max()
    index = pd.date_range(first, last, freq="D", name="date")
    duplicate_dates = set(valid.loc[valid["duplicate_date"], "date"])
    unique_records = valid.loc[~valid["duplicate_date"]].set_index("date")
    unique_records = unique_records.loc[~unique_records.index.duplicated(keep=False)]

    daily = unique_records.reindex(index)[list(COUNT_COLUMNS) + ["source_row"]]
    daily.index.name = "date"
    daily = daily.reset_index()
    observed_dates = set(valid["date"])
    daily["is_observed"] = daily["date"].isin(observed_dates)
    daily["duplicate_date"] = daily["date"].isin(duplicate_dates)
    return daily[["date", *COUNT_COLUMNS, "source_row", "is_observed", "duplicate_date"]]


def load_dataset(source: str | Path | bytes | TextIO | BinaryIO) -> DatasetBundle:
    """Load a CSV, preserve its raw values, normalize counts, and index calendar days.

    Completely blank rows are excluded from ``records`` but remain available in
    ``raw`` and are counted. Rows with invalid dates or counts remain in
    ``records`` for transparent validation.
    """

    raw, source_name = _read_csv(source)
    missing = [column for column in REQUIRED_SOURCE_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError(
            "CSV is missing required source columns: " + ", ".join(missing)
        )

    raw = raw.copy(deep=True)
    blank_mask = raw.apply(lambda row: row.astype("string").str.strip().eq("").all(), axis=1)
    blank_rows_removed = int(blank_mask.sum())
    nonblank = raw.loc[~blank_mask].copy()
    nonblank["source_row"] = nonblank.index.to_series().astype(int) + 2

    records = pd.DataFrame(index=nonblank.index)
    records["source_row"] = nonblank["source_row"].astype(int)
    records["date_raw"] = nonblank["Date"].astype("string")
    parsed = pd.to_datetime(records["date_raw"], format="%B %d, %Y", errors="coerce")
    unparsed = parsed.isna() & records["date_raw"].str.strip().ne("")
    if unparsed.any():
        parsed.loc[unparsed] = pd.to_datetime(
            records.loc[unparsed, "date_raw"], errors="coerce"
        )
    records["date"] = parsed

    for source_column, internal_column in SOURCE_TO_INTERNAL.items():
        if internal_column == "date":
            continue
        raw_values = nonblank[source_column].astype("string")
        records[f"raw_{internal_column}"] = raw_values
        records[internal_column] = _parse_counts(raw_values)

    exact_duplicates = nonblank[list(REQUIRED_SOURCE_COLUMNS)].duplicated(keep=False)
    records["exact_duplicate"] = exact_duplicates.to_numpy(dtype=bool)
    valid_dates = records["date"].notna()
    duplicate_date = pd.Series(False, index=records.index)
    duplicate_date.loc[valid_dates] = records.loc[valid_dates, "date"].duplicated(keep=False)
    records["duplicate_date"] = duplicate_date
    original_dates = records["date"].dropna()
    if original_dates.is_monotonic_increasing:
        source_order = "Oldest-first"
    elif original_dates.is_monotonic_decreasing:
        source_order = "Newest-first"
    else:
        source_order = "Unsorted"
    source_not_ascending = source_order != "Oldest-first"
    records["is_observed"] = records["date"].notna()
    records = records.sort_values(["date", "source_row"], na_position="last", kind="stable").reset_index(drop=True)

    return DatasetBundle(
        raw=raw,
        records=records,
        daily_index=_build_daily_index(records),
        raw_row_count=len(raw),
        blank_rows_removed=blank_rows_removed,
        source_name=source_name,
        source_columns=dict(SOURCE_TO_INTERNAL),
        unexpected_columns=[column for column in raw.columns if column not in REQUIRED_SOURCE_COLUMNS],
        source_not_ascending=source_not_ascending,
        source_order=source_order,
    )
