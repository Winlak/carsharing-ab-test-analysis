"""Generate deterministic, event-level synthetic data for the experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    ANALYSIS_AS_OF,
    BOOKING_EXPOSURE_LOG_ODDS_EFFECT,
    BOOKING_NEW_USER_INTERACTION,
    CANCELLATION_EXPOSURE_LOG_ODDS_EFFECT,
    EXPERIMENT_ID,
    SEED,
    TIME_TO_BOOK_EXPOSURE_EFFECT_SECONDS,
)


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-values))


def _as_utc_strings(values: pd.Series) -> pd.Series:
    return values.dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_experiment(n_users: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return users, assignments, and events for one reproducible A/B test."""
    if n_users < 100:
        raise ValueError("n_users must be at least 100")

    rng = np.random.default_rng(seed)
    user_id = pd.Series([f"u_{i:06d}" for i in range(1, n_users + 1)], name="user_id")
    assigned_at = pd.Series(
        pd.Timestamp("2025-06-01T00:00:00Z")
        + pd.to_timedelta(rng.integers(0, 14 * 24 * 60 * 60, size=n_users), unit="s")
    )
    platform = rng.choice(["iOS", "Android"], size=n_users, p=[0.46, 0.54])
    city = rng.choice(["Moscow", "St_Petersburg", "Kazan", "Yekaterinburg"], size=n_users, p=[0.48, 0.24, 0.16, 0.12])
    is_new_user = rng.binomial(1, 0.42, size=n_users)
    trips_30d = rng.poisson(3.5 + 0.9 * (1 - is_new_user), size=n_users)
    acquisition_channel = rng.choice(["organic", "paid", "referral"], size=n_users, p=[0.51, 0.31, 0.18])

    users = pd.DataFrame(
        {
            "user_id": user_id,
            "platform": platform,
            "city": city,
            "is_new_user": is_new_user,
            "trips_30d": trips_30d,
            "acquisition_channel": acquisition_channel,
        }
    )
    users["trips_30d_bucket"] = pd.cut(
        users["trips_30d"], bins=[-1, 0, 3, 7, np.inf], labels=["0", "1-3", "4-7", "8+"]
    ).astype(str)

    treatment = rng.binomial(1, 0.5, size=n_users)
    assignments = pd.DataFrame(
        {
            "assignment_id": [f"a_{i:06d}" for i in range(1, n_users + 1)],
            "experiment_id": EXPERIMENT_ID,
            "user_id": user_id,
            "variant": np.where(treatment == 1, "treatment", "control"),
            "assigned_at": _as_utc_strings(assigned_at),
            "is_eligible": 1,
        }
    )

    city_booking_effect = pd.Series(city).map(
        {"Moscow": 0.05, "St_Petersburg": 0.00, "Kazan": -0.06, "Yekaterinburg": -0.08}
    ).to_numpy()
    platform_booking_effect = np.where(platform == "iOS", 0.04, -0.03)
    screen_ts = assigned_at + pd.to_timedelta(rng.integers(45, 900, size=n_users), unit="s")

    exposure_probability = np.clip(0.975 - 0.020 * (platform == "Android"), 0.90, 0.99)
    exposed = (treatment == 1) & (rng.random(n_users) < exposure_probability)
    booking_logit = (
        -0.63
        + city_booking_effect
        + platform_booking_effect
        + 0.19 * is_new_user
        + 0.036 * trips_30d
        + exposed * (BOOKING_EXPOSURE_LOG_ODDS_EFFECT + BOOKING_NEW_USER_INTERACTION * is_new_user)
    )
    booked = rng.random(n_users) < _sigmoid(booking_logit)

    city_cancel_effect = pd.Series(city).map(
        {"Moscow": 0.04, "St_Petersburg": 0.00, "Kazan": -0.03, "Yekaterinburg": 0.02}
    ).to_numpy()
    cancellation_logit = (
        -2.34
        + city_cancel_effect
        + 0.18 * is_new_user
        - 0.035 * trips_30d
        + exposed * CANCELLATION_EXPOSURE_LOG_ODDS_EFFECT
    )
    cancelled = booked & (rng.random(n_users) < _sigmoid(cancellation_logit))

    raw_time = rng.lognormal(mean=np.log(165), sigma=0.47, size=n_users)
    time_to_book_seconds = np.maximum(
        20,
        raw_time + exposed * TIME_TO_BOOK_EXPOSURE_EFFECT_SECONDS + 4 * is_new_user - 1.5 * trips_30d,
    ).round().astype(int)
    booking_ts = screen_ts + pd.to_timedelta(time_to_book_seconds, unit="s")
    cancel_ts = booking_ts + pd.to_timedelta(rng.integers(600, 4 * 60 * 60, size=n_users), unit="s")

    screen_events = pd.DataFrame(
        {
            "user_id": user_id,
            "event_name": "booking_screen_view",
            "event_ts": _as_utc_strings(screen_ts),
            "booking_id": pd.NA,
            "platform": platform,
            "event_properties": '{"source":"booking_flow"}',
        }
    )
    exposure_events = pd.DataFrame(
        {
            "user_id": user_id[exposed],
            "event_name": "booking_hint_shown",
            "event_ts": _as_utc_strings(screen_ts[exposed] + pd.to_timedelta(2, unit="s")),
            "booking_id": pd.NA,
            "platform": platform[exposed],
            "event_properties": '{"hint":"price_and_duration"}',
        }
    )
    booking_ids = pd.Series([f"b_{i:06d}" for i in range(1, n_users + 1)])
    booking_events = pd.DataFrame(
        {
            "user_id": user_id[booked],
            "event_name": "booking_created",
            "event_ts": _as_utc_strings(booking_ts[booked]),
            "booking_id": booking_ids[booked].to_numpy(),
            "platform": platform[booked],
            "event_properties": '{"vehicle_class":"standard"}',
        }
    )
    cancellation_events = pd.DataFrame(
        {
            "user_id": user_id[cancelled],
            "event_name": "booking_cancelled",
            "event_ts": _as_utc_strings(cancel_ts[cancelled]),
            "booking_id": booking_ids[cancelled].to_numpy(),
            "platform": platform[cancelled],
            "event_properties": '{"reason":"changed_mind"}',
        }
    )
    events = pd.concat([screen_events, exposure_events, booking_events, cancellation_events], ignore_index=True)
    events = events.sort_values(["event_ts", "user_id", "event_name"], kind="stable").reset_index(drop=True)
    events.insert(0, "event_id", [f"e_{i:07d}" for i in range(1, len(events) + 1)])
    return users, assignments, events


