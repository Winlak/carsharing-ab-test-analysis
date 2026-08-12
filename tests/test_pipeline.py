from pathlib import Path

from src.generate_data import write_experiment
from src.run_analysis import run


def test_end_to_end_pipeline_creates_a_launch_readout(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    report_dir = tmp_path / "reports"
    write_experiment(data_dir, n_users=8_000, seed=20250812)
    results = run(data_dir, Path("sql/experiment_mart.sql"), report_dir)

    assert results["sample_ratio_mismatch"]["p_value"] > 0.01
    assert results["primary_conversion"]["difference"] > 0
    assert (report_dir / "analysis_report.md").exists()
    assert (report_dir / "figures" / "effect_and_guardrails.png").exists()


def test_analysis_uses_pre_treatment_segments_only() -> None:
    from src.config import SEGMENT_COLUMNS

    forbidden = {"booked", "cancelled_24h", "time_to_book_seconds", "has_exposure", "variant"}
    assert forbidden.isdisjoint(SEGMENT_COLUMNS)
