from pathlib import Path

import nbformat

from scripts.normalize_notebook import STABLE_NOTEBOOK_METADATA, normalize_notebook
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


def test_notebook_normalization_keeps_outputs_but_removes_timestamps(tmp_path: Path) -> None:
    notebook_path = tmp_path / "executed.ipynb"
    notebook = nbformat.v4.new_notebook(
        metadata={"language_info": {"name": "python", "version": "volatile"}},
        cells=[
            nbformat.v4.new_code_cell(
                "1 + 1",
                execution_count=1,
                metadata={"execution": {"iopub.status.idle": "2026-08-12T00:00:00Z"}},
                outputs=[
                    nbformat.v4.new_output(
                        output_type="execute_result",
                        data={"text/plain": "2"},
                        execution_count=1,
                        metadata={},
                    )
                ],
            )
        ],
    )
    nbformat.write(notebook, notebook_path)

    normalize_notebook(notebook_path)
    normalized = nbformat.read(notebook_path, as_version=4)

    assert normalized.metadata == STABLE_NOTEBOOK_METADATA
    assert "execution" not in normalized.cells[0].metadata
    assert normalized.cells[0].execution_count == 1
    assert normalized.cells[0].outputs[0].data["text/plain"] == "2"
