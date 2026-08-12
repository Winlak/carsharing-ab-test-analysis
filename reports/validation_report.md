# Validation report

## Overall Assessment: Ready to share

### Methodology Review

Проверена ITT-когорта с одним пользователем на строку, 50:50 assignment,
предзаданными primary/guardrail правилами и Holm-поправкой. Сегменты определены
только по pre-treatment полям; outcome и exposure не попадают в сегментацию.

### Calculation Spot-Checks

- Conversion control: **40.64%** — совпадает с JSON-результатом.
- Conversion treatment: **43.44%** — совпадает с JSON-результатом.
- Lift: **2.80 п.п.** — пересчитан напрямую из SQL-витрины.
- SRM: p=0.2332 > 0.01.
- Guardrails: оба non-inferiority условия и product threshold прошли.

### Visualization and Notebook Review

Три PNG-графика существуют и не пусты; executed notebook не содержит ошибок.
Это структурная QA-проверка, а не кроссбраузерный тест рендеринга Markdown.

### Required Caveats

Результат относится только к детерминированной synthetic генерации. В реальном
эксперименте потребуются проверка продового логирования, согласование NI-марж,
и downstream guardrails (completed trip, support, margin).
