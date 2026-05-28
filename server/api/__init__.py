"""REST API blueprints (DESIGN.md §7.1), all mounted under /api."""
from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    from server.api.alerts import bp as alerts_bp
    from server.api.health import bp as health_bp
    from server.api.instrument import bp as instrument_bp
    from server.api.settings import bp as settings_bp
    from server.api.watchlist import bp as watchlist_bp

    app.register_blueprint(watchlist_bp)
    app.register_blueprint(instrument_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(alerts_bp)
