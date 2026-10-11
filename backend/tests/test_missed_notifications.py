import uuid
from datetime import timedelta

from conftest import T0, set_now
from sqlalchemy import func, select

from app.extensions import db
from app.jobs import tasks
from app.models import DoseOutcome, NotificationDelivery, Reminder


def _setup(api):
    p = api.register("patient", name="Ada Patient")
    c = api.register("caregiver", name="Cara Giver")
    api.link_caregiver(p, c)
    api.active_metformin(p)
    return p, c


def test_missed_dose_alerts_caregiver_and_patient_in_app(api, ctx):
    p, c = _setup(api)
    breakfast = api.doses(p, p["id"])[0]
    at = T0 + timedelta(hours=3, minutes=1)  # 10:01 local, past missed_after (10:00)
    set_now(at)
    assert tasks.mark_missed_doses(at) == 1
    assert tasks.mark_missed_doses(at) == 0  # idempotent
    dose = api.get(p, f"/doses/{breakfast['id']}").get_json()
    assert dose["status"] == "missed"
    assert db.session.scalar(select(DoseOutcome.status)) == "missed"

    sent = tasks.dispatch_due_reminders(at)
    assert sent >= 2
    inbox = api.get(c, "/notifications").get_json()
    kinds = [n["kind"] for n in inbox["notifications"]]
    assert "missed_dose_alert" in kinds and inbox["unread_count"] >= 1
    alert = next(n for n in inbox["notifications"] if n["kind"] == "missed_dose_alert")
    assert alert["title"] == "Ada Patient missed a dose"
    assert "08:00 dose of Metformin 500 mg" in alert["body"]
    patient_inbox = api.get(p, "/notifications").get_json()
    assert any(n["kind"] == "missed_dose_alert" for n in patient_inbox["notifications"])

    # Patient alert is in-app only; no push/sms rows even if channels existed
    patient_alert = db.session.scalar(
        select(Reminder).where(Reminder.kind == "missed_dose_alert", Reminder.recipient_user_id == uuid.UUID(p["id"]))
    )
    assert [d.channel for d in patient_alert.deliveries] == ["in_app"]

    r = api.post(c, f"/notifications/{alert['id']}/read")
    assert r.status_code == 200 and r.get_json()["read"] is True
    # Someone else can't read your notification
    assert api.post(p, f"/notifications/{alert['id']}/read").status_code == 404


def test_confirm_after_missed_becomes_late_and_resolves(api, ctx):
    p, c = _setup(api)
    breakfast = api.doses(p, p["id"])[0]
    at = T0 + timedelta(hours=4)
    set_now(at)
    tasks.mark_missed_doses(at)
    tasks.dispatch_due_reminders(at)

    set_now(at + timedelta(minutes=30))  # 11:30 local, before the 19:00 confirm_deadline
    r = api.post(p, f"/doses/{breakfast['id']}/confirm", {})
    assert r.status_code == 200, r.get_json()
    dose = r.get_json()["dose"]
    assert dose["status"] == "taken_late" and dose["confirmed_after_missed"] is True
    # Outcome replaced, not duplicated
    rows = db.session.execute(select(DoseOutcome.status)).scalars().all()
    assert rows == ["taken_late"]
    resolved = db.session.scalars(select(Reminder).where(Reminder.kind == "missed_dose_resolved")).all()
    assert [str(r.recipient_user_id) for r in resolved] == [c["id"]]
    assert "Ada Patient confirmed taking Metformin 500 mg" in resolved[0].body


def test_cannot_confirm_after_deadline(api, ctx):
    p, _ = _setup(api)
    breakfast = api.doses(p, p["id"])[0]
    at = T0 + timedelta(hours=12, minutes=1)  # 19:01 local, past confirm_deadline (19:00)
    set_now(at)
    tasks.mark_missed_doses(at)
    r = api.post(p, f"/doses/{breakfast['id']}/confirm", {})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "CONFIRM_WINDOW_CLOSED"


