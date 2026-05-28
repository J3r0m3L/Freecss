"""REST API blueprints (DESIGN.md §7.1), all mounted under /api."""
from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    from server.api.alerts import bp as alerts_bp
    from server.api.earnings import bp as earnings_bp
    from server.api.health import bp as health_bp
    from server.api.instrument import bp as instrument_bp
    from server.api.liquidity import bp as liquidity_bp
    from server.api.news import bp as news_bp
    from server.api.notes import bp as notes_bp
    from server.api.settings import bp as settings_bp
    from server.api.social import bp as social_bp
    from server.api.usage import bp as usage_bp
    from server.api.watchlist import bp as watchlist_bp

    app.register_blueprint(watchlist_bp)
    app.register_blueprint(instrument_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(social_bp)
    app.register_blueprint(earnings_bp)
    app.register_blueprint(usage_bp)
    app.register_blueprint(liquidity_bp)
