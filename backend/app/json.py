"""JSON provider: ISO-8601 UTC timestamps with Z, HH:MM local times, UUIDs and Decimals as JSON-native."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from flask.json.provider import DefaultJSONProvider

from app.utils.time import iso_utc


def to_number(value: Decimal | None):
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


class ApiJSONProvider(DefaultJSONProvider):
    sort_keys = False

    @staticmethod
    def default(o):
        if isinstance(o, datetime):
            return iso_utc(o)
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, time):
            return o.strftime("%H:%M")
        if isinstance(o, uuid.UUID):
            return str(o)
        if isinstance(o, Decimal):
            return to_number(o)
        return DefaultJSONProvider.default(o)
