"""Deleveraging Watch — single-process Flask + SocketIO + APScheduler backend.

See DESIGN.md §4 (architecture) and §15 (repo layout). Phase 0 wires the
skeleton: app factory, SQLite schema, watchlist CRUD, a stub data adapter,
and a console notifier. Later phases plug real adapters into the same seams.
"""

__version__ = "0.1.0"
