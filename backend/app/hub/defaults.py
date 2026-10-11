"""Dashboard defaults (match frontend/docs/fixtures/settings.json)."""

DEFAULT_SETTINGS = {
    "thresholds": {"first": 7, "second": 5, "urgent": 3},
    "alert_missed": True,
    "alert_no_refills": True,
    "alert_wrong_bottle": False,
    "remind_again": "30",
    "voice_language": "English",
    "camera_paused": False,
    "caregivers": [],
}
