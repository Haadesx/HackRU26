"""TimescaleDB: hypertables and the daily_adherence continuous aggregate

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute(
        "SELECT create_hypertable('vision_observations', by_range('observed_at', INTERVAL '7 days'), if_not_exists => TRUE)"
    )
    op.execute(
        "SELECT create_hypertable('dose_outcomes', by_range('scheduled_at', INTERVAL '30 days'), if_not_exists => TRUE)"
    )
    # Continuous aggregates cannot be created inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS daily_adherence
            WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
            SELECT time_bucket(INTERVAL '1 day', scheduled_at) AS day,
                   patient_id,
                   medication_id,
                   count(*) FILTER (WHERE status = 'taken_on_time') AS taken_on_time,
                   count(*) FILTER (WHERE status = 'taken_late')    AS taken_late,
                   count(*) FILTER (WHERE status = 'missed')        AS missed,
                   count(*) FILTER (WHERE status = 'skipped')       AS skipped,
                   count(*) FILTER (WHERE dose_mismatch)            AS dose_mismatch,
                   count(*)                                         AS total
            FROM dose_outcomes
            GROUP BY day, patient_id, medication_id
            WITH NO DATA
            """
        )
        op.execute(
            """
            SELECT add_continuous_aggregate_policy('daily_adherence',
                start_offset => INTERVAL '60 days',
                end_offset => INTERVAL '1 hour',
                schedule_interval => INTERVAL '1 hour',
                if_not_exists => TRUE)
            """
        )
    # On-time rate view over the aggregate (rate = on_time / (on_time + late + missed); skipped excluded).
    op.execute(
        """
        CREATE OR REPLACE VIEW daily_adherence_rates AS
        SELECT *,
               CASE WHEN (taken_on_time + taken_late + missed) > 0
                    THEN round(taken_on_time::numeric / (taken_on_time + taken_late + missed), 3)
               END AS on_time_rate
        FROM daily_adherence
        """
    )


def downgrade():
    op.execute("DROP VIEW IF EXISTS daily_adherence_rates")
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS daily_adherence")
    # Hypertables are dropped with their tables in 0001's downgrade.
