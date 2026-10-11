"""Firebase Cloud Messaging web push for the React app.

iOS push is not supported (no paid Apple Developer account). Disabled unless
FIREBASE_CREDENTIALS_JSON is set to a service-account file path or raw JSON.
"""

import json
import os

from flask import current_app

from app.services.channels import ChannelError, InvalidRecipient

_app = None


def configured() -> bool:
    return bool(current_app.config.get("FIREBASE_CREDENTIALS_JSON"))


def _get_app():
    global _app
    if _app is None:
        import firebase_admin
        from firebase_admin import credentials

        raw = current_app.config["FIREBASE_CREDENTIALS_JSON"]
        cred_source = raw if os.path.isfile(raw) else json.loads(raw)
        _app = firebase_admin.initialize_app(credentials.Certificate(cred_source), name="medcheck")
    return _app


def send(token: str, title: str, body: str, data: dict[str, str] | None = None) -> str:
    from firebase_admin import exceptions, messaging

    message = messaging.Message(
        token=token,
        data={k: str(v) for k, v in (data or {}).items()},
        webpush=messaging.WebpushConfig(notification=messaging.WebpushNotification(title=title, body=body)),
    )
    try:
        return messaging.send(message, app=_get_app())
    except (messaging.UnregisteredError, messaging.SenderIdMismatchError) as exc:
        raise InvalidRecipient(str(exc)) from exc
    except exceptions.InvalidArgumentError as exc:
        raise InvalidRecipient(str(exc)) from exc
    except Exception as exc:
        raise ChannelError(str(exc)) from exc
