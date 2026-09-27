"""Run the single APScheduler process separately from the web server."""

from __future__ import annotations

import threading

from inkdisplay.app import create_app
from inkdisplay.infrastructure.scheduler.apscheduler_adapter import APSchedulerAdapter


def main() -> None:
    app = create_app()
    scheduler: APSchedulerAdapter = app.extensions["inkdisplay.scheduler"]
    if not scheduler.start():
        raise SystemExit("Un altro processo MyInky possiede già lo scheduler.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
