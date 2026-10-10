from __future__ import annotations

from pathlib import Path

import pandas as pd

import app
from uac_analytics.charts import generate_static_figures
from uac_analytics.data_loader import load_dataset
from uac_analytics.data_validation import validate_dataset
from uac_analytics.feature_engineering import add_derived_metrics
from uac_analytics.report_generation import generate_reports


def test_static_reports_and_figures_are_created(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "data" / "raw" / "HHS_Unaccompanied_Alien_Children_Program.csv"
    bundle = load_dataset(source)
    flags, quality = validate_dataset(bundle)
    metrics = add_derived_metrics(bundle.records)
    paths = generate_static_figures(bundle.daily_index, tmp_path / "figures")
    reports = generate_reports(metrics, bundle.daily_index, flags, quality, tmp_path)
    app_result = app._analyze_source.__wrapped__(source.read_bytes(), source.name)
    paper = reports["research_paper"].read_text(encoding="utf-8")
    executive = reports["executive_summary"].read_text(encoding="utf-8")

    assert len(paths) >= 6
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)
    assert all(path.exists() and path.stat().st_size > 0 for path in reports.values())
    assert callable(app.main)
    assert len(app_result[3]) == 720
    assert "## KPI summary" in paper
    assert "Care Load Volatility Index" in paper
    assert "Backlog Accumulation Rate" in executive

