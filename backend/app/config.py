"""Environment-driven configuration."""

import os
from datetime import timedelta


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://medcheck:medcheck@localhost:5433/medcheck"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or None
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=_int("JWT_ACCESS_MINUTES", 15))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=_int("JWT_REFRESH_DAYS", 7))
    JWT_TOKEN_LOCATION = ["headers"]

    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

    OPENFDA_ENABLED = _bool("OPENFDA_ENABLED", True)
    OPENFDA_API_KEY = os.getenv("OPENFDA_API_KEY") or None
    OPENFDA_TIMEOUT_S = float(os.getenv("OPENFDA_TIMEOUT_S", "5"))

    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID") or None
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN") or None
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER") or None
    FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON") or None

    DOSE_HORIZON_HOURS = _int("DOSE_HORIZON_HOURS", 48)
    WORKER_DISPATCH_INTERVAL_S = _int("WORKER_DISPATCH_INTERVAL_S", 30)
    WORKER_MISSED_INTERVAL_S = _int("WORKER_MISSED_INTERVAL_S", 60)
    WORKER_GENERATE_INTERVAL_S = _int("WORKER_GENERATE_INTERVAL_S", 900)
    WORKER_RETRY_INTERVAL_S = _int("WORKER_RETRY_INTERVAL_S", 300)
    DELIVERY_MAX_ATTEMPTS = 3

    # /hub compatibility layer for the React dashboard (frontend/docs/api-contract.md).
    # It has NO login: every request acts as HUB_PATIENT_EMAIL. Keep it off unless you
    # are running the dashboard demo, and never expose it publicly.
    HUB_ENABLED = _bool("HUB_ENABLED", False)
    HUB_PATIENT_EMAIL = os.getenv("HUB_PATIENT_EMAIL", "demo.patient@example.com")
    HUB_INFERENCE_URL = os.getenv("HUB_INFERENCE_URL", "http://127.0.0.1:8300").rstrip("/")
    HUB_INFERENCE_API_KEY = os.getenv("HUB_INFERENCE_API_KEY") or None
    HUB_INFERENCE_TIMEOUT_S = float(os.getenv("HUB_INFERENCE_TIMEOUT_S", "90"))
    HUB_ASK_PATIENT_MINUTES = _int("HUB_ASK_PATIENT_MINUTES", 3)
    # Demo only: the medication name can only be one of app/hub/demo_names.DEMO_MEDICATIONS.
    HUB_DEMO_NAMES = _bool("HUB_DEMO_NAMES", False)

    # flask-smorest / OpenAPI
    API_TITLE = "MedCheck Backend API"
    API_VERSION = "v1"
    OPENAPI_VERSION = "3.0.3"
    OPENAPI_URL_PREFIX = "/api"
    OPENAPI_JSON_PATH = "openapi.json"
    OPENAPI_SWAGGER_UI_PATH = "/docs"
    OPENAPI_SWAGGER_UI_URL = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
    API_SPEC_OPTIONS = {
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            }
        },
        "security": [{"bearerAuth": []}],
    }
