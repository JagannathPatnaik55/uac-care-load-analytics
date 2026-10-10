"""Named entry point for reproducible derived features."""

import pandas as pd

from .metrics import derive_metrics


def add_derived_metrics(data: pd.DataFrame) -> pd.DataFrame:
    """Return observed records or a daily index with documented derived fields."""

    return derive_metrics(data)
