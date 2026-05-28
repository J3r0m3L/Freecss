"""Runtime configuration, sourced from environment (.env via python-dotenv).

Credentials are read-only here and surfaced to the UI only as present/absent
(DESIGN.md §11.E) — never echoed back in API responses.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repo root (parent of the `server` package) if present.
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")


def _present(*names: str) -> bool:
    """True if any of the named env vars is set and non-empty."""
    return any(os.environ.get(n) for n in names)


@dataclass(frozen=True)
class Config:
    repo_root: Path = _REPO_ROOT
    db_path: Path = field(
        default_factory=lambda: (_REPO_ROOT / os.environ.get("DW_DB_PATH", "deleveraging_watch.db"))
    )
    host: str = field(default_factory=lambda: os.environ.get("DW_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("DW_PORT", "5000")))

    data_adapter: str = field(default_factory=lambda: os.environ.get("DW_DATA_ADAPTER", "stub"))
    notifier: str = field(default_factory=lambda: os.environ.get("DW_NOTIFIER", "console"))

    @property
    def web_dist(self) -> Path:
        """Built frontend (served by Flask in prod). Absent in dev — Vite serves :5173."""
        return self.repo_root / "web" / "dist"

    def credential_status(self) -> dict[str, bool]:
        """Presence/absence map for the Settings credentials panel (§11.E)."""
        return {
            # MASSIVE_API_KEY with legacy POLYGON_API_KEY alias (§3.1).
            "MASSIVE_API_KEY": _present("MASSIVE_API_KEY", "POLYGON_API_KEY"),
            "FINNHUB_API_KEY": _present("FINNHUB_API_KEY"),
            "ANTHROPIC_API_KEY": _present("ANTHROPIC_API_KEY"),
            "X_BEARER_TOKEN": _present("X_BEARER_TOKEN"),
            "PUSHOVER_USER_KEY": _present("PUSHOVER_USER_KEY"),
            "PUSHOVER_APP_TOKEN_CRITICAL": _present("PUSHOVER_APP_TOKEN_CRITICAL"),
            "PUSHOVER_APP_TOKEN_WARN": _present("PUSHOVER_APP_TOKEN_WARN"),
            "PUSHOVER_APP_TOKEN_NEWS": _present("PUSHOVER_APP_TOKEN_NEWS"),
            "PUSHOVER_APP_TOKEN_INFO": _present("PUSHOVER_APP_TOKEN_INFO"),
        }


config = Config()
