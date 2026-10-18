from pathlib import Path

import nbformat
import pandas as pd
import pytest
from nbclient import NotebookClient

from scripts import build_notebook as builder
from src.generate_data import write_experiment
from src.notebook_view import experiment_overview, notebook_summary, validate_notebook_outputs
from src.run_analysis import build_mart, calculate_results

ROOT = Path(__file__).resolve().parents[1]


def test_executed_notebook_updates_summary_and_conditional_rates(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data/generated'
    write_experiment(data_dir, n_users=8000, seed=20250812)
    assignments = pd.read_csv(data_dir / 'assignments.csv')
    removed = set(assignments.loc[assignments['variant'].eq('control'), 'user_id'].iloc[:1500])
    for name in ['users', 'assignments', 'events']:
        frame = pd.read_csv(data_dir / f'{name}.csv')
        frame.loc[~frame['user_id'].isin(removed)].to_csv(data_dir / f'{name}.csv', index=False)
    (tmp_path / 'src').symlink_to(ROOT / 'src', target_is_directory=True)
    (tmp_path / 'sql').symlink_to(ROOT / 'sql', target_is_directory=True)
    target = tmp_path / 'notebook.ipynb'
    monkeypatch.setattr(builder, 'NOTEBOOK_PATH', target)
    builder.build_notebook()
    notebook = nbformat.read(target, as_version=4)
    NotebookClient(notebook, timeout=90, resources={'metadata': {'path': str(tmp_path)}}).execute()

    mart = build_mart(data_dir, ROOT / 'sql/experiment_mart.sql')
    results, _ = calculate_results(mart)
    assert results['decision']['recommendation'] == 'invalid'
    validate_notebook_outputs(notebook, results, mart)
    summary = next(c for c in notebook.cells if c['id'] == 'current-summary')
    rendered = summary.outputs[0].data['text/markdown']
    assert '**Решение: INVALID.**' in rendered
    assert 'LAUNCH' not in rendered
    assert 'LAUNCH' not in notebook.cells[0].source

    table = experiment_overview(mart)
    for variant in ['control', 'treatment']:
        bookers = mart.loc[mart['variant'].eq(variant) & mart['booked'].eq(1)]
        assert table.loc[variant, 'cancellation_among_bookers'] == pytest.approx(bookers['cancelled_24h'].sum() / len(bookers))
        assert table.loc[variant, 'cancellation_among_bookers'] == pytest.approx(results['guardrail_cancellation'][f'{variant}_rate'])
        assert table.loc[variant, 'mean_time_to_book_among_bookers'] == pytest.approx(results['guardrail_time_to_book'][f'{variant}_mean'])

    summary.outputs[0].data['text/markdown'] = rendered.replace('INVALID', 'LAUNCH')
    with pytest.raises(AssertionError, match='summary'):
        validate_notebook_outputs(notebook, results, mart)
    summary.outputs[0].data['text/markdown'] = notebook_summary(results)
    table_cell = next(c for c in notebook.cells if c['id'] == 'itt-summary')
    wrong = table.copy()
    wrong['cancellation_among_bookers'] = mart.groupby('variant')['cancelled_24h'].mean()
    table_cell.outputs[0].data['text/html'] = wrong.to_html()
    with pytest.raises(AssertionError, match='denominators'):
        validate_notebook_outputs(notebook, results, mart)
