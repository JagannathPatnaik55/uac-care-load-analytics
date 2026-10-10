"""Consistent static report figures and reusable interactive chart builders."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .config import METRIC_LABELS
from .metrics import derive_metrics


COLORS = {
    "total_system_load": "#183B56",
    "cbp_custody": "#2F80A7",
    "hhs_care": "#6B5CA5",
    "cbp_daily_intake": "#D97706",
    "transfers_to_hhs": "#238B78",
    "hhs_discharges": "#C44747",
    "hhs_net_intake_pressure": "#6B5CA5",
}


def _configure_axis(ax: plt.Axes, dates: pd.Series | None = None) -> None:
    ax.grid(True, axis="y", color="#D8E0E7", linewidth=0.7, alpha=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if dates is not None and not dates.empty:
        locator = mdates.AutoDateLocator(minticks=4, maxticks=9)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))


def _save_figure(fig: plt.Figure, output: Path) -> Path:
    fig.tight_layout()
    fig.savefig(output, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output


def generate_static_figures(daily_index: pd.DataFrame, output_dir: str | Path) -> list[Path]:
    """Write six labeled PNG figures, preserving missing days as line gaps."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    data = derive_metrics(daily_index) if not daily_index.empty else daily_index.copy()
    figures: list[Path] = []
    if not data.empty:
        data["date"] = pd.to_datetime(data["date"])
        note = "Source dates without records remain gaps; no values are interpolated or filled."
        date_min, date_max = data["date"].min().date(), data["date"].max().date()
        span = f"{date_min:%b %d, %Y} – {date_max:%b %d, %Y}"
    else:
        note, span = "No valid dated observations are available.", "No valid date range"

    specifications = [
        ("total_system_load.png", "total_system_load", "Total System Load", "Children in active custody/care"),
        ("cbp_vs_hhs_load.png", None, "CBP and HHS Active Loads", "Children in active custody/care"),
        ("transfers_and_discharges.png", None, "Transfers and HHS Discharges", "Children per observed reporting record"),
        ("hhs_net_intake_pressure.png", "hhs_net_intake_pressure", "HHS Net Intake Pressure", "Children per observed reporting record"),
    ]
    for filename, metric, title, ylabel in specifications:
        fig, ax = plt.subplots(figsize=(10.5, 4.7))
        if data.empty:
            ax.text(0.5, 0.5, "No valid dated observations", ha="center", va="center", transform=ax.transAxes)
        elif metric == "total_system_load":
            ax.plot(data["date"], data[metric], color=COLORS[metric], linewidth=1.35, label="Observed daily total")
        elif title == "CBP and HHS Active Loads":
            for column in ("cbp_custody", "hhs_care"):
                ax.plot(data["date"], data[column], color=COLORS[column], linewidth=1.25, label=METRIC_LABELS[column])
        elif title == "Transfers and HHS Discharges":
            for column in ("transfers_to_hhs", "hhs_discharges"):
                ax.plot(data["date"], data[column], color=COLORS[column], linewidth=1.1, label=METRIC_LABELS[column])
        else:
            ax.axhline(0, color="#5B6573", linewidth=1, linestyle="--", label="Zero net flow")
            ax.plot(data["date"], data[metric], color=COLORS[metric], linewidth=1.15, label=METRIC_LABELS[metric])
        ax.set_title(f"{title}\n{span}", loc="left", fontsize=13, weight="bold")
        ax.set_xlabel("Reporting date")
        ax.set_ylabel(ylabel)
        if not data.empty:
            _configure_axis(ax, data["date"])
            ax.legend(frameon=False, ncol=2, loc="best")
        fig.text(0.01, 0.005, note, fontsize=8, color="#53616D")
        figures.append(_save_figure(fig, output / filename))

    fig, ax = plt.subplots(figsize=(10.5, 4.5))
    if data.empty:
        ax.text(0.5, 0.5, "No valid dated observations", ha="center", va="center", transform=ax.transAxes)
    else:
        monthly = data.set_index("date")["is_observed"].resample("MS").agg(["sum", "count"])
        monthly["coverage_pct"] = monthly["sum"] / monthly["count"] * 100
        ax.bar(monthly.index, monthly["coverage_pct"], width=22, color="#2F80A7", align="center")
        ax.set_ylim(0, 105)
        _configure_axis(ax, pd.Series(monthly.index))
    ax.set_title(f"Monthly Reporting-Date Coverage\n{span}", loc="left", fontsize=13, weight="bold")
    ax.set_xlabel("Month")
    ax.set_ylabel("Observed calendar days (%)")
    fig.text(0.01, 0.005, "Coverage = distinct observed dates ÷ calendar dates within the analyzed reporting span.", fontsize=8, color="#53616D")
    figures.append(_save_figure(fig, output / "monthly_reporting_coverage.png"))

    fig, ax = plt.subplots(figsize=(8.8, 4.6))
    load = data.get("total_system_load", pd.Series(dtype=float)).dropna() if not data.empty else pd.Series(dtype=float)
    if load.empty:
        ax.text(0.5, 0.5, "No total-load values available", ha="center", va="center", transform=ax.transAxes)
    else:
        ax.hist(load, bins=min(30, max(8, int(np.sqrt(len(load)))),), color="#2F80A7", edgecolor="white")
    ax.set_title("Distribution of Observed Total System Load", loc="left", fontsize=13, weight="bold")
    ax.set_xlabel("Children in active CBP custody + HHS care")
    ax.set_ylabel("Observed reporting dates")
    _configure_axis(ax)
    fig.text(0.01, 0.005, "Distribution uses observed dates only; it is not a capacity distribution.", fontsize=8, color="#53616D")
    figures.append(_save_figure(fig, output / "total_load_distribution.png"))
    return figures


def make_plotly_figure(
    data: pd.DataFrame,
    columns: Iterable[str],
    title: str,
    y_title: str,
    *,
    zero_line: bool = False,
    threshold: float | None = None,
) -> go.Figure:
    """Build an interactive time-series chart that does not connect gaps."""

    figure = go.Figure()
    if not data.empty and "date" in data:
        ordered = data.sort_values("date", kind="stable")
        for column in columns:
            if column not in ordered:
                continue
            label = METRIC_LABELS.get(column, column.replace("_", " ").title())
            figure.add_trace(
                go.Scatter(
                    x=ordered["date"],
                    y=ordered[column],
                    mode="lines",
                    name=label,
                    connectgaps=False,
                    line={"color": COLORS.get(column, "#435466"), "width": 2},
                    hovertemplate="%{x|%b %d, %Y}<br>%{y:,.1f}<extra>%{fullData.name}</extra>",
                )
            )
    if zero_line:
        figure.add_hline(y=0, line_dash="dash", line_color="#68737D", annotation_text="Zero")
    if threshold is not None:
        figure.add_hline(y=threshold, line_dash="dot", line_color="#D97706", annotation_text="Selected percentile")
    figure.update_layout(
        title={"text": title, "x": 0, "xanchor": "left"},
        xaxis_title="Reporting date / period",
        yaxis_title=y_title,
        hovermode="x unified",
        legend={"orientation": "h", "y": -0.22, "x": 0},
        margin={"l": 18, "r": 18, "t": 58, "b": 64},
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis={"showgrid": False},
        yaxis={"gridcolor": "#E4E9EE", "zeroline": False},
    )
    return figure
