"""
RSS Keyword Monitor – main entrypoint.
"""
import os
from apscheduler.schedulers.background import BackgroundScheduler
from app import create_app, poll_feeds, cleanup_old_items
from app.db import SessionLocal

app = create_app()

scheduler = BackgroundScheduler(daemon=True)


def scheduled_poll():
    with app.app_context():
        try:
            poll_feeds()
        except Exception as e:
            print(f"[SCHED] poll error: {e}", flush=True)


def scheduled_cleanup():
    with app.app_context():
        try:
            cleanup_old_items()
        except Exception as e:
            print(f"[SCHED] cleanup error: {e}", flush=True)


scheduler.add_job(scheduled_poll, "interval", minutes=1, id="rss_poll", replace_existing=True)
scheduler.add_job(scheduled_cleanup, "interval", minutes=10, id="rss_cleanup", replace_existing=True)
scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False, use_reloader=False)