def write_experiment(output_dir: Path, n_users: int, seed: int) -> None:
    """Write sources and transparent data-generating-process metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)
    users, assignments, events = generate_experiment(n_users=n_users, seed=seed)
    users.to_csv(output_dir / "users.csv", index=False)
    assignments.to_csv(output_dir / "assignments.csv", index=False)
    events.to_csv(output_dir / "events.csv", index=False)
    metadata = {
        "synthetic": True,
        "experiment_id": EXPERIMENT_ID,
        "seed": seed,
        "n_users": n_users,
        "analysis_as_of": ANALYSIS_AS_OF,
        "known_effects": {
            "booking_exposure_log_odds": BOOKING_EXPOSURE_LOG_ODDS_EFFECT,
            "booking_new_user_interaction_log_odds": BOOKING_NEW_USER_INTERACTION,
            "cancellation_exposure_log_odds": CANCELLATION_EXPOSURE_LOG_ODDS_EFFECT,
            "time_to_book_exposure_seconds": TIME_TO_BOOK_EXPOSURE_EFFECT_SECONDS,
        },
        "notes": "Do not interpret as real carsharing or Delimobil data.",
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--n-users", type=int, default=60_000)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    write_experiment(args.output_dir, args.n_users, args.seed)
    print(f"Synthetic sources written to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
