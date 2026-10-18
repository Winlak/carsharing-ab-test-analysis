"""Create the reader-facing executed notebook source from reproducible cells."""

from pathlib import Path
from textwrap import dedent

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT / "notebooks" / "ab_test_analysis.ipynb"


def markdown(cell_id: str, source: str):
    """Create a markdown cell with a stable notebook cell identifier."""
    cell = nbf.v4.new_markdown_cell(dedent(source).strip())
    cell["id"] = cell_id
    return cell


def code(cell_id: str, source: str):
    """Create a code cell with a stable notebook cell identifier."""
    cell = nbf.v4.new_code_cell(dedent(source).strip())
    cell["id"] = cell_id
    return cell


def build_notebook() -> None:
    notebook = nbf.v4.new_notebook()
    notebook["metadata"] = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    }
    notebook["cells"] = [
        markdown(
            "title",
            """
            # A/B-тест подсказки при бронировании

            ## Краткие результаты

            **Решение: LAUNCH с постепенным rollout.** В зафиксированной synthetic
            реализации treatment увеличивает conversion с 40.64% до 43.44%:
            +2.80 п.п. (95% CI +2.01…+3.59 п.п.; Holm p < 0.001). Это выше MDE
            1.13 п.п. и продуктового порога +0.7 п.п. Cancellation и time-to-book
            проходят предзаданные non-inferiority маржи. Ниже — воспроизводимый
            путь от событий к этому решению.
            """
        ),
        markdown(
            "context-methods",
            """
            ## Задача и методика

            **Решение:** запускать ли новую подсказку на экране бронирования.

            **Primary:** conversion to booking в течение 24 часов после первого экрана.
            **Guardrails:** cancellation rate в 24 часа после бронирования и time-to-book.
            **Дизайн:** user-level 50:50 A/B, ITT-анализ, Holm для семьи из primary и
            двух guardrails. Синтетические данные не относятся к реальному каршерингу.

            ### Допущения

            Когорта состоит из eligible пользователей с созревшим 24-часовым окном;
            сегменты заданы до treatment и не применяются для смены решения.
            """
        ),
        markdown("data-heading", "## Данные"),
        code(
            "load-sources",
            """
            from pathlib import Path
            import json
            import sys
            import pandas as pd

            ROOT = Path.cwd().resolve()
            if not (ROOT / "src").exists():
                ROOT = ROOT.parent
            sys.path.insert(0, str(ROOT))

            from src.run_analysis import build_mart, calculate_results, load_sources, quality_checks

            DATA_DIR = ROOT / "data" / "generated"
            SQL_FILE = ROOT / "sql" / "experiment_mart.sql"
            users, assignments, events = load_sources(DATA_DIR)
            users.head()
            """
        ),
        code(
            "validate-events",
            """
            # pandas filter + merge: проверить покрытие событий назначениями.
            post_assignment_events = events.merge(
                assignments[["user_id", "assigned_at", "variant"]],
                on="user_id", how="left", validate="many_to_one"
            ).query("event_ts >= assigned_at")
            post_assignment_events.groupby(["variant", "event_name"], observed=True).size().unstack(fill_value=0)
            """
        ),
        markdown("results-heading", "## Расчёты"),
        code(
            "build-mart",
            """
            # SQL builds a one-row-per-user mart with CTEs, joins and window functions.
            mart = build_mart(DATA_DIR, SQL_FILE)
            checks = quality_checks(users, assignments, events, mart)
            pd.DataFrame(checks)
            """
        ),
        code(
            "itt-summary",
            """
            # pandas groupby makes the ITT denominators visible before inferential tests.
            mart.groupby("variant", observed=True).agg(
                users=("user_id", "nunique"),
                conversion=("booked", "mean"),
                cancellation=("cancelled_24h", "mean"),
                median_time_to_book=("time_to_book_seconds", "median"),
            )
            """
        ),
        code(
            "inferential-results",
            """
            results, segment_results = calculate_results(mart)
            print(json.dumps(results, ensure_ascii=False, indent=2))
            segment_results
            """
        ),
        code(
            "city-chart",
            """
            city_rates = mart.groupby(["city", "variant"], observed=True)["booked"].mean().unstack()
            # Визуализация сохраняется pipeline как reports/figures/conversion_by_city.svg.
            (city_rates * 100).round(2)
            """
        ),
        markdown(
            "takeaways",
            """
            ## Выводы

            Посмотрите `reports/analysis_report.md` для итогового решения и `reports/analysis_results.json`
            для машиночитаемых оценок. Launch разрешён только если Holm-скорректированный
            primary-тест положителен, эффект превышает продуктовый порог, оба guardrail
            non-inferiority теста пройдены и SRM не обнаружен (p > 0.01).
            """
        ),
    ]
    nbf.write(notebook, NOTEBOOK_PATH)


if __name__ == "__main__":
    build_notebook()
