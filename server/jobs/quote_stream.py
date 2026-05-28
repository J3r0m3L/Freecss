"""quote_stream_supervisor (§7.3) — keeps the live feed healthy.

For the Massive WS adapter, checks connection health (auth + recent messages);
the adapter reconnects internally with backoff, so this is a heartbeat that
records liveness to job_run. A no-op for the stub adapter (always healthy)."""
from __future__ import annotations

from server.feed import feed
from server.jobs import record_run


def run() -> None:
    with record_run("quote_stream_supervisor") as result:
        adapter = feed.adapter
        healthy = getattr(adapter, "is_healthy", lambda: True)()
        result["rows"] = 1 if healthy else 0
        if not healthy:
            raise RuntimeError(f"{adapter.name} feed unhealthy (no recent messages)")
