# A/B-тест подсказки при бронировании

> Портфолио-кейс продуктового аналитика. Все данные синтетические и
> воспроизводимо сгенерированы; это не данные Делимобиля или иного оператора.

Новая подсказка на экране бронирования должна увеличить conversion to booking,
не ухудшив cancellation rate и time-to-book. Репозиторий демонстрирует полный
путь эксперимента: event-level данные → SQL-витрина → Python-статистика →
decision-ready отчёт и проверки в CI.

## Вывод

**Решение: launch с постепенным rollout.** В synthetic ITT-когорте из 60 000
пользователей conversion выросла с **40.64%** до **43.44%**: +**2.80 п.п.**
(95% CI +2.01…+3.59 п.п.; Holm p < 0.001). Это и статистически значимо, и больше
заранее зафиксированного продуктового порога +0.7 п.п.

Guardrails прошли non-inferiority: cancellation выросла лишь на +0.14 п.п.
(95% CI −0.57…+0.84 п.п.; разрешённая маржа +1.0 п.п.), а time-to-book — на
+2.4 сек. (95% CI +0.1…+4.6 сек.; маржа +30 сек.). SRM не обнаружен:
control 29 854, treatment 30 146, χ²=1.42, p=0.233.

Полный отчёт: [reports/analysis_report.md](reports/analysis_report.md). Графики:
`reports/figures/`. Числа создаются pipeline, а не вписаны вручную.

## Бизнес-вопрос и решение

| Элемент | Определение |
| --- | --- |
| Решение | Запускать ли подсказку в eligible-аудитории экрана бронирования? |
| Unit of randomization | Пользователь, 50:50 control/treatment |
| Primary | Пользователь создал бронирование в 24 часа после первого экрана / все пользователи когорты |
| Guardrail 1 | Отмена в 24 часа после бронирования / все созданные бронирования |
| Guardrail 2 | Секунды от первого экрана до первого бронирования, среди забронировавших |
| Предзаданные условия launch | Holm-adjusted primary p < 0.05, lift ≥ +0.7 п.п., оба guardrail non-inferiority p < 0.05 |

Primary-анализ — **intention-to-treat** (по assignment), поэтому неполный показ
подсказки не создаёт смещения за счёт фильтрации по exposure. Exposure (96.4% в
treatment) используется как диагностическая метрика. Сегменты — `platform`,
`city`, `is_new_user`, `trips_30d_bucket`: они заданы до анализа и проходят
Holm-поправку как отдельное семейство; по ним не меняется основное решение.

## Данные и известный ground truth

Нет внешних источников и персональных данных. Скрипт
[`src/generate_data.py`](src/generate_data.py) с фиксированным seed создаёт:

- `users.csv` — предэкспериментальные признаки;
- `assignments.csv` — assignment;
- `events.csv` — `booking_screen_view`, `booking_hint_shown`,
  `booking_created`, `booking_cancelled`.

Параметры генератора открыто зафиксированы в
[`src/config.py`](src/config.py): подсказка повышает log-odds бронирования на
0.105 (с небольшим усилением для новых пользователей), не меняет log-odds
отмены и добавляет 3 секунды к времени бронирования у реально увидевших
подсказку. Поэтому ITT-эффект намеренно известен, но конечная выборочная оценка
и p-value всё равно получаются из случайной реализации.

Generated CSV и витрина не коммитятся. Лицензия кода и сгенерированных данных —
[MIT](LICENSE). Поля описаны в [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

## Что именно делает SQL и Python

[`sql/experiment_mart.sql`](sql/experiment_mart.sql) — не декоративный запрос:
в нём есть CTE, `INNER/LEFT JOIN`, агрегации, окно `ROW_NUMBER()` для дедупликации
assignment и первого события, а также 24-часовые окна наблюдения. Результат —
одна строка на пользователя с assignment, exposure, признаками и outcome.

[`src/run_analysis.py`](src/run_analysis.py) загружает источники через pandas,
использует `filter`, `merge` и `groupby`, выполняет SQL в DuckDB, проверяет
качество данных и считает:

1. SRM χ²-тест относительно 50:50;
2. мощность и MDE (80%, двусторонний α=0.05);
3. 95% CI и направленный z-тест для conversion;
4. two-sided CI и one-sided non-inferiority для cancellation/time-to-book;
5. Holm-поправку для семьи primary + 2 guardrails;
6. предзаданный сегментный анализ без p-hacking.

## Быстрый старт

Требуется Python 3.9+.

```bash
git clone https://github.com/Winlak/carsharing-ab-test-analysis.git
cd carsharing-ab-test-analysis
python3 -m venv .venv
source .venv/bin/activate
make install
python scripts/build_notebook.py
make reproduce
```

Результаты появятся в `reports/`; выполненный ноутбук —
`notebooks/ab_test_analysis.ipynb`. `make reproduce-ci` использует тот же
полный детерминированный сценарий, что и `make reproduce`.

## Проверки и воспроизводимость

```bash
make lint       # статический анализ
make test       # ключевые статистические расчёты и e2e pipeline
make check      # lint + tests + SQL/Python/notebook reproduction
```

GitHub Actions запускает эти проверки на каждом push в `main` и pull request.
Сгенерированные данные, кэши, виртуальное окружение и промежуточные файлы
исключены через `.gitignore`.

## Структура

```text
src/                    генератор, статистика и orchestration pipeline
sql/                    SQL-витрина из событий
notebooks/              выполненный читабельный Jupyter notebook
reports/                отчёт, data-quality checks, результаты и PNG-графики
tests/                  unit- и end-to-end проверки
.github/workflows/      CI: lint, tests, reproducibility
```

## Ограничения

- Это синтетический кейс: величина эффекта, feature mix и качество событий не
  являются оценками реального рынка или сервиса.
- Guardrails условны на совершённом бронировании, поэтому в production стоит
  добавить completed-trip rate, поддержку, выручку и маржинальность.
- Non-inferiority маржи (+1 п.п. и +30 секунд) — явные рабочие допущения; их
  следует согласовать до реального запуска.
- Эффект ITT причинно интерпретируем для assignment. Эффект фактического показа
  подсказки требует отдельного IV/CACE-анализа и строгого аудита exposure-логов.

## Одна строка для резюме

Построил воспроизводимый A/B-тест для сценария каршеринга: спроектировал
event-level synthetic data и SQL-витрину, реализовал SRM/MDE/CI/Holm и
non-inferiority guardrails в Python, оформил decision-ready отчёт и CI pipeline.