def test_dispatch_sends_due_reminder_and_skips_taken_doses(api, ctx):
    p, _ = _setup(api)
    doses = api.doses(p, p["id"])
    at = T0 + timedelta(hours=1)  # 08:00 local: breakfast dose_due is due
    set_now(at)
    assert tasks.dispatch_due_reminders(at) == 1
    due = db.session.scalar(select(Reminder).where(Reminder.kind == "dose_due", Reminder.status == "sent"))
    assert due.title == "Time for Metformin 500 mg"
    assert due.body == "Take 1 tablet of Metformin 500 mg (Breakfast dose, 08:00)."
    # Taking the dose cancels the follow-up, so the dispatcher doesn't send it.
    api.post(p, f"/doses/{doses[0]['id']}/confirm", {})
    later = T0 + timedelta(hours=2, minutes=1)
    set_now(later)
    assert tasks.dispatch_due_reminders(later) == 0
    followup = db.session.scalar(
        select(Reminder).where(Reminder.kind == "dose_followup", Reminder.dose_event_id == uuid.UUID(doses[0]["id"]))
    )
    assert followup.status == "cancelled"


def test_sms_and_push_fan_out_when_configured(api, app, ctx, monkeypatch):
    from app.services.channels import InvalidRecipient
    from app.services.channels import push as push_channel
    from app.services.channels import sms as sms_channel

    sent_sms, sent_push = [], []
    monkeypatch.setattr(sms_channel, "configured", lambda: True)
    monkeypatch.setattr(sms_channel, "send", lambda to, body: sent_sms.append((to, body)) or "SM1")
    monkeypatch.setattr(push_channel, "configured", lambda: True)

    def fake_push(token, title, body, data=None):
        if token.startswith("dead"):
            raise InvalidRecipient("unregistered")
        sent_push.append(token)
        return "msg-1"

    monkeypatch.setattr(push_channel, "send", fake_push)

    p = api.register("patient", phone="+15555550123")
    api.post(p, "/me/push-tokens", {"token": "good-web-token-123", "platform": "web"})
    api.post(p, "/me/push-tokens", {"token": "dead-web-token-456", "platform": "web"})
    assert api.post(p, "/me/push-tokens", {"token": "ios-token-123456", "platform": "ios"}).status_code == 400
    api.active_metformin(p)
    at = T0 + timedelta(hours=1)
    set_now(at)
    tasks.dispatch_due_reminders(at)
    assert sent_sms == [("+15555550123", "Time for Metformin 500 mg: Take 1 tablet of Metformin 500 mg (Breakfast dose, 08:00).")]
    assert sent_push == ["good-web-token-123"]
    channels = db.session.execute(select(NotificationDelivery.channel, NotificationDelivery.status)).all()
    assert sorted(channels) == sorted([("in_app", "sent"), ("sms", "sent"), ("push", "sent"), ("push", "failed")])
    from app.models import PushToken

    assert db.session.scalar(select(func.count()).select_from(PushToken)) == 1  # dead token removed


def test_sms_failure_is_retried(api, ctx, monkeypatch):
    from app.services.channels import ChannelError
    from app.services.channels import sms as sms_channel

    calls = {"n": 0}

    def flaky(to, body):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ChannelError("timeout")
        return "SM2"

    monkeypatch.setattr(sms_channel, "configured", lambda: True)
    monkeypatch.setattr(sms_channel, "send", flaky)
    p = api.register("patient", phone="+15555550123")
    api.active_metformin(p)
    at = T0 + timedelta(hours=1)
    set_now(at)
    tasks.dispatch_due_reminders(at)
    sms = db.session.scalar(select(NotificationDelivery).where(NotificationDelivery.channel == "sms"))
    assert sms.status == "failed" and sms.attempts == 1
    assert tasks.retry_failed_deliveries(at) == 1
    db.session.refresh(sms)
    assert sms.status == "sent" and sms.attempts == 2
