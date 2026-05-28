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
    if name == "massive":
        from server.adapters.massive import MassiveAdapter

        return MassiveAdapter()
    raise ValueError(f"unknown data adapter {name!r} (supported: 'stub', 'massive')")


__all__ = ["Bar", "DataAdapter", "StubAdapter", "make_adapter"]
