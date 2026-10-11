"""hub_dose_refs.method: allow 'scan' (dose confirmed after a Track-tab dose scan)

Revision ID: 0005_hub_dose_method_scan
Revises: 0004_hub_scan_form
"""

from alembic import op

revision = "0005_hub_dose_method_scan"
down_revision = "0004_hub_scan_form"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(op.f("ck_hub_dose_refs_method"), "hub_dose_refs", type_="check")
    op.create_check_constraint(
        op.f("ck_hub_dose_refs_method"),
        "hub_dose_refs",
        "method IS NULL OR method IN ('voice', 'button', 'dashboard', 'scan')",
    )


def downgrade():
    op.execute("UPDATE hub_dose_refs SET method = 'button' WHERE method = 'scan'")
    op.drop_constraint(op.f("ck_hub_dose_refs_method"), "hub_dose_refs", type_="check")
    op.create_check_constraint(
        op.f("ck_hub_dose_refs_method"),
        "hub_dose_refs",
        "method IS NULL OR method IN ('voice', 'button', 'dashboard')",
    )
