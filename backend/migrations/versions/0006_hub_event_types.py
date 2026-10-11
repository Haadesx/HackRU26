"""hub_events.type: allow 'skipped' and 'missed' (doses the caregiver should hear about)

Revision ID: 0006_hub_event_types
Revises: 0005_hub_dose_method_scan
"""

from alembic import op

revision = "0006_hub_event_types"
down_revision = "0005_hub_dose_method_scan"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(op.f("ck_hub_events_type"), "hub_events", type_="check")
    op.create_check_constraint(
        op.f("ck_hub_events_type"),
        "hub_events",
        "type IN ('wrong_bottle', 'double_dose', 'skipped', 'missed')",
    )


def downgrade():
    op.execute("DELETE FROM hub_events WHERE type IN ('skipped', 'missed')")
    op.drop_constraint(op.f("ck_hub_events_type"), "hub_events", type_="check")
    op.create_check_constraint(op.f("ck_hub_events_type"), "hub_events", "type IN ('wrong_bottle', 'double_dose')")
