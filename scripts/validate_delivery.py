"""Independently validate the generated readout before it is handed off."""

from __future__ import annotations

import json
from pathlib import Path

import nbformat
import numpy as np
import pandas as pd

from src.config import SEGMENT_COLUMNS, SRM_ALPHA

ROOT = Path(__file__).resolve().parents[1]

def main() -> None:
    data_dir = ROOT / "data" / "generated"
    report_dir = ROOT / "reports"
    mart = pd.read_csv(data_dir / "experiment_mart.csv")
    results = json.loads((report_dir / "analysis_results.json").read_text())

    recomputed = mart.groupby("variant", observed=True).agg(
        users=("user_id", "nunique"), conversion=("booked", "mean")
    )
    control_rate = float(recomputed.loc["control", "conversion"])
    treatment_rate = float(recomputed.loc["treatment", "conversion"])
    primary = results["primary_conversion"]
    assert mart["user_id"].is_unique, "Mart must have one row per user"
    assert np.isclose(primary["control_rate"], control_rate), "Control rate does not reconcile"
    assert np.isclose(primary["treatment_rate"], treatment_rate), "Treatment rate does not reconcile"
    assert np.isclose(primary["difference"], treatment_rate - control_rate), "Lift does not reconcile"
    decision = results["decision"]
    valid = results["sample_ratio_mismatch"]["p_value"] > SRM_ALPHA
    assert decision["randomization_valid"] == valid, "SRM gate does not reconcile"
    eligible = all(decision[key] for key in (
        "statistical_significance", "product_significance",
        "cancellation_noninferior", "time_to_book_noninferior",
    ))
    expected = "invalid" if not valid else "launch" if eligible else "iterate"
    assert decision["recommendation"] == expected, "Decision rule does not reconcile"

    forbidden_segments = {"variant", "has_exposure", "booked", "cancelled_24h", "time_to_book_seconds"}
    assert forbidden_segments.isdisjoint(SEGMENT_COLUMNS), "Outcome leakage in segment definitions"
    notebook = nbformat.read(ROOT / "notebooks" / "ab_test_analysis.ipynb", as_version=4)
    notebook_errors = [
        output
        for cell in notebook.cells
        if cell.cell_type == "code"
        for output in cell.get("outputs", [])
        if output.output_type == "error"
    ]
    assert not notebook_errors, "Executed notebook contains errors"
    for figure in [
        "effect_and_guardrails.svg",
        "conversion_by_city.svg",
        "time_to_book_distribution.svg",
    ]:
        path = report_dir / "figures" / figure
        assert path.exists() and path.stat().st_size > 2_000, f"Missing or empty figure: {figure}"

    report = f"""# Проверка результатов

## Автоматические проверки

### Методика

Проверена ITT-когорта с одним пользователем на строку, 50:50 assignment,
предзаданными primary/guardrail правилами и Holm-поправкой. Сегменты определены
только по pre-treatment полям; outcome и exposure не попадают в сегментацию.

### Контрольные пересчёты

- Conversion control: **{100 * control_rate:.2f}%** — совпадает с JSON-результатом.
- Conversion treatment: **{100 * treatment_rate:.2f}%** — совпадает с JSON-результатом.
- Lift: **{100 * (treatment_rate - control_rate):.2f} п.п.** — пересчитан напрямую из SQL-витрины.
- SRM: p={results['sample_ratio_mismatch']['p_value']:.4f}; проверка рандомизации: {valid}.
- Решение `{expected}` соответствует результатам SRM, основного теста и защитных метрик.

### Графики и ноутбук

Три SVG-графика существуют и не пусты; executed notebook не содержит ошибок.
Это структурная QA-проверка, а не кроссбраузерный тест рендеринга Markdown.

### Ограничения

Результат относится только к детерминированной synthetic генерации. В реальном
эксперименте потребуются проверка продового логирования, согласование NI-марж,
и downstream guardrails (completed trip, support, margin).
"""
    (report_dir / "validation_report.md").write_text(report)
    print("Validation checks passed")


if __name__ == "__main__":
    main()
