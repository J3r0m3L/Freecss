"""§10.1 profile-setup pipeline + profile_text generator (stub backend)."""
import json

from server.db import one
from server.nlp.finbert import blob_to_embedding
from server.nlp.profile_setup import setup_profile
from server.nlp.profile_text import generate_profile_text


def test_profile_text_stub_uses_meta_fields():
    out = generate_profile_text(
        symbol="AAPL", display_name="Apple Inc.",
        meta={"sector": "Technology", "industry": "Consumer Electronics",
              "country": "US", "description": "designs phones and laptops"},
    )
    assert out.backend == "stub" and out.cost_usd == 0.0
    assert "Apple Inc." in out.text
    assert "Technology" in out.text


def test_profile_text_falls_back_when_no_anthropic_key(monkeypatch):
    # 'auto' + missing ANTHROPIC_API_KEY should also yield the stub paragraph.
    monkeypatch.setenv("DW_PROFILE_TEXT_BACKEND", "auto")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = generate_profile_text(
        symbol="MSFT", display_name="Microsoft", meta={"sector": "Technology"},
    )
    assert out.backend == "stub"


def test_setup_profile_persists_meta_text_and_embedding(make_watch):
    iid, _ = make_watch("AAPL")
    setup_profile(iid)
    row = one("SELECT meta_json, profile_text, profile_embedding, meta_refreshed_at "
              "FROM instrument WHERE id=?", (iid,))
    assert row["meta_refreshed_at"] is not None
    assert row["profile_text"] and "AAPL" in row["profile_text"]
    meta = json.loads(row["meta_json"])
    assert meta.get("sector")  # populated from Finnhub stub
    emb = blob_to_embedding(row["profile_embedding"])
    assert emb is not None and len(emb) == 768


def test_setup_profile_is_idempotent(make_watch):
    iid, _ = make_watch("AAPL")
    setup_profile(iid)
    first = one("SELECT profile_text, profile_embedding FROM instrument WHERE id=?", (iid,))
    setup_profile(iid)
    second = one("SELECT profile_text, profile_embedding FROM instrument WHERE id=?", (iid,))
    # Same stub inputs → same outputs.
    assert first["profile_text"] == second["profile_text"]
    assert bytes(first["profile_embedding"]) == bytes(second["profile_embedding"])
