import numpy as np
import pandas as pd
import pytest

from src.run_analysis import calculate_results, render_analysis_report


def experiment(control_n=20000, treatment_n=20000, effect=True, harm=False):
    """Fixed outcomes isolate the decision gates from random generator effects."""
    frames = []
    for variant, n in [('control', control_n), ('treatment', treatment_n)]:
        rate = 0.65 if variant == 'treatment' and effect else 0.40
        booked = np.arange(n) < int(n * rate)
        frames.append(pd.DataFrame({
            'user_id': [f'{variant}-{i}' for i in range(n)], 'variant': variant,
            'booked': booked.astype(int), 'has_exposure': variant == 'treatment',
            'cancelled_24h': (np.arange(n) % 100 < 5).astype(int),
            'time_to_book_seconds': 120.0 + np.arange(n) % 20 + (60 if harm and variant == 'treatment' else 0),
            'platform': 'web', 'city': 'Moscow', 'is_new_user': True,
            'trips_30d_bucket': '0',
        }))
    return pd.concat(frames, ignore_index=True)


def test_srm_blocks_otherwise_successful_experiment():
    results, segments = calculate_results(experiment(treatment_n=30000))
    assert results['decision']['statistical_significance']
    assert results['decision']['cancellation_noninferior']
    assert results['decision']['time_to_book_noninferior']
    assert results['decision']['recommendation'] == 'invalid'
    assert not results['decision']['randomization_valid']
    report = render_analysis_report(results, [], segments)
    assert 'Решение: INVALID' in report
    assert 'рекомендация запуска заблокирована' in report


@pytest.mark.parametrize('effect,harm,expected', [(True, False, 'launch'), (False, False, 'iterate'), (True, True, 'iterate')])
def test_balanced_experiment_requires_effect_and_guardrails(effect, harm, expected):
    results, _ = calculate_results(experiment(effect=effect, harm=harm))
    assert results['decision']['randomization_valid']
    assert results['decision']['recommendation'] == expected
