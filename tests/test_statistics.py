import numpy as np

from src.statistics import (
    holm_adjust,
    minimum_detectable_effect,
    proportion_noninferiority,
    proportion_superiority,
    srm_check,
    welch_noninferiority,
)


def test_srm_check_accepts_balanced_assignment() -> None:
    result = srm_check(control_n=5_000, treatment_n=5_000)
    assert result["p_value"] == 1.0


def test_holm_never_reduces_a_p_value() -> None:
    raw = [0.001, 0.02, 0.04]
    adjusted = holm_adjust(raw)
    assert all(new >= old for new, old in zip(adjusted, raw))
    assert adjusted[0] <= adjusted[1] <= adjusted[2]


def test_noninferiority_passes_when_harm_is_far_below_margin() -> None:
    control = np.r_[np.ones(1_000), np.zeros(9_000)]
    treatment = np.r_[np.ones(1_000), np.zeros(9_000)]
    result = proportion_noninferiority(treatment, control, margin=0.01)
    assert result["difference"] == 0.0
    assert result["p_value"] < 0.05


def test_superiority_detects_clear_conversion_lift() -> None:
    control = np.r_[np.ones(400), np.zeros(600)]
    treatment = np.r_[np.ones(460), np.zeros(540)]
    result = proportion_superiority(treatment, control)
    assert result["difference"] > 0
    assert result["p_value"] < 0.01


def test_time_noninferiority_respects_positive_margin() -> None:
    control = np.linspace(170.0, 190.0, 1_000)
    treatment = control + 4.0
    result = welch_noninferiority(treatment, control, margin=30.0)
    assert result["difference"] == 4.0
    assert result["p_value"] < 0.05


def test_mde_decreases_with_more_users() -> None:
    small = minimum_detectable_effect(baseline_rate=0.40, n_per_arm=2_000)
    large = minimum_detectable_effect(baseline_rate=0.40, n_per_arm=10_000)
    assert large < small
