"""hub scan dosage form + dose unit (read from inference, never assumed)

Revision ID: 0005_hub_scan_form
Revises: 0003_hub_compat
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_hub_scan_form"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("hub_scans") as batch_op:
        batch_op.add_column(sa.Column("dosage_form", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("dose_unit", sa.String(length=30), nullable=True))


def downgrade():
    with op.batch_alter_table("hub_scans") as batch_op:
        batch_op.drop_column("dose_unit")
        batch_op.drop_column("dosage_form")
