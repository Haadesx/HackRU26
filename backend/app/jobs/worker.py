"""Background worker: python -m app.jobs.worker

Run exactly as a separate process. Never start the scheduler inside gunicorn workers.
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app import create_app
from app.extensions import db
from app.jobs import tasks

log = logging.getLogger("medcheck.worker")


def _wrap(app, fn):
    def run():
        with app.app_context():
            try:
                result = fn()
                if result:
                    log.info("%s: %s", fn.__name__, result)
            except Exception:
                db.session.rollback()
                log.exception("%s failed", fn.__name__)
            finally:
                db.session.remove()

    run.__name__ = fn.__name__
    return run


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = create_app()
    cfg = app.config
    scheduler = BlockingScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1})
    jobs = [
        (tasks.generate_dose_events, cfg["WORKER_GENERATE_INTERVAL_S"]),
        (tasks.mark_missed_doses, cfg["WORKER_MISSED_INTERVAL_S"]),
        (tasks.dispatch_due_reminders, cfg["WORKER_DISPATCH_INTERVAL_S"]),
        (tasks.retry_failed_deliveries, cfg["WORKER_RETRY_INTERVAL_S"]),
    ]
    for fn, seconds in jobs:
        job = _wrap(app, fn)
        scheduler.add_job(job, "interval", seconds=seconds, id=fn.__name__, name=fn.__name__)
        job()  # run once at startup
    log.info("Worker started: %s", ", ".join(f"{fn.__name__}/{s}s" for fn, s in jobs))
    scheduler.start()


if __name__ == "__main__":
    main()
