"""Uniform error envelope: {"error": {"code", "message", "details"}}."""

from flask import jsonify
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def bad_request(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(400, code, message, details)


def forbidden(message: str = "You do not have access to this resource.") -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def not_found(what: str = "Resource") -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found.")


def conflict(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(409, code, message, details)


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_error_handlers(app) -> None:
    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return jsonify(error_body(exc.code, exc.message, exc.details)), exc.status

    def _http_error(exc: HTTPException):
        # flask-smorest/webargs validation failures arrive as 422 with messages in exc.data.
        if exc.code == 422:
            messages = getattr(exc, "data", {}).get("messages", {})
            return (
                jsonify(error_body("VALIDATION_ERROR", "Request validation failed.", messages)),
                400,
            )
        code = (exc.name or "HTTP_ERROR").upper().replace(" ", "_")
        return jsonify(error_body(code, exc.description or exc.name)), exc.code or 500

    # Registered after flask-smorest so it replaces smorest's default handler.
    app.register_error_handler(HTTPException, _http_error)

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        app.logger.exception("Unhandled error")
        return jsonify(error_body("INTERNAL_ERROR", "Unexpected server error.")), 500
