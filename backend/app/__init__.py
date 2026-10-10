"""Flask application factory."""

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify  # noqa: E402

from app.config import Config  # noqa: E402
from app.errors import error_body, register_error_handlers  # noqa: E402
from app.extensions import api as smorest_api, cors, db, jwt, migrate  # noqa: E402
from app.json import ApiJSONProvider  # noqa: E402


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.json_provider_class = ApiJSONProvider
    app.json = ApiJSONProvider(app)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    if not app.config.get("JWT_SECRET_KEY"):
        raise RuntimeError("JWT_SECRET_KEY is not set. Copy .env.example to .env and set it.")

    from app import models  # noqa: F401  (register models with SQLAlchemy metadata)

    db.init_app(app)
    migrate.init_app(app, db, directory=_migrations_dir())
    jwt.init_app(app)
    cors.init_app(
        app,
        resources={
            r"/api/*": {"origins": app.config["CORS_ORIGINS"]},
            r"/hub/*": {"origins": app.config["CORS_ORIGINS"]},
        },
        allow_headers=["Authorization", "Content-Type"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    smorest_api.init_app(app)

    from app.api import register_blueprints

    register_blueprints(smorest_api)
    _register_jwt_handlers()
    register_error_handlers(app)
    if app.config["HUB_ENABLED"]:
        from app.hub import hub_bp

        app.register_blueprint(hub_bp, url_prefix="/hub")
        app.logger.warning("HUB_ENABLED: /hub has no login and acts as %s. Demo use only.", app.config["HUB_PATIENT_EMAIL"])
    return app


def _migrations_dir() -> str:
    import os

    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")


def _register_jwt_handlers() -> None:
    def _unauthorized(message: str):
        return jsonify(error_body("UNAUTHORIZED", message)), 401

    @jwt.unauthorized_loader
    def _missing(reason):
        return _unauthorized("Missing or malformed Authorization header.")

    @jwt.invalid_token_loader
    def _invalid(reason):
        return _unauthorized("Invalid token.")

    @jwt.expired_token_loader
    def _expired(header, payload):
        return _unauthorized("Token has expired.")

    @jwt.revoked_token_loader
    def _revoked(header, payload):
        return _unauthorized("Token has been revoked.")

    @jwt.needs_fresh_token_loader
    def _fresh(header, payload):
        return _unauthorized("Fresh token required.")

    @jwt.user_lookup_error_loader
    def _lookup_error(header, payload):
        return _unauthorized("User no longer exists.")

    @jwt.user_lookup_loader
    def _lookup(header, payload):
        import uuid

        from app.models import User

        try:
            return db.session.get(User, uuid.UUID(payload["sub"]))
        except (ValueError, KeyError):
            return None
