"""Texts to the dashboard's caregiver contacts (settings.caregivers). Skipped when Twilio isn't configured."""

import logging
import re

from app.services.channels import ChannelError
from app.services.channels import sms as sms_channel

log = logging.getLogger(__name__)


def to_e164(phone: str) -> str | None:
    """'(732) 555-0187' -> '+17325550187'. Assumes US numbers when no country code is given."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if phone.strip().startswith("+") and 8 <= len(digits) <= 15:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


def text_contacts(settings: dict, message: str, scopes=("all",)) -> int:
    """Send `message` to contacts whose scope is in `scopes`. Returns the number sent."""
    if not sms_channel.configured():
        return 0
    sent = 0
    for contact in settings.get("caregivers") or []:
        if contact.get("scope", "all") not in scopes:
            continue
        number = to_e164(contact.get("phone", ""))
        if not number:
            continue
        try:
            sms_channel.send(number, message)
            sent += 1
        except ChannelError as exc:
            log.warning("SMS to contact %s failed: %s", contact.get("id"), exc)
    return sent
