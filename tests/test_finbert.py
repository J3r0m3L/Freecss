"""FinBERT stub backend + embedding BLOB helpers (DESIGN.md §3.3, §10)."""
import math

from server.nlp.finbert import (
    EMBED_DIM,
    blob_to_embedding,
    cosine,
    embedding_to_blob,
    get_finbert,
    reset_for_tests,
)


def setup_function(_fn):
    reset_for_tests()


def test_stub_backend_is_used_in_tests():
    fb = get_finbert()
    assert fb.name == "stub"


def test_embedding_dim_and_l2_normalized():
    r = get_finbert().score("AAPL plunges on probe")
    assert len(r.embedding) == EMBED_DIM
    norm = math.sqrt(sum(x * x for x in r.embedding))
    assert abs(norm - 1.0) < 1e-6


def test_polarity_keywords_drive_sentiment_sign():
    r_pos = get_finbert().score("AAPL beats and raises full-year guidance")
    r_neg = get_finbert().score("AAPL plunges on regulatory probe")
    r_neu = get_finbert().score("Apple announced a calendar update.")
    assert r_pos.sentiment > 0 and r_pos.label == "positive"
    assert r_neg.sentiment < 0 and r_neg.label == "negative"
    assert r_neu.label == "neutral"


def test_stub_is_deterministic_for_same_text():
    a = get_finbert().score("AAPL beats")
    b = get_finbert().score("AAPL beats")
    assert a.embedding == b.embedding
    assert a.sentiment == b.sentiment


def test_blob_roundtrip_preserves_floats():
    vec = [0.1, -0.2, 0.3, 0.0, 0.4]
    blob = embedding_to_blob(vec)
    out = blob_to_embedding(blob)
    assert all(abs(a - b) < 1e-6 for a, b in zip(vec, out))


def test_blob_to_embedding_handles_none():
    assert blob_to_embedding(None) is None


def test_cosine_known_values():
    assert abs(cosine([1, 0], [1, 0]) - 1.0) < 1e-9
    assert abs(cosine([1, 0], [0, 1]) - 0.0) < 1e-9
    assert abs(cosine([1, 0], [-1, 0]) - (-1.0)) < 1e-9
    assert cosine([], [1, 0]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0
