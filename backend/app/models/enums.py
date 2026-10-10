"""Allowed values from db.md. Enforced with CHECK constraints and request validation."""

ROLES = ("patient", "caregiver")
LINK_STATUSES = ("pending", "active", "revoked")
PERMISSION_KEYS = ("view", "receive_alerts")
PRESCRIPTION_STATUSES = ("draft", "active", "superseded")
WINDOW_KINDS = ("breakfast", "lunch", "dinner", "bedtime", "generic", "custom")
PRESET_WINDOW_KINDS = ("breakfast", "lunch", "dinner", "bedtime", "generic")
FREQUENCIES = ("daily", "every_other_day", "weekly")
DOSE_STATUSES = ("pending", "taken_on_time", "taken_late", "missed", "skipped")
FINAL_DOSE_STATUSES = ("taken_on_time", "taken_late", "missed", "skipped")
CONFIRMATION_METHODS = ("scan", "manual")
MATCH_STATUSES = ("matched", "ambiguous", "no_match", "not_due")
REMINDER_KINDS = (
    "dose_due",
    "dose_followup",
    "missed_dose_alert",
    "missed_dose_resolved",
    "dose_mismatch_alert",
    "refill_update",
)
REMINDER_STATUSES = ("pending", "sent", "failed", "cancelled")
CHANNELS = ("push", "sms", "in_app")
DELIVERY_STATUSES = ("pending", "sent", "failed")
PUSH_PLATFORMS = ("web",)
REFILL_STATUSES = ("requested", "scheduled", "fulfilled", "cancelled")
INVENTORY_REASONS = ("dose", "refill", "manual_adjustment")

DEFAULT_PERMISSIONS = {"view": True, "receive_alerts": True}

# Default dose windows seeded on patient registration (db.md table 6).
# (kind, name, target_time "HH:MM" or None, on_time_before, on_time_after, missed_after)
DEFAULT_WINDOWS = (
    ("breakfast", "Breakfast", "08:00", 30, 60, 120),
    ("lunch", "Lunch", "12:30", 30, 60, 120),
    ("dinner", "Dinner", "19:00", 30, 60, 120),
    ("bedtime", "Bedtime", "21:30", 30, 60, 120),
    ("generic", "Generic", None, 30, 30, 120),
)
