# Data dictionary

Все таблицы создаются `src/generate_data.py`. Время — UTC, идентификаторы
псевдонимизированы и полностью синтетические.

## `users.csv`

Гранулярность: один пользователь.

| Поле | Тип | Описание | Когда известно |
| --- | --- | --- | --- |
| `user_id` | string | Синтетический идентификатор пользователя | до assignment |
| `platform` | string | `iOS` или `Android` | до assignment |
| `city` | string | Синтетический город | до assignment |
| `is_new_user` | int | Флаг нового пользователя | до assignment |
| `trips_30d` | int | Число поездок за прошлые 30 дней | до assignment |
| `trips_30d_bucket` | string | Предзаданный бакет частоты поездок | до assignment |
| `acquisition_channel` | string | Synthetic acquisition channel | до assignment |

## `assignments.csv`

Гранулярность: одно назначение на пользователя и эксперимент.

| Поле | Тип | Описание |
| --- | --- | --- |
| `assignment_id` | string | Уникальный ID назначения |
| `experiment_id` | string | `booking_hint_v1` |
| `user_id` | string | Ключ к users/events |
| `variant` | string | `control` или `treatment` |
| `assigned_at` | timestamp | Время назначения |
| `is_eligible` | int | Включён ли пользователь в эксперимент |

## `events.csv`

Гранулярность: одно событие.

| Поле | Тип | Описание |
| --- | --- | --- |
| `event_id` | string | Уникальный ID события |
| `user_id` | string | Ключ к пользователю |
| `event_name` | string | Одно из четырёх событий ниже |
| `event_ts` | timestamp | Время события |
| `booking_id` | string/null | ID бронирования для booking/cancel событий |
| `platform` | string | Платформа в момент события |
| `event_properties` | JSON string | Контекст события, не используется как outcome |

События:

- `booking_screen_view` — пользователь открыл целевой экран;
- `booking_hint_shown` — treatment-подсказка реально отрисована;
- `booking_created` — создано бронирование;
- `booking_cancelled` — бронирование отменено.

## `experiment_mart.csv`

Гранулярность: один назначенный eligible пользователь с первым экраном после
assignment и созревшим 24-часовым окном. Формируется SQL-запросом и не
коммитится.

| Поле | Описание |
| --- | --- |
| `variant`, `assigned_at` | assignment для ITT-анализa |
| `screen_ts` | первый релевантный экран бронирования |
| `has_exposure` | показана ли подсказка в следующие 24 часа |
| признаки из `users` | только pre-treatment признаки для срезов |
| `booked` | первое бронирование в следующие 24 часа |
| `cancelled_24h` | отмена этого бронирования в 24 часа |
| `time_to_book_seconds` | время от экрана до бронирования, иначе null |

`has_exposure`, `booked`, `cancelled_24h` и `time_to_book_seconds` не
используются для формирования сегментов — это защита от outcome leakage.
