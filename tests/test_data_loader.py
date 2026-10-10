from __future__ import annotations

from io import StringIO

import pandas as pd

from uac_analytics.data_loader import load_dataset


CSV_HEADER = (
    "Date,Children apprehended and placed in CBP custody*,Children in CBP custody,"
    "Children transferred out of CBP custody,Children in HHS Care,"
    "Children discharged from HHS Care\n"
)


def test_loader_sorts_removes_only_blank_rows_and_builds_daily_index() -> None:
    csv_text = (
        CSV_HEADER
        + '"January 3, 2024",4,5,2,"2,484",3\n'
        + ",,,,,\n"
        + '"January 1, 2024",1,2,3,20,1\n'
    )

    bundle = load_dataset(StringIO(csv_text))

    assert bundle.raw_row_count == 3
    assert bundle.blank_rows_removed == 1
    assert len(bundle.records) == 2
    assert bundle.records["date"].is_monotonic_increasing
    assert bundle.records.iloc[1]["hhs_care"] == 2484
    assert len(bundle.daily_index) == 3
    missing_day = bundle.daily_index.loc[bundle.daily_index["date"] == pd.Timestamp("2024-01-02")].iloc[0]
    assert not missing_day["is_observed"]
    assert pd.isna(missing_day["hhs_care"])


def test_duplicate_dates_are_preserved_and_not_aggregated() -> None:
    csv_text = (
        CSV_HEADER
        + '"January 1, 2024",1,2,3,20,1\n'
        + '"January 1, 2024",2,3,4,21,2\n'
    )

    bundle = load_dataset(StringIO(csv_text))

    assert len(bundle.records) == 2
    assert bundle.records["cbp_daily_intake"].tolist() == [1, 2]
    duplicate_day = bundle.daily_index.loc[bundle.daily_index["date"] == pd.Timestamp("2024-01-01")].iloc[0]
    assert duplicate_day["duplicate_date"]
    assert pd.isna(duplicate_day["cbp_daily_intake"])


def test_invalid_dates_remain_in_observed_records() -> None:
    csv_text = CSV_HEADER + "not a date,1,2,3,20,1\n"

    bundle = load_dataset(StringIO(csv_text))

    assert len(bundle.records) == 1
    assert pd.isna(bundle.records.iloc[0]["date"])
    assert bundle.records.iloc[0]["source_row"] == 2
    assert bundle.daily_index.empty

