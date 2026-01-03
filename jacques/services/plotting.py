from __future__ import annotations

from pathlib import Path
from typing import Any
import json

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover - optional
    plt = None


def generate_plot(spec: dict[str, Any], output_path: Path) -> Path:
    if plt is None:
        raise RuntimeError("matplotlib is required for plot generation.")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    chart_type = str(spec.get("chart_type", "line")).lower()
    title = str(spec.get("title", "")).strip()
    x_label = str(spec.get("x_label", "")).strip()
    y_label = str(spec.get("y_label", "")).strip()
    color = spec.get("color")

    series = spec.get("series")
    fig, ax = plt.subplots(figsize=(7, 4))

    if isinstance(series, list) and series:
        for entry in series:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip() or None
            x_vals = _normalize_list(entry.get("x"))
            y_vals = _normalize_list(entry.get("y"))
            x_vals, y_vals = _ensure_xy(x_vals, y_vals)
            _plot_series(ax, chart_type, x_vals, y_vals, name, entry.get("color"))
        if len(series) > 1:
            ax.legend()
    else:
        x_vals = _normalize_list(spec.get("x"))
        y_vals = _normalize_list(spec.get("y"))
        x_vals, y_vals = _ensure_xy(x_vals, y_vals)
        _plot_series(ax, chart_type, x_vals, y_vals, None, color)

    if title:
        ax.set_title(title)
    if x_label:
        ax.set_xlabel(x_label)
    if y_label:
        ax.set_ylabel(y_label)
    ax.grid(True, alpha=0.25)

    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def _plot_series(
    ax: plt.Axes,
    chart_type: str,
    x_vals: list[Any],
    y_vals: list[Any],
    label: str | None,
    color: str | None,
) -> None:
    if chart_type == "bar":
        ax.bar(x_vals, y_vals, label=label, color=color)
    elif chart_type == "scatter":
        ax.scatter(x_vals, y_vals, label=label, color=color)
    else:
        ax.plot(x_vals, y_vals, label=label, color=color)


def _normalize_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_coerce(item) for item in value]
    if isinstance(value, tuple):
        return [_coerce(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [_coerce(item) for item in data]
        except json.JSONDecodeError:
            pass
        return [_coerce(item) for item in text.split(",") if item.strip()]
    return [_coerce(value)]


def _coerce(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            return float(text) if "." in text else int(text)
        except ValueError:
            return text
    return value


def _ensure_xy(x_vals: list[Any], y_vals: list[Any]) -> tuple[list[Any], list[Any]]:
    if not y_vals:
        return [], []
    if not x_vals or len(x_vals) != len(y_vals):
        x_vals = list(range(1, len(y_vals) + 1))
    return x_vals, y_vals
