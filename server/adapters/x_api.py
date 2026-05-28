"""X API adapter (DESIGN.md §10.3).

Two endpoints in v1:
- User: Read   — GET /2/users/by/username/{handle}      → resolve handle → external_id
                 (one-shot per row, billed once at $0.01)
- User Tweets  — GET /2/users/{external_id}/tweets       → only-new posts since `since_id`
                 (per-post-read billing at $0.005/post returned)

Each billable call writes one api_cost_event row so /api/usage stays truthful.

Stub fallback fires when X_BEARER_TOKEN is missing, the SDK is unreachable, or
the HTTP layer throws — tests run entirely against the stub via monkeypatch.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from server.db import execute

log = logging.getLogger("deleveraging_watch.adapters.x_api")

_USERS_BASE = "https://api.twitter.com/2/users"
_TIMEOUT_S = 10
_BILL_PER_TWEET = 0.005
_BILL_PER_USER_READ = 0.010


def _token() -> str:
    return os.environ.get("X_BEARER_TOKEN", "")


def _record_cost(source: str, units: int, unit_cost: float, *,
                 ref_endpoint: str, ref_job_run: str | None = None) -> None:
    if units <= 0:
        return
    execute(
        "INSERT INTO api_cost_event(source, units, unit_cost_usd, cost_usd, "
        "ref_endpoint, ref_job_run) VALUES(?,?,?,?,?,?)",
        (source, units, unit_cost, units * unit_cost, ref_endpoint, ref_job_run),
    )


@dataclass(frozen=True)
class TweetItem:
    external_post_id: str
    posted_at: datetime
    body: str
    url: str


def resolve_user_id(handle: str) -> str | None:
    """One-shot lookup. Bills $0.01. Returns None on failure."""
    h = handle.lstrip("@")
    token = _token()
    if not token:
        log.debug("X_BEARER_TOKEN missing; stubbing external_id for @%s", h)
        return f"stub-{h}"
    try:
        resp = requests.get(
            f"{_USERS_BASE}/by/username/{h}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or {}
        _record_cost("x:user_read", 1, _BILL_PER_USER_READ,
                     ref_endpoint=f"GET /2/users/by/username/{h}")
        return data.get("id")
    except Exception as exc:  # noqa: BLE001
        log.warning("X user_read failed for @%s: %s", h, exc)
        return None


def fetch_tweets(handle: str, external_id: str, *, since_id: str | None,
                 ref_job_run: str | None = None) -> list[TweetItem]:
    """Per-post-billed. Empty response = $0. Returns posts ordered oldest-first.

    Stubs fire 0 or 1 deterministic tweets per call when X_BEARER_TOKEN is
    missing — 1 if `since_id` is None (first poll), 0 otherwise (subsequent
    polls return nothing, mirroring the "no new tweets" path).
    """
    token = _token()
    if not token:
        if since_id is None:
            tw = _stub_tweet(handle)
            return [tw]
        return []

    params = {"max_results": 10, "tweet.fields": "created_at"}
    if since_id:
        params["since_id"] = since_id

    try:
        resp = requests.get(
            f"{_USERS_BASE}/{external_id}/tweets",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("X fetch_tweets failed for @%s: %s", handle, exc)
        return []

    out: list[TweetItem] = []
    for row in data:
        try:
            out.append(TweetItem(
                external_post_id=str(row.get("id")),
                posted_at=_parse_ts(row.get("created_at") or ""),
                body=row.get("text") or "",
                url=f"https://x.com/{handle.lstrip('@')}/status/{row.get('id')}",
            ))
        except Exception:  # noqa: BLE001
            log.exception("could not parse X tweet for @%s", handle)
    out.sort(key=lambda t: t.posted_at)

    _record_cost("x:tweets", len(out), _BILL_PER_TWEET,
                 ref_endpoint=f"GET /2/users/{external_id}/tweets",
                 ref_job_run=ref_job_run)
    return out


def _parse_ts(s: str) -> datetime:
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


def _stub_tweet(handle: str) -> TweetItem:
    h = handle.lstrip("@")
    now = datetime.now(timezone.utc)
    return TweetItem(
        external_post_id=f"stub-{h}-{int(now.timestamp())}",
        posted_at=now,
        body=f"[stub] @{h} commenting on $SPY market action; tariffs in focus.",
        url=f"https://x.com/{h}/status/stub-{int(now.timestamp())}",
    )
