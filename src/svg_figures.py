"""Deterministic SVG charts for the reproducible experiment artifacts.

The chart payloads are written as plain SVG rather than rasterized by a local
graphics stack. This keeps report artifacts byte-stable across CI platforms.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CONTROL_COLOR = "#7f8c8d"
TREATMENT_COLOR = "#2166ac"
INK = "#243447"
GRID = "#d9e1e8"
MARGIN_COLOR = "#8c510a"


def _text(x: float, y: float, value: str, *, size: int = 16, anchor: str = "start") -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" fill="{INK}" font-family="Arial, sans-serif" '
        f'font-size="{size}" text-anchor="{anchor}">{escape(value)}</text>'
    )


def _line(x1: float, y1: float, x2: float, y2: float, *, color: str = GRID, width: float = 1) -> str:
    return (
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{color}" stroke-width="{width:.2f}"/>'
    )


def _circle(x: float, y: float, *, color: str, radius: float = 6) -> str:
    return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{color}"/>'


def _svg(width: int, height: int, elements: list[str]) -> str:
    body = "\n  ".join(elements)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">\n  {body}\n</svg>\n'
    )


def _scale(value: float, low: float, high: float, left: float, right: float) -> float:
    return left + (value - low) / (high - low) * (right - left)


def write_effect_and_guardrails(results: dict[str, Any], path: Path) -> None:
    """Draw the ITT effect, rate guardrail, and time guardrail as stable SVG."""
    primary = results["primary_conversion"]
    cancellation = results["guardrail_cancellation"]
    time_to_book = results["guardrail_time_to_book"]
    elements = [_text(600, 32, "Эффект и guardrail-метрики: intention-to-treat", size=22, anchor="middle")]
    left_x0, left_x1, right_x0, right_x1 = 90, 555, 680, 1145
    rate_low, rate_high = -1.0, 4.0
    for tick in range(-1, 5):
        x = _scale(tick, rate_low, rate_high, left_x0, left_x1)
        elements.extend([_line(x, 85, x, 350), _text(x, 378, f"{tick}", size=13, anchor="middle")])
    elements.extend(
        [
            _line(_scale(0, rate_low, rate_high, left_x0, left_x1), 85, _scale(0, rate_low, rate_high, left_x0, left_x1), 350, color=INK, width=1.5),
            _text((left_x0 + left_x1) / 2, 65, "Разность rate-метрик", size=18, anchor="middle"),
            _text((left_x0 + left_x1) / 2, 412, "Treatment − control, п.п. (95% CI)", size=14, anchor="middle"),
        ]
    )
    for label, metric, y in [
        ("Conversion to booking", primary, 170),
        ("Cancellation rate", cancellation, 280),
    ]:
        difference = 100 * metric["difference"]
        low, high = 100 * metric["ci_low"], 100 * metric["ci_high"]
        elements.extend(
            [
                _text(left_x0 - 14, y + 5, label, size=14, anchor="end"),
                _line(_scale(low, rate_low, rate_high, left_x0, left_x1), y, _scale(high, rate_low, rate_high, left_x0, left_x1), y, color=TREATMENT_COLOR, width=2),
                _line(_scale(low, rate_low, rate_high, left_x0, left_x1), y - 6, _scale(low, rate_low, rate_high, left_x0, left_x1), y + 6, color=TREATMENT_COLOR, width=2),
                _line(_scale(high, rate_low, rate_high, left_x0, left_x1), y - 6, _scale(high, rate_low, rate_high, left_x0, left_x1), y + 6, color=TREATMENT_COLOR, width=2),
                _circle(_scale(difference, rate_low, rate_high, left_x0, left_x1), y, color=TREATMENT_COLOR),
            ]
        )
    time_low, time_high = -2.0, 32.0
    for tick in range(0, 31, 5):
        x = _scale(tick, time_low, time_high, right_x0, right_x1)
        elements.extend([_line(x, 85, x, 350), _text(x, 378, f"{tick}", size=13, anchor="middle")])
    zero_x = _scale(0, time_low, time_high, right_x0, right_x1)
    margin_x = _scale(time_to_book["margin"], time_low, time_high, right_x0, right_x1)
    y = 225
    elements.extend(
        [
            _line(zero_x, 85, zero_x, 350, color=INK, width=1.5),
            f'<line x1="{margin_x:.2f}" y1="85" x2="{margin_x:.2f}" y2="350" stroke="{MARGIN_COLOR}" stroke-width="1.5" stroke-dasharray="6 4"/>',
            _text((right_x0 + right_x1) / 2, 65, "Time-to-book среди бронирований", size=18, anchor="middle"),
            _text((right_x0 + right_x1) / 2, 412, "Treatment − control, секунд (95% CI)", size=14, anchor="middle"),
            _line(_scale(time_to_book["ci_low"], time_low, time_high, right_x0, right_x1), y, _scale(time_to_book["ci_high"], time_low, time_high, right_x0, right_x1), y, color=MARGIN_COLOR, width=2),
            _circle(_scale(time_to_book["difference"], time_low, time_high, right_x0, right_x1), y, color=MARGIN_COLOR),
            _text(margin_x - 8, 330, f"NI-маржа +{time_to_book['margin']:.0f} сек.", size=13, anchor="end"),
        ]
    )
    path.write_text(_svg(1200, 440, elements), encoding="utf-8")


def write_conversion_by_city(mart: pd.DataFrame, path: Path) -> None:
    """Draw pre-specified city conversion values without a platform renderer."""
    rates = (
        mart.groupby(["city", "variant"], observed=True)["booked"]
        .mean()
        .unstack()
        .reindex(columns=["control", "treatment"])
        .sort_index()
    )
    low = float(np.floor((rates.min().min() * 100 - 0.3) * 2) / 2)
    high = float(np.ceil((rates.max().max() * 100 + 0.3) * 2) / 2)
    x0, x1, y0, y1 = 180, 1070, 105, 385
    elements = [_text(625, 35, "Конверсия по предзаданным городам", size=22, anchor="middle")]
    for tick in np.arange(np.ceil(low), np.floor(high) + 1, 1):
        x = _scale(float(tick), low, high, x0, x1)
        elements.extend([_line(x, y0, x, y1), _text(x, 415, f"{tick:.0f}", size=13, anchor="middle")])
    for index, city in enumerate(rates.index):
        y = y0 + index * (y1 - y0) / (len(rates.index) - 1)
        control_x = _scale(float(rates.loc[city, "control"] * 100), low, high, x0, x1)
        treatment_x = _scale(float(rates.loc[city, "treatment"] * 100), low, high, x0, x1)
        elements.extend(
            [
                _line(x0, y, x1, y),
                _text(x0 - 16, y + 5, city, size=15, anchor="end"),
                _line(control_x, y, treatment_x, y, color="#bdc3c7", width=2),
                f'<rect x="{control_x - 5:.2f}" y="{y - 5:.2f}" width="10" height="10" fill="{CONTROL_COLOR}"/>',
                _circle(treatment_x, y, color=TREATMENT_COLOR),
            ]
        )
    elements.extend(
        [
            _text((x0 + x1) / 2, 458, "Конверсия в бронирование, %", size=14, anchor="middle"),
            f'<rect x="860" y="55" width="10" height="10" fill="{CONTROL_COLOR}"/>',
            _text(878, 65, "Control", size=13),
            _circle(865, 84, color=TREATMENT_COLOR),
            _text(878, 89, "Treatment", size=13),
        ]
    )
    path.write_text(_svg(1150, 490, elements), encoding="utf-8")


def write_time_distribution(mart: pd.DataFrame, path: Path) -> None:
    """Draw a density histogram with deterministic binning and SVG serialization."""
    values_by_variant = {
        variant: mart.loc[(mart["variant"] == variant) & (mart["booked"] == 1), "time_to_book_seconds"].to_numpy()
        for variant in ("control", "treatment")
    }
    all_values = np.concatenate(list(values_by_variant.values()))
    low = float(np.floor(all_values.min() / 20) * 20)
    high = float(np.ceil(all_values.max() / 20) * 20)
    edges = np.linspace(low, high, 36)
    densities = {variant: np.histogram(values, bins=edges, density=True)[0] for variant, values in values_by_variant.items()}
    density_max = max(float(density.max()) for density in densities.values()) * 1.08
    x0, x1, y0, y1 = 100, 1120, 80, 375
    elements = [_text(610, 32, "Распределение time-to-book среди бронирований", size=22, anchor="middle")]
    for tick in np.arange(low, high + 1, 100):
        x = _scale(float(tick), low, high, x0, x1)
        elements.extend([_line(x, y0, x, y1), _text(x, 405, f"{tick:.0f}", size=13, anchor="middle")])
    elements.extend(
        [
            _line(x0, y1, x1, y1, color=INK, width=1.5),
            _text((x0 + x1) / 2, 445, "Время от экрана до бронирования, секунд", size=14, anchor="middle"),
            _text(x0, 62, "Плотность", size=14),
        ]
    )
    for variant, color in [("control", CONTROL_COLOR), ("treatment", TREATMENT_COLOR)]:
        points = []
        for index, density in enumerate(densities[variant]):
            center = (edges[index] + edges[index + 1]) / 2
            x = _scale(float(center), low, high, x0, x1)
            y = y1 - float(density) / density_max * (y1 - y0)
            points.append(f"{x:.2f},{y:.2f}")
        elements.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2"/>')
    elements.extend(
        [
            _line(900, 57, 925, 57, color=CONTROL_COLOR, width=3),
            _text(934, 62, "Control", size=13),
            _line(1000, 57, 1025, 57, color=TREATMENT_COLOR, width=3),
            _text(1034, 62, "Treatment", size=13),
        ]
    )
    path.write_text(_svg(1220, 470, elements), encoding="utf-8")
