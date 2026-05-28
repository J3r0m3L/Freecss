"""Flask + SocketIO application factory (DESIGN.md §4).

Single process: Flask serves the API and (in prod) the built React SPA; SocketIO
pushes ticks/alerts/news; APScheduler runs background jobs in the same process.
"""
from __future__ import annotations

import logging

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO

from server.api import register_blueprints
from server.config import config
from server.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("deleveraging_watch")

# threading async mode keeps Phase 0 dependency-free (no eventlet/gevent native
# build). Fine for a single-user laptop app; revisit if WS throughput matters.
socketio = SocketIO(async_mode="threading", cors_allowed_origins="*")


def create_app(*, start_background: bool = True) -> Flask:
    app = Flask(__name__, static_folder=None)
    # In dev the React app runs on Vite :5173 and calls the API cross-origin.
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    init_db()
    register_blueprints(app)
    socketio.init_app(app)

    _register_spa(app)

    if start_background:
        from server.feed import feed
        from server import scheduler

        feed.start(socketio)
        scheduler.start()

    log.info("app ready (adapter=%s, notifier=%s, db=%s)",
             config.data_adapter, config.notifier, config.db_path)
    return app


def _register_spa(app: Flask) -> None:
    """Serve the built SPA from web/dist when present; otherwise a dev hint."""
    dist = config.web_dist

    @app.get("/")
    @app.get("/<path:path>")
    def spa(path: str = ""):
        if path.startswith("api/"):
            return jsonify({"error": "not found"}), 404
        if dist.exists():
            target = dist / path
            if path and target.is_file():
                return send_from_directory(dist, path)
            return send_from_directory(dist, "index.html")
        return jsonify({
            "app": "deleveraging-watch",
            "status": "backend running (Phase 0)",
            "frontend": "not built — run `npm install && npm run dev` in web/, "
                        "or `npm run build` to serve from web/dist",
            "api": ["/api/watchlist", "/api/health", "/api/settings",
                    "/api/instrument/<symbol>"],
        })


# Convenience for `flask --app server.app run` style invocation.
app = None  # populated by create_app when run via __main__
