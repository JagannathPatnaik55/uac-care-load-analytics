from __future__ import annotations

from io import StringIO

from uac_analytics.data_loader import load_dataset
from uac_analytics.data_validation import validate_dataset


HEADER = (
    "Date,Children apprehended and placed in CBP custody*,Children in CBP custody,"
    "Children transferred out of CBP custody,Children in HHS Care,"
    "Children discharged from HHS Care\n"
)


def test_invalid_numeric_negative_fractional_and_date_values_are_flagged() -> None:
    source = StringIO(HEADER + "bad date,invalid,-1,1.5,20,2\n")

    bundle = load_dataset(source)
    flags, summary = validate_dataset(bundle)

    rules = set(flags["rule"])
    assert {"invalid_date", "numeric_conversion_failure", "negative_count", "fractional_count"} <= rules
    assert (flags.loc[flags["rule"] == "invalid_date", "source_row"] == 2).any()
    assert not summary.empty


def test_transfer_stock_review_flag_does_not_change_source_metrics() -> None:
    source = StringIO(HEADER + '"January 1, 2024",1,5,7,20,2\n')

    bundle = load_dataset(source)
    original_transfer = bundle.records.loc[0, "transfers_to_hhs"]
    flags, _ = validate_dataset(bundle)

    assert original_transfer == 7
    assert (flags["rule"] == "transfer_exceeds_cbp_custody_review").any()
    assert bundle.records.loc[0, "transfers_to_hhs"] == 7

