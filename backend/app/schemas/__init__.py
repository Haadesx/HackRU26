"""Marshmallow request schemas (validated by flask-smorest, documented in Swagger)."""

import re

from marshmallow import Schema, ValidationError, fields, validate, validates, validates_schema

from app.models.enums import FREQUENCIES, PUSH_PLATFORMS, ROLES, WINDOW_KINDS
from app.utils.time import is_valid_timezone

E164 = re.compile(r"^\+[1-9]\d{6,14}$")


class StrictSchema(Schema):
    class Meta:
        unknown = "raise"


class Strength(fields.Field):
    """Accepts "500 mg" or the inference contract's {"value": 500, "unit": "mg"}."""

    def _deserialize(self, value, attr, data, **kwargs):
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, dict) and "value" in value:
            if value["value"] is not None and not isinstance(value["value"], (int, float)):
                raise ValidationError("strength.value must be a number.")
            return {"value": value["value"], "unit": value.get("unit")}
        raise ValidationError('Use a string like "500 mg" or {"value": 500, "unit": "mg"}.')


class LocalTime(fields.Time):
    """HH:MM (seconds optional)."""

    def __init__(self, **kwargs):
        super().__init__(format="iso", **kwargs)


class UtcDateTime(fields.AwareDateTime):
    def __init__(self, **kwargs):
        super().__init__(format="iso", default_timezone=None, **kwargs)


def _timezone(value):
    if not is_valid_timezone(value):
        raise ValidationError("Must be an IANA timezone such as America/New_York.")


# ---------- auth / me ----------


class RegisterSchema(StrictSchema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=200))
    email = fields.Email(required=True)
    password = fields.String(required=True, load_only=True, validate=validate.Length(min=8, max=200))
    role = fields.String(required=True, validate=validate.OneOf(ROLES))
    timezone = fields.String(load_default="America/New_York", validate=_timezone)
    phone = fields.String(load_default=None, allow_none=True, validate=validate.Regexp(E164, error="Use E.164, e.g. +15551234567."))


class LoginSchema(StrictSchema):
    email = fields.Email(required=True)
    password = fields.String(required=True, load_only=True)


class UpdateMeSchema(StrictSchema):
    name = fields.String(validate=validate.Length(min=1, max=200))
    phone = fields.String(allow_none=True, validate=validate.Regexp(E164, error="Use E.164, e.g. +15551234567."))
    timezone = fields.String(validate=_timezone)
    sms_enabled = fields.Boolean()
    push_enabled = fields.Boolean()


class PushTokenSchema(StrictSchema):
    token = fields.String(required=True, validate=validate.Length(min=10, max=4096))
    platform = fields.String(load_default="web", validate=validate.OneOf(PUSH_PLATFORMS))


# ---------- caregivers ----------


class InviteSchema(StrictSchema):
    email = fields.Email(required=True)


class AcceptInviteSchema(StrictSchema):
    code = fields.String(required=True, validate=validate.Length(min=4, max=16))


class UpdateLinkSchema(StrictSchema):
    receive_alerts = fields.Boolean()
    status = fields.String(validate=validate.OneOf(["revoked"]))


# ---------- prescriptions ----------


class ItemInputSchema(StrictSchema):
    id = fields.UUID()
    name = fields.String(validate=validate.Length(min=1, max=200))
    strength = Strength(allow_none=True)
    dosage_form = fields.String(allow_none=True, validate=validate.Length(max=50))
    dose_quantity = fields.Decimal(allow_none=True, places=3, validate=validate.Range(min=0, min_inclusive=False))
    dose_unit = fields.String(allow_none=True, validate=validate.Length(max=30))
    route = fields.String(allow_none=True, validate=validate.Length(max=50))
    quantity_prescribed = fields.Decimal(allow_none=True, places=3, validate=validate.Range(min=0))
    refills_authorized = fields.Integer(allow_none=True, validate=validate.Range(min=0))
    instructions = fields.String(allow_none=True, validate=validate.Length(max=2000))


class CreatePrescriptionSchema(StrictSchema):
    items = fields.List(fields.Nested(ItemInputSchema), required=True, validate=validate.Length(min=1))
    effective_at = UtcDateTime(allow_none=True)
    source_document_uri = fields.String(allow_none=True, validate=validate.Length(max=2048))

    @validates("items")
    def _names(self, items, **kwargs):
        for i, item in enumerate(items):
            if not item.get("name"):
                raise ValidationError(f"items[{i}].name is required.")


