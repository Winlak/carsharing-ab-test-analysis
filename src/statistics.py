"""Small, testable statistical primitives used by the experiment readout."""

from __future__ import annotations

from collections.abc import Iterable
from math import sqrt

import numpy as np
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize


def proportion_confidence_interval(
    treatment_successes: int,
    treatment_total: int,
    control_successes: int,
    control_total: int,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Wald interval for a treatment-minus-control proportion difference."""
    treatment_rate = treatment_successes / treatment_total
    control_rate = control_successes / control_total
    standard_error = sqrt(
        treatment_rate * (1 - treatment_rate) / treatment_total
        + control_rate * (1 - control_rate) / control_total
    )
    z_value = stats.norm.ppf(1 - alpha / 2)
    difference = treatment_rate - control_rate
    return difference - z_value * standard_error, difference + z_value * standard_error


def proportion_superiority(
    treatment: Iterable[int], control: Iterable[int], alpha: float = 0.05
) -> dict[str, float]:
    """One-sided z-test for improvement plus a two-sided confidence interval."""
    treatment_array = np.asarray(list(treatment), dtype=float)
    control_array = np.asarray(list(control), dtype=float)
    treatment_total = len(treatment_array)
    control_total = len(control_array)
    treatment_rate = float(treatment_array.mean())
    control_rate = float(control_array.mean())
    pooled_rate = float((treatment_array.sum() + control_array.sum()) / (treatment_total + control_total))
    pooled_se = sqrt(pooled_rate * (1 - pooled_rate) * (1 / treatment_total + 1 / control_total))
    difference = treatment_rate - control_rate
    z_stat = difference / pooled_se
    ci_low, ci_high = proportion_confidence_interval(
        int(treatment_array.sum()), treatment_total, int(control_array.sum()), control_total, alpha
    )
    return {
        "control_n": control_total,
        "treatment_n": treatment_total,
        "control_rate": control_rate,
        "treatment_rate": treatment_rate,
        "difference": difference,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "z_stat": z_stat,
        "p_value": float(stats.norm.sf(z_stat)),
    }


def proportion_noninferiority(
    treatment: Iterable[int], control: Iterable[int], margin: float, alpha: float = 0.05
) -> dict[str, float]:
    """One-sided non-inferiority test for a harmful increase in a rate.

    The estimand is treatment minus control. Values below the positive margin
    support non-inferiority; cancellation uses this convention.
    """
    result = proportion_superiority(treatment, control, alpha)
    treatment_rate = result["treatment_rate"]
    control_rate = result["control_rate"]
    standard_error = sqrt(
        treatment_rate * (1 - treatment_rate) / result["treatment_n"]
        + control_rate * (1 - control_rate) / result["control_n"]
    )
    z_stat = (result["difference"] - margin) / standard_error
    result.update(
        {
            "margin": margin,
            "ni_z_stat": z_stat,
            "p_value": float(stats.norm.cdf(z_stat)),
        }
    )
    return result


def welch_noninferiority(
    treatment: Iterable[float], control: Iterable[float], margin: float, alpha: float = 0.05
) -> dict[str, float]:
    """One-sided Welch non-inferiority test for a harmful increase in a mean."""
    treatment_array = np.asarray(list(treatment), dtype=float)
    control_array = np.asarray(list(control), dtype=float)
    treatment_n, control_n = len(treatment_array), len(control_array)
    treatment_mean, control_mean = float(treatment_array.mean()), float(control_array.mean())
    treatment_var, control_var = float(treatment_array.var(ddof=1)), float(control_array.var(ddof=1))
    standard_error = sqrt(treatment_var / treatment_n + control_var / control_n)
    numerator = (treatment_var / treatment_n + control_var / control_n) ** 2
    denominator = (treatment_var / treatment_n) ** 2 / (treatment_n - 1) + (
        control_var / control_n
    ) ** 2 / (control_n - 1)
    degrees_freedom = numerator / denominator
    difference = treatment_mean - control_mean
    test_stat = (difference - margin) / standard_error
    critical_value = stats.t.ppf(1 - alpha / 2, degrees_freedom)
    return {
        "control_n": control_n,
        "treatment_n": treatment_n,
        "control_mean": control_mean,
        "treatment_mean": treatment_mean,
        "difference": difference,
        "ci_low": difference - critical_value * standard_error,
        "ci_high": difference + critical_value * standard_error,
        "margin": margin,
        "welch_df": degrees_freedom,
        "t_stat": test_stat,
        "p_value": float(stats.t.cdf(test_stat, degrees_freedom)),
    }


def srm_check(control_n: int, treatment_n: int) -> dict[str, float]:
    """Chi-square sample-ratio-mismatch check against a 50:50 split."""
    total = control_n + treatment_n
    expected = total / 2
    chi_square = (control_n - expected) ** 2 / expected + (treatment_n - expected) ** 2 / expected
    return {
        "control_n": control_n,
        "treatment_n": treatment_n,
        "expected_per_variant": expected,
        "chi_square": chi_square,
        "p_value": float(stats.chi2.sf(chi_square, df=1)),
    }


def holm_adjust(p_values: list[float]) -> list[float]:
    """Family-wise error correction retaining the input order."""
    return multipletests(p_values, method="holm")[1].tolist()


def minimum_detectable_effect(
    baseline_rate: float, n_per_arm: int, alpha: float = 0.05, power: float = 0.80
) -> float:
    """Two-sided absolute MDE for two equal-sized proportions via root search."""
    analysis = NormalIndPower()
    low, high = 1e-6, min(0.50, 0.999 - baseline_rate)
    for _ in range(60):
        middle = (low + high) / 2
        effect_size = proportion_effectsize(baseline_rate + middle, baseline_rate)
        achieved_power = analysis.power(
            effect_size=effect_size, nobs1=n_per_arm, alpha=alpha, ratio=1.0, alternative="two-sided"
        )
        if achieved_power < power:
            low = middle
        else:
            high = middle
    return high
