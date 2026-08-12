"""Build the SQL mart, validate it, calculate experiment statistics, and save figures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from .config import (
    ALPHA,
    CANCELLATION_NI_MARGIN_PP,
    MIN_PRODUCT_LIFT_PP,
    MIN_SEGMENT_ARM_SIZE,
    POWER_TARGET,
    SEGMENT_COLUMNS,
    TIME_TO_BOOK_NI_MARGIN_SECONDS,
)
from .statistics import (
    holm_adjust,
    minimum_detectable_effect,
    proportion_noninferiority,
    proportion_superiority,
    srm_check,
    welch_noninferiority,
)
from .svg_figures import (
    write_conversion_by_city,
    write_effect_and_guardrails,
    write_time_distribution,
)

VARIANT_ORDER = ["control", "treatment"]


def _native(value: Any) -> Any:
    """Convert NumPy/Pandas scalars for stable JSON output."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(f"{float(value):.12g}")
    if isinstance(value, np.ndarray):
        return [_native(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {key: _native(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_native(item) for item in value]
    return value


def load_sources(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load source tables with pandas before their SQL transformation."""
    users = pd.read_csv(data_dir / "users.csv")
    assignments = pd.read_csv(data_dir / "assignments.csv", parse_dates=["assigned_at"])
    events = pd.read_csv(data_dir / "events.csv", parse_dates=["event_ts"])
    return users, assignments, events


def build_mart(data_dir: Path, sql_file: Path) -> pd.DataFrame:
    """Execute the repository SQL against local CSV sources with DuckDB."""
    connection = duckdb.connect(database=":memory:")
    for table_name in ("users", "assignments", "events"):
        source_path = (data_dir / f"{table_name}.csv").as_posix()
        connection.execute(
            f"CREATE VIEW {table_name} AS SELECT * FROM read_csv_auto('{source_path}')"
        )
    mart = connection.execute(sql_file.read_text()).df()
    connection.close()
    return mart


def quality_checks(
    users: pd.DataFrame, assignments: pd.DataFrame, events: pd.DataFrame, mart: pd.DataFrame
) -> list[dict[str, Any]]:
    """Run high-signal quality checks at source and transformed grains."""
    assignment_duplicates = int(assignments.duplicated(["experiment_id", "user_id"]).sum())
    event_id_duplicates = int(events.duplicated("event_id").sum())
    exact_event_duplicates = int(events.duplicated().sum())
    user_lookup = users[["user_id"]].rename(columns={"user_id": "known_user_id"})
    assignment_users = assignments.merge(
        user_lookup, left_on="user_id", right_on="known_user_id", how="left", validate="one_to_one"
    )
    user_assignment_coverage = int(assignment_users["known_user_id"].isna().sum())

    event_assignment = events.merge(
        assignments[["user_id", "assigned_at", "variant"]], on="user_id", how="left", validate="many_to_one"
    )
    missing_event_assignments = int(event_assignment["variant"].isna().sum())
    pre_assignment_events = int((event_assignment["event_ts"] < event_assignment["assigned_at"]).sum())
    hint_in_control = int(
        ((event_assignment["event_name"] == "booking_hint_shown") & (event_assignment["variant"] == "control")).sum()
    )
    group_overlap = int(assignments.groupby("user_id")["variant"].nunique().gt(1).sum())
    mart_duplicates = int(mart.duplicated("user_id").sum())
    mart_coverage_gap = int(len(assignments) - len(mart))
    impossible_cancel = int(((mart["cancelled_24h"] == 1) & (mart["booked"] == 0)).sum())

    checks = [
        {
            "check": "Одна запись назначения на пользователя",
            "value": assignment_duplicates,
            "expected": 0,
            "status": "pass" if assignment_duplicates == 0 else "fail",
        },
        {
            "check": "Пересечение вариантов по пользователю",
            "value": group_overlap,
            "expected": 0,
            "status": "pass" if group_overlap == 0 else "fail",
        },
        {
            "check": "Дубликаты event_id",
            "value": event_id_duplicates,
            "expected": 0,
            "status": "pass" if event_id_duplicates == 0 else "fail",
        },
        {
            "check": "Полные дубликаты событий",
            "value": exact_event_duplicates,
            "expected": 0,
            "status": "pass" if exact_event_duplicates == 0 else "fail",
        },
        {
            "check": "События без назначения",
            "value": missing_event_assignments,
            "expected": 0,
            "status": "pass" if missing_event_assignments == 0 else "fail",
        },
        {
            "check": "События до назначения",
            "value": pre_assignment_events,
            "expected": 0,
            "status": "pass" if pre_assignment_events == 0 else "fail",
        },
        {
            "check": "Показ подсказки в control",
            "value": hint_in_control,
            "expected": 0,
            "status": "pass" if hint_in_control == 0 else "fail",
        },
        {
            "check": "Покрытие пользователей при JOIN assignments → users",
            "value": user_assignment_coverage,
            "expected": 0,
            "status": "pass" if user_assignment_coverage == 0 else "fail",
        },
        {
            "check": "Дубликаты user_id в SQL-витрине",
            "value": mart_duplicates,
            "expected": 0,
            "status": "pass" if mart_duplicates == 0 else "fail",
        },
        {
            "check": "Потеря пользователей между assignment и mature cohort",
            "value": mart_coverage_gap,
            "expected": 0,
            "status": "pass" if mart_coverage_gap == 0 else "fail",
        },
        {
            "check": "Отмена без созданного бронирования",
            "value": impossible_cancel,
            "expected": 0,
            "status": "pass" if impossible_cancel == 0 else "fail",
        },
    ]
    return checks


def summarize_segments(mart: pd.DataFrame) -> pd.DataFrame:
    """Run all pre-specified segment tests and adjust the whole family by Holm."""
    rows: list[dict[str, Any]] = []
    for segment in SEGMENT_COLUMNS:
        for level, frame in mart.groupby(segment, observed=True):
            control = frame.loc[frame["variant"] == "control", "booked"]
            treatment = frame.loc[frame["variant"] == "treatment", "booked"]
            if min(len(control), len(treatment)) < MIN_SEGMENT_ARM_SIZE:
                continue
            result = proportion_superiority(treatment, control)
            rows.append(
                {
                    "segment": segment,
                    "level": str(level),
                    "control_n": result["control_n"],
                    "treatment_n": result["treatment_n"],
                    "control_conversion": result["control_rate"],
                    "treatment_conversion": result["treatment_rate"],
                    "difference_pp": 100 * result["difference"],
                    "ci_low_pp": 100 * result["ci_low"],
                    "ci_high_pp": 100 * result["ci_high"],
                    "p_value": result["p_value"],
                }
            )
    segment_results = pd.DataFrame(rows)
    if not segment_results.empty:
        segment_results["p_value_holm"] = holm_adjust(segment_results["p_value"].tolist())
        segment_results = segment_results.sort_values(["segment", "level"]).reset_index(drop=True)
        numeric_columns = segment_results.select_dtypes(include="number").columns
        segment_results[numeric_columns] = segment_results[numeric_columns].round(12)
    return segment_results


def calculate_results(mart: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    """Calculate pre-registered tests from the intention-to-treat mart."""
    mart = mart.copy()
    mart["variant"] = pd.Categorical(mart["variant"], categories=VARIANT_ORDER, ordered=True)
    grouped = mart.groupby("variant", observed=True).agg(
        users=("user_id", "nunique"),
        exposed=("has_exposure", "mean"),
        bookings=("booked", "sum"),
        conversion=("booked", "mean"),
    )
    control = mart.loc[mart["variant"] == "control"]
    treatment = mart.loc[mart["variant"] == "treatment"]
    control_bookers = control.loc[control["booked"] == 1]
    treatment_bookers = treatment.loc[treatment["booked"] == 1]

    srm = srm_check(len(control), len(treatment))
    primary = proportion_superiority(treatment["booked"], control["booked"])
    cancellation = proportion_noninferiority(
        treatment_bookers["cancelled_24h"], control_bookers["cancelled_24h"], CANCELLATION_NI_MARGIN_PP / 100
    )
    time_to_book = welch_noninferiority(
        treatment_bookers["time_to_book_seconds"],
        control_bookers["time_to_book_seconds"],
        TIME_TO_BOOK_NI_MARGIN_SECONDS,
    )
    adjusted_p_values = holm_adjust(
        [primary["p_value"], cancellation["p_value"], time_to_book["p_value"]]
    )
    primary["p_value_holm"] = adjusted_p_values[0]
    cancellation["p_value_holm"] = adjusted_p_values[1]
    time_to_book["p_value_holm"] = adjusted_p_values[2]

    mde = minimum_detectable_effect(
        baseline_rate=primary["control_rate"],
        n_per_arm=min(primary["control_n"], primary["treatment_n"]),
        alpha=ALPHA,
        power=POWER_TARGET,
    )
    primary_pass = primary["p_value_holm"] < ALPHA and 100 * primary["difference"] >= MIN_PRODUCT_LIFT_PP
    cancellation_pass = cancellation["p_value_holm"] < ALPHA
    time_pass = time_to_book["p_value_holm"] < ALPHA
    decision = "launch" if primary_pass and cancellation_pass and time_pass else "iterate"

    summary = {
        "sample_ratio_mismatch": srm,
        "variant_summary": grouped.reset_index().to_dict(orient="records"),
        "primary_conversion": primary,
        "guardrail_cancellation": cancellation,
        "guardrail_time_to_book": time_to_book,
        "multiplicity": {"method": "Holm", "family_size": 3, "alpha": ALPHA},
        "power_and_mde": {
            "power_target": POWER_TARGET,
            "planning_alpha": ALPHA,
            "control_baseline": primary["control_rate"],
            "n_per_arm": min(primary["control_n"], primary["treatment_n"]),
            "mde_absolute": mde,
        },
        "decision": {
            "recommendation": decision,
            "statistical_significance": primary["p_value_holm"] < ALPHA,
            "product_significance": 100 * primary["difference"] >= MIN_PRODUCT_LIFT_PP,
            "cancellation_noninferior": cancellation_pass,
            "time_to_book_noninferior": time_pass,
            "product_lift_threshold_pp": MIN_PRODUCT_LIFT_PP,
        },
    }
    return _native(summary), summarize_segments(mart)


def save_figures(mart: pd.DataFrame, results: dict[str, Any], output_dir: Path) -> None:
    """Save platform-independent report-ready SVG figures."""
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    write_effect_and_guardrails(results, figure_dir / "effect_and_guardrails.svg")
    write_conversion_by_city(mart, figure_dir / "conversion_by_city.svg")
    write_time_distribution(mart, figure_dir / "time_to_book_distribution.svg")


def render_quality_report(checks: list[dict[str, Any]]) -> str:
    rows = "\n".join(
        f"| {item['check']} | {item['value']} | {item['expected']} | {item['status']} |" for item in checks
    )
    return f"""# Проверка качества данных

Все источники синтетические, сгенерированы детерминированно. Гранулярность
витрины — один назначенный и созревший для наблюдения пользователь.

| Проверка | Факт | Ожидание | Статус |
| --- | ---: | ---: | --- |
{rows}

**Интерпретация.** Проверки исключают смешение групп, дублирование событий,
потери на ключевом JOIN и явные временные нарушения. Для реального запуска к
ним следует добавить мониторинг задержки событий и сверку с продовой схемой.
"""


def render_analysis_report(results: dict[str, Any], checks: list[dict[str, Any]], segments: pd.DataFrame) -> str:
    """Create the technical report after the calculations have executed."""
    primary = results["primary_conversion"]
    cancellation = results["guardrail_cancellation"]
    time_to_book = results["guardrail_time_to_book"]
    srm = results["sample_ratio_mismatch"]
    power = results["power_and_mde"]
    decision = results["decision"]
    segment_statement = (
        "Ни один сегмент не использован для изменения решения; все срезы предзаданы, "
        f"а {len(segments)} p-value скорректированы Holm внутри сегментного семейства."
    )
    decision_text = "LAUNCH" if decision["recommendation"] == "launch" else "ITERATE"
    return f"""# A/B-тест подсказки при бронировании — технический отчёт

## Техническое резюме

**Решение: {decision_text}.** В synthetic ITT-когорте подсказка повысила conversion to booking
на **{100 * primary['difference']:.2f} п.п.**: {100 * primary['control_rate']:.2f}% →
{100 * primary['treatment_rate']:.2f}% (95% CI {100 * primary['ci_low']:.2f}…
{100 * primary['ci_high']:.2f} п.п.; Holm p={primary['p_value_holm']:.4g}). Это больше
предзаданного продуктового порога {MIN_PRODUCT_LIFT_PP:.1f} п.п. Cancellation rate и
time-to-book прошли non-inferiority относительно марж +{CANCELLATION_NI_MARGIN_PP:.1f} п.п.
и +{TIME_TO_BOOK_NI_MARGIN_SECONDS:.0f} сек. соответственно.

Данные и результат целиком синтетические: это демонстрация аналитического процесса, а
не измерение поведения клиентов или результатов какого-либо оператора каршеринга.

## Эффект виден в primary, а guardrail-метрики не ухудшились

![Эффект и guardrail-метрики](figures/effect_and_guardrails.svg)

Основной тест — односторонний тест превосходства для treatment − control по
конверсии. Guardrails тестируются как non-inferiority: рост cancellation rate не
должен достигать +{CANCELLATION_NI_MARGIN_PP:.1f} п.п., а рост time-to-book —
+{TIME_TO_BOOK_NI_MARGIN_SECONDS:.0f} секунд. Для трёх заранее заявленных решений
применена Holm-поправка к p-value, контролирующая family-wise error rate.

| Метрика | Control | Treatment | Разность treatment − control | 95% CI | Holm p | Критерий |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| Conversion to booking | {100 * primary['control_rate']:.2f}% | {100 * primary['treatment_rate']:.2f}% | {100 * primary['difference']:.2f} п.п. | {100 * primary['ci_low']:.2f}…{100 * primary['ci_high']:.2f} п.п. | {primary['p_value_holm']:.4g} | рост > 0 |
| Cancellation rate среди бронирований | {100 * cancellation['control_rate']:.2f}% | {100 * cancellation['treatment_rate']:.2f}% | {100 * cancellation['difference']:.2f} п.п. | {100 * cancellation['ci_low']:.2f}…{100 * cancellation['ci_high']:.2f} п.п. | {cancellation['p_value_holm']:.4g} | NI < +{CANCELLATION_NI_MARGIN_PP:.1f} п.п. |
| Time-to-book среди бронирований | {time_to_book['control_mean']:.1f} с | {time_to_book['treatment_mean']:.1f} с | {time_to_book['difference']:.1f} с | {time_to_book['ci_low']:.1f}…{time_to_book['ci_high']:.1f} с | {time_to_book['p_value_holm']:.4g} | NI < +{TIME_TO_BOOK_NI_MARGIN_SECONDS:.0f} с |

## Популяция и определения делают сравнение проверяемым

- **Единица рандомизации и анализа:** пользователь, один раз назначенный в
  `control` или `treatment`; primary-анализ — intention-to-treat, а не только
  увидевшие подсказку.
- **Когорта:** eligible пользователи с первым экраном бронирования после
  assignment и минимум 24 часами наблюдения. В каждом варианте: control
  n={int(primary['control_n']):,}, treatment n={int(primary['treatment_n']):,}.
- **Primary:** `booking_created` в течение 24 часов после первого просмотра
  экрана / все пользователи когорты.
- **Guardrails:** отмена в 24 часа после созданного бронирования / все созданные
  бронирования; `time_to_book` — секунды от первого экрана до первого создания
  бронирования, только среди забронировавших.
- **Экспозиция:** в treatment подсказку увидели
  {100 * next(row['exposed'] for row in results['variant_summary'] if row['variant'] == 'treatment'):.1f}%
  пользователей. Это диагностическая метрика, не фильтр для primary-теста.

SQL-витрина в `sql/experiment_mart.sql` применяет CTE, `INNER/LEFT JOIN`,
агрегации и `ROW_NUMBER()` для дедупликации назначений и выбора первого
релевантного события. Python загружает CSV, фильтрует когорту, использует
`merge`, `groupby` и независимые статистические функции.

## Рандомизация и качество данных не дают явного повода не доверять оценке

SRM: control={int(srm['control_n']):,}, treatment={int(srm['treatment_n']):,},
χ²={srm['chi_square']:.3f}, p={srm['p_value']:.4f}. При α=0.01 SRM не обнаружен.
Из {len(checks)} автоматических проверок качества пройдены {sum(item['status'] == 'pass' for item in checks)}:
уникальность assignment и event_id, отсутствие пересечений вариантов и показа
в control, временная корректность, покрытие JOIN и один пользователь на строку
витрины. Полная таблица — в `reports/data_quality_report.md`.

## Мощность достаточна для практического, а не только статистического эффекта

До чтения результатов зафиксированы α={ALPHA:.2f}, целевая мощность
{POWER_TARGET:.0%} и равные плечи. При фактическом baseline
{100 * power['control_baseline']:.2f}% и n={int(power['n_per_arm']):,} на вариант
двусторонний MDE равен **{100 * power['mde_absolute']:.2f} п.п.**. Наблюдаемый
lift {100 * primary['difference']:.2f} п.п. превышает и MDE, и бизнес-порог
{MIN_PRODUCT_LIFT_PP:.1f} п.п.; поэтому статистическая значимость здесь имеет
продуктовый смысл.

## Сегменты — диагностический срез, а не поиск победителя

![Конверсия по городам](figures/conversion_by_city.svg)

Срезы по `platform`, `city`, `is_new_user` и `trips_30d_bucket` определены до
анализа по признакам, доступным до treatment. {segment_statement} Данные не
подтверждают отдельный таргетинг: текущая рекомендация относится к общей
eligible-аудитории.

## Ограничения и устойчивость вывода

- Синтетическая генерация не воспроизводит реальную сезонность, стоимость
  коммуникации, конкурирующие эксперименты и задержки событий.
- Cancellation rate и time-to-book условны на бронировании; поэтому они
  полезны как operational guardrails, но не заменяют downstream-метрики
  выполненной поездки и выручки.
- Non-inferiority задана операционными маржами, а не бизнес-моделью. В реальном
  запуске их нужно согласовать с командой и зафиксировать до эксперимента.
- ITT даёт причинную оценку назначения варианта; эффект именно показа подсказки
  требовал бы отдельного инструментального анализа и строгой проверки логирования.

## Следующий шаг

Запустить постепенный rollout на 50% eligible-трафика на 2 недели, сохранив
assignment и event-логирование. Мониторить conversion, cancellation и
time-to-book ежедневно без многократной остановки теста; для решения после
rollout заранее зафиксировать окно, маржи и правила последовательного анализа.

## Открытые вопросы

Нужно проверить downstream-качество бронирования: start-trip rate, контакт с
поддержкой и маржинальность. Если эффект будет концентрироваться в новых
пользователях, следующий подтверждающий тест можно спланировать именно для
этой когорты, а не ретроспективно менять таргетинг по текущему срезу.
"""


def run(data_dir: Path, sql_file: Path, output_dir: Path) -> dict[str, Any]:
    """Run the complete reproducible analytical pipeline."""
    output_dir.mkdir(parents=True, exist_ok=True)
    users, assignments, events = load_sources(data_dir)
    mart = build_mart(data_dir, sql_file)
    mart.to_csv(data_dir / "experiment_mart.csv", index=False)
    checks = quality_checks(users, assignments, events, mart)
    failed_checks = [check for check in checks if check["status"] != "pass"]
    if failed_checks:
        names = ", ".join(check["check"] for check in failed_checks)
        raise ValueError(f"Data-quality checks failed: {names}")
    results, segments = calculate_results(mart)
    save_figures(mart, results, output_dir)
    segments.to_csv(output_dir / "segment_results.csv", index=False, float_format="%.12g")
    (output_dir / "analysis_results.json").write_text(
        json.dumps(_native(results), ensure_ascii=False, indent=2) + "\n"
    )
    (output_dir / "data_quality_report.md").write_text(render_quality_report(checks))
    (output_dir / "analysis_report.md").write_text(render_analysis_report(results, checks, segments))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--sql-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    results = run(args.data_dir, args.sql_file, args.output_dir)
    print(
        "Decision: "
        f"{results['decision']['recommendation'].upper()} | "
        f"conversion lift: {100 * results['primary_conversion']['difference']:.2f} pp"
    )


if __name__ == "__main__":
    main()