class UpdatePrescriptionSchema(StrictSchema):
    items = fields.List(fields.Nested(ItemInputSchema), load_default=list)
    remove_item_ids = fields.List(fields.UUID(), load_default=list)
    effective_at = UtcDateTime(allow_none=True)
    source_document_uri = fields.String(allow_none=True, validate=validate.Length(max=2048))


class ActivateSchema(StrictSchema):
    initialize_inventory = fields.Boolean(load_default=True)


class ScheduleTimeSchema(StrictSchema):
    dose_window_id = fields.UUID()
    window_kind = fields.String(validate=validate.OneOf(WINDOW_KINDS[:-1]))
    local_time = LocalTime(allow_none=True)

    @validates_schema
    def _window(self, data, **kwargs):
        if not data.get("dose_window_id") and not data.get("window_kind"):
            raise ValidationError("Provide dose_window_id or window_kind.")


class ScheduleSchema(StrictSchema):
    frequency = fields.String(load_default="daily", validate=validate.OneOf(FREQUENCIES))
    start_date = fields.Date(allow_none=True)
    end_date = fields.Date(allow_none=True)
    times = fields.List(fields.Nested(ScheduleTimeSchema), required=True, validate=validate.Length(min=1, max=12))


# ---------- windows ----------


class WindowUpdateSchema(StrictSchema):
    name = fields.String(validate=validate.Length(min=1, max=100))
    target_time = LocalTime(allow_none=True)
    on_time_before_min = fields.Integer(validate=validate.Range(min=0, max=720))
    on_time_after_min = fields.Integer(validate=validate.Range(min=0, max=720))
    missed_after_min = fields.Integer(validate=validate.Range(min=0, max=1440))


class WindowCreateSchema(StrictSchema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    target_time = LocalTime(allow_none=True)
    on_time_before_min = fields.Integer(load_default=30, validate=validate.Range(min=0, max=720))
    on_time_after_min = fields.Integer(load_default=30, validate=validate.Range(min=0, max=720))
    missed_after_min = fields.Integer(load_default=120, validate=validate.Range(min=0, max=1440))


# ---------- doses / scans ----------


class DoseRangeQuerySchema(Schema):
    start = UtcDateTime(data_key="from")
    end = UtcDateTime(data_key="to")
    status = fields.String()


class ScanSchema(StrictSchema):
    event_id = fields.UUID(required=True)
    user_id = fields.UUID(required=True)
    drug_name = fields.String(required=True, validate=validate.Length(min=1, max=200))
    strength = Strength(allow_none=True, load_default=None)
    quantity = fields.Decimal(required=True, places=3, validate=validate.Range(min=0, min_inclusive=False))
    timestamp = UtcDateTime(required=True)


class ConfirmSchema(StrictSchema):
    observation_event_id = fields.UUID(allow_none=True, load_default=None)
    quantity_taken = fields.Decimal(allow_none=True, load_default=None, places=3, validate=validate.Range(min=0, min_inclusive=False))


# ---------- inventory / refills ----------


class InventoryUpdateSchema(StrictSchema):
    quantity_remaining = fields.Decimal(required=True, places=3, validate=validate.Range(min=0))
    quantity_unit = fields.String(validate=validate.Length(min=1, max=30))
    note = fields.String(allow_none=True, validate=validate.Length(max=500))


class RefillCreateSchema(StrictSchema):
    prescription_item_id = fields.UUID(required=True)
    appointment_at = UtcDateTime(allow_none=True)
    pharmacy_or_provider = fields.String(allow_none=True, validate=validate.Length(max=300))


class RefillUpdateSchema(StrictSchema):
    appointment_at = UtcDateTime(allow_none=True)
    pharmacy_or_provider = fields.String(allow_none=True, validate=validate.Length(max=300))


class RefillFulfillSchema(StrictSchema):
    quantity_added = fields.Decimal(required=True, places=3, validate=validate.Range(min=0, min_inclusive=False))
    fulfilled_at = UtcDateTime(allow_none=True)


# ---------- misc ----------


class SearchQuerySchema(Schema):
    q = fields.String(required=True, validate=validate.Length(min=2, max=200))


class NotificationsQuerySchema(Schema):
    unread_only = fields.Boolean(load_default=False)
    limit = fields.Integer(load_default=50, validate=validate.Range(min=1, max=200))


class AdherenceQuerySchema(Schema):
    start = UtcDateTime(data_key="from")
    end = UtcDateTime(data_key="to")
    granularity = fields.String(load_default="day", validate=validate.OneOf(["day", "week"]))
    medication_id = fields.UUID()
