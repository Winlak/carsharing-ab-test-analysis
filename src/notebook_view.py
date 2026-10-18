"""Reader-facing notebook outputs, derived from the current experiment."""

from __future__ import annotations

import nbformat
import pandas as pd


def experiment_overview(mart: pd.DataFrame) -> pd.DataFrame:
    """Keep ITT conversion and conditional booking guardrails distinct."""
    users = mart.groupby('variant', observed=True).agg(
        users=('user_id', 'nunique'), conversion=('booked', 'mean'),
    )
    bookers = mart.loc[mart['booked'].eq(1)].groupby('variant', observed=True).agg(
        bookings=('user_id', 'nunique'),
        cancellation_among_bookers=('cancelled_24h', 'mean'),
        mean_time_to_book_among_bookers=('time_to_book_seconds', 'mean'),
    )
    return users.join(bookers).sort_index()


def notebook_summary(results: dict) -> str:
    primary = results['primary_conversion']
    decision = results['decision']
    warning = (
        'Обнаружен SRM. Запуск заблокирован до проверки назначений и логирования.'
        if not decision['randomization_valid'] else
        'SRM не обнаружен. Решение учитывает основной тест, продуктовый порог и защитные метрики.'
    )
    return (
        '## Результат текущего расчёта\n\n'
        f"**Решение: {decision['recommendation'].upper()}.** {warning}\n\n"
        f"Конверсия: {100 * primary['control_rate']:.2f}% → {100 * primary['treatment_rate']:.2f}%. "
        f"Разность: {100 * primary['difference']:.2f} п.п. "
        f"(95% CI {100 * primary['ci_low']:.2f}…{100 * primary['ci_high']:.2f} п.п.).\n\n"
        'Данные сгенерированы; вывод описывает учебный эксперимент.'
    )


def validate_notebook_outputs(notebook: nbformat.NotebookNode, results: dict, mart: pd.DataFrame) -> None:
    cells = {cell['id']: cell for cell in notebook.cells}
    summary_outputs = cells['current-summary'].get('outputs', [])
    markdown = [out.get('data', {}).get('text/markdown') for out in summary_outputs]
    assert notebook_summary(results) in markdown, 'Notebook summary disagrees with current results'
    table_outputs = cells['itt-summary'].get('outputs', [])
    html = [out.get('data', {}).get('text/html') for out in table_outputs]
    assert experiment_overview(mart).to_html() in html, 'Notebook table disagrees with current denominators'
