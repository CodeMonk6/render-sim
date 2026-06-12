"""Deterministic, reproducible plotting utilities.

Every plot is generated from ResultBundle quantities + engine-provided raw
data using matplotlib with a fixed style.  Figures are saved to the run's
output directory; the interpreter cites their paths.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def plot_timeseries(
    t: list[float] | np.ndarray,
    y: list[float] | np.ndarray,
    *,
    xlabel: str = "Time (s)",
    ylabel: str = "Value",
    title: str = "",
    out_path: Path,
) -> Path:
    """Save a deterministic x-y time-series plot to *out_path*."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "figure.figsize": (7, 4),
            "font.size": 10,
            "axes.grid": True,
            "grid.alpha": 0.4,
        }
    )
    fig, ax = plt.subplots()
    ax.plot(np.asarray(t), np.asarray(y), linewidth=1.5)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)
    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def plot_bar(
    labels: list[str],
    values: list[float],
    *,
    xlabel: str = "",
    ylabel: str = "Value",
    title: str = "",
    out_path: Path,
) -> Path:
    """Save a deterministic bar chart to *out_path*."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"figure.dpi": 150, "figure.figsize": (6, 4), "font.size": 10})
    fig, ax = plt.subplots()
    ax.bar(labels, values)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)
    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path
