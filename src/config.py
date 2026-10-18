"""Design constants for the synthetic experiment.

The constants below are intentionally public: they define the data-generating
process and make the simulated ground truth auditable.
"""

EXPERIMENT_ID = "booking_hint_v1"
SEED = 20250812
ANALYSIS_AS_OF = "2025-06-17 00:00:00+00:00"

# Pre-registered business thresholds.
ALPHA = 0.05
SRM_ALPHA = 0.01
POWER_TARGET = 0.80
MIN_PRODUCT_LIFT_PP = 0.7
CANCELLATION_NI_MARGIN_PP = 1.0
TIME_TO_BOOK_NI_MARGIN_SECONDS = 30.0
MIN_SEGMENT_ARM_SIZE = 500

# Known synthetic DGP effects. Outcomes use post-assignment exposure, while the
# readout is intention-to-treat by assigned variant.
BOOKING_EXPOSURE_LOG_ODDS_EFFECT = 0.105
BOOKING_NEW_USER_INTERACTION = 0.025
CANCELLATION_EXPOSURE_LOG_ODDS_EFFECT = 0.0
TIME_TO_BOOK_EXPOSURE_EFFECT_SECONDS = 3.0

SEGMENT_COLUMNS = ["platform", "city", "is_new_user", "trips_30d_bucket"]
