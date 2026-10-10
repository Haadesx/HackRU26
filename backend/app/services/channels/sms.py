"""Twilio SMS. Disabled (configured() is False) unless all three TWILIO_* variables are set."""

from flask import current_app

from app.services.channels import ChannelError, InvalidRecipient

_client = None


def configured() -> bool:
    cfg = current_app.config
    return bool(cfg.get("TWILIO_ACCOUNT_SID") and cfg.get("TWILIO_AUTH_TOKEN") and cfg.get("TWILIO_FROM_NUMBER"))


def _get_client():
    global _client
    if _client is None:
        from twilio.rest import Client

        cfg = current_app.config
        _client = Client(cfg["TWILIO_ACCOUNT_SID"], cfg["TWILIO_AUTH_TOKEN"])
    return _client


def send(to_number: str, body: str) -> str:
    """Send an SMS. Returns the Twilio message SID."""
    from twilio.base.exceptions import TwilioRestException

    try:
        msg = _get_client().messages.create(to=to_number, from_=current_app.config["TWILIO_FROM_NUMBER"], body=body)
    except TwilioRestException as exc:
        # 21211 invalid 'To' number, 21610 recipient opted out, 21614 not a mobile number.
        if exc.code in (21211, 21610, 21614):
            raise InvalidRecipient(f"Twilio {exc.code}: {exc.msg}") from exc
        raise ChannelError(f"Twilio {exc.code}: {exc.msg}") from exc
    except Exception as exc:  # network errors etc.
        raise ChannelError(str(exc)) from exc
    return msg.sid
