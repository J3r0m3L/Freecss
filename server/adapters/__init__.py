"""Data adapters. The adapter is the only thing that changes per asset class
(DESIGN.md §13). Phase 0 ships a stub; Phase 1 adds the Massive WS/REST adapter."""
from __future__ import annotations

from server.adapters.base import Bar, DataAdapter
from server.adapters.stub import StubAdapter
from server.config import config


def make_adapter(name: str | None = None) -> DataAdapter:
    name = name or config.data_adapter
    if name == "stub":
        return StubAdapter()
    # Phase 1: `massive` → MassiveAdapter (Polygon WS endpoints, post-rebrand).
    raise ValueError(f"unknown data adapter {name!r} (Phase 0 supports 'stub' only)")


__all__ = ["Bar", "DataAdapter", "StubAdapter", "make_adapter"]
