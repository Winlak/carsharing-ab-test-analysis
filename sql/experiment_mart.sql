-- One row per randomized and eligible user. DuckDB syntax.
-- The SQL deliberately uses CTEs, joins, aggregation and window functions so
-- that the analytical mart is formed from event data rather than hand-crafted.
WITH assignment_ranked AS (
    SELECT
        assignment_id,
        experiment_id,
        user_id,
        variant,
        CAST(assigned_at AS TIMESTAMPTZ) AS assigned_at,
        is_eligible,
        ROW_NUMBER() OVER (
            PARTITION BY experiment_id, user_id
            ORDER BY CAST(assigned_at AS TIMESTAMPTZ), assignment_id
        ) AS assignment_rank
    FROM assignments
    WHERE experiment_id = 'booking_hint_v1'
),
assigned AS (
    SELECT *
    FROM assignment_ranked
    WHERE assignment_rank = 1 AND is_eligible = 1
),
screen_ranked AS (
    SELECT
        a.user_id,
        CAST(e.event_ts AS TIMESTAMPTZ) AS screen_ts,
        ROW_NUMBER() OVER (
            PARTITION BY a.user_id
            ORDER BY CAST(e.event_ts AS TIMESTAMPTZ), e.event_id
        ) AS screen_rank
    FROM assigned AS a
    INNER JOIN events AS e
        ON a.user_id = e.user_id
       AND e.event_name = 'booking_screen_view'
       AND CAST(e.event_ts AS TIMESTAMPTZ) >= a.assigned_at
),
first_screen AS (
    SELECT user_id, screen_ts
    FROM screen_ranked
    WHERE screen_rank = 1
),
exposure AS (
    SELECT
        s.user_id,
        MAX(CASE WHEN e.event_name = 'booking_hint_shown' THEN 1 ELSE 0 END) AS has_exposure
    FROM first_screen AS s
    LEFT JOIN events AS e
        ON s.user_id = e.user_id
       AND e.event_name = 'booking_hint_shown'
       AND CAST(e.event_ts AS TIMESTAMPTZ) >= s.screen_ts
       AND CAST(e.event_ts AS TIMESTAMPTZ) < s.screen_ts + INTERVAL '24 hours'
    GROUP BY s.user_id
),
booking_ranked AS (
    SELECT
        s.user_id,
        e.booking_id,
        CAST(e.event_ts AS TIMESTAMPTZ) AS booking_ts,
        ROW_NUMBER() OVER (
            PARTITION BY s.user_id
            ORDER BY CAST(e.event_ts AS TIMESTAMPTZ), e.event_id
        ) AS booking_rank
    FROM first_screen AS s
    INNER JOIN events AS e
        ON s.user_id = e.user_id
       AND e.event_name = 'booking_created'
       AND CAST(e.event_ts AS TIMESTAMPTZ) >= s.screen_ts
       AND CAST(e.event_ts AS TIMESTAMPTZ) < s.screen_ts + INTERVAL '24 hours'
),
first_booking AS (
    SELECT user_id, booking_id, booking_ts
    FROM booking_ranked
    WHERE booking_rank = 1
),
cancellations AS (
    SELECT
        b.user_id,
        MIN(CAST(e.event_ts AS TIMESTAMPTZ)) AS cancelled_at
    FROM first_booking AS b
    INNER JOIN events AS e
        ON b.booking_id = e.booking_id
       AND e.event_name = 'booking_cancelled'
       AND CAST(e.event_ts AS TIMESTAMPTZ) >= b.booking_ts
       AND CAST(e.event_ts AS TIMESTAMPTZ) < b.booking_ts + INTERVAL '24 hours'
    GROUP BY b.user_id
),
matured_users AS (
    SELECT *
    FROM first_screen
    WHERE screen_ts < TIMESTAMPTZ '2025-06-16 00:00:00+00:00'
)
SELECT
    a.experiment_id,
    a.user_id,
    a.variant,
    a.assigned_at,
    m.screen_ts,
    COALESCE(x.has_exposure, 0) AS has_exposure,
    u.platform,
    u.city,
    u.is_new_user,
    u.trips_30d,
    u.trips_30d_bucket,
    u.acquisition_channel,
    CASE WHEN b.user_id IS NOT NULL THEN 1 ELSE 0 END AS booked,
    CASE WHEN c.user_id IS NOT NULL THEN 1 ELSE 0 END AS cancelled_24h,
    CASE
        WHEN b.user_id IS NOT NULL THEN DATE_DIFF('second', m.screen_ts, b.booking_ts)
        ELSE NULL
    END AS time_to_book_seconds
FROM assigned AS a
INNER JOIN matured_users AS m ON a.user_id = m.user_id
INNER JOIN users AS u ON a.user_id = u.user_id
LEFT JOIN exposure AS x ON a.user_id = x.user_id
LEFT JOIN first_booking AS b ON a.user_id = b.user_id
LEFT JOIN cancellations AS c ON a.user_id = c.user_id;
