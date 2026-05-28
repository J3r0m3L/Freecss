"""Entry point: `python -m server` (see DESIGN.md §14 launchd supervision)."""
from __future__ import annotations

import logging

from server.app import create_app, socketio
from server.config import config

log = logging.getLogger("deleveraging_watch")


def main() -> None:
    app = create_app(start_background=True)
    log.info("serving on http://%s:%d", config.host, config.port)
    try:
        socketio.run(app, host=config.host, port=config.port,
                     allow_unsafe_werkzeug=True)
    finally:
        from server import scheduler
        from server.feed import feed

        scheduler.stop()
        feed.stop()


if __name__ == "__main__":
    main()
