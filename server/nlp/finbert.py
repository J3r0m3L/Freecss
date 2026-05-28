"""FinBERT model wrapper (DESIGN.md §3.3, §10).

One model instance is shared process-wide. `score(text)` returns a FinBERTResult
with (sentiment, label, conf, embedding). Embedding is mean-pooled across
non-padding tokens, L2-normalized so later cosine reduces to a dot product.

A deterministic stub is used when:
- `transformers` / `torch` are not installed (Phase 2 nlp extras absent), or
- env `DW_FINBERT_BACKEND=stub` is set (always true in the test harness).

The stub is keyword-driven and deterministic — enough to exercise the rest of
the pipeline without pulling a 400MB checkpoint. Real model load happens lazily
on first call so importing this module is cheap.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from dataclasses import dataclass

log = logging.getLogger("deleveraging_watch.nlp.finbert")

_EMBED_DIM = 768
_MODEL_NAME = "ProsusAI/finbert"  # pinned name (revision pin lives in pyproject extras)


@dataclass(frozen=True)
class FinBERTResult:
    sentiment: float          # p_pos − p_neg, in [-1, 1]
    label: str                # 'positive' | 'negative' | 'neutral'
    conf: float               # max softmax probability
    embedding: list[float]    # 768-dim float32, L2-normalized


class _StubFinBERT:
    """Deterministic, keyword-driven stand-in. Same shape as the real backend.

    Sentiment is a simple lexicon match (so tests can write 'plunges'/'beats'
    and get the polarity they expect). Embedding is seeded by a stable hash of
    the text — identical text → identical vector, similar text → different but
    deterministic vectors. Good enough for cosine-pipeline tests.
    """

    name = "stub"

    _POS = {"beats", "surges", "rallies", "upgrade", "upgrades", "tops",
            "record", "soars", "strong", "outperform", "raised", "guides higher"}
    _NEG = {"misses", "plunges", "downgrade", "downgrades", "cuts", "warns",
            "guides lower", "halts", "probe", "lawsuit", "fraud", "weak",
            "underperform", "slashes", "tariff", "tariffs", "investigation"}

    def score(self, text: str) -> FinBERTResult:
        t = (text or "").lower()
        pos_hits = sum(1 for w in self._POS if w in t)
        neg_hits = sum(1 for w in self._NEG if w in t)
        total = pos_hits + neg_hits
        if total == 0:
            p_pos, p_neg, p_neu = 0.1, 0.1, 0.8
        else:
            p_pos = 0.05 + 0.9 * (pos_hits / total) if pos_hits else 0.05
            p_neg = 0.05 + 0.9 * (neg_hits / total) if neg_hits else 0.05
            p_neu = max(0.0, 1.0 - p_pos - p_neg)
        # Renormalize to a valid softmax (numerical guard).
        s = p_pos + p_neg + p_neu
        p_pos, p_neg, p_neu = p_pos / s, p_neg / s, p_neu / s

        sentiment = p_pos - p_neg
        if p_pos >= max(p_neg, p_neu):
            label, conf = "positive", p_pos
        elif p_neg >= max(p_pos, p_neu):
            label, conf = "negative", p_neg
        else:
            label, conf = "neutral", p_neu

        return FinBERTResult(
            sentiment=sentiment, label=label, conf=conf,
            embedding=_stub_embedding(text),
        )


def _stub_embedding(text: str) -> list[float]:
    """Deterministic, L2-normalized 768-dim vector keyed on text content.

    Method: SHA-256 → expand to EMBED_DIM bytes → center on 128 → normalize.
    Same input → same vector. Different inputs → different vectors. Cosine
    between two stub vectors won't be semantically meaningful (it's a hash),
    so tests that need controlled cosine values inject vectors directly.
    """
    norm_text = re.sub(r"\s+", " ", (text or "").strip().lower())
    seed = hashlib.sha256(norm_text.encode("utf-8")).digest()
    # Stretch the 32-byte digest into EMBED_DIM bytes deterministically.
    buf = bytearray()
    counter = 0
    while len(buf) < _EMBED_DIM:
        buf.extend(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
        counter += 1
    floats = [(b - 128) / 128.0 for b in buf[:_EMBED_DIM]]
    return _l2_normalize(floats)


def _l2_normalize(v: list[float]) -> list[float]:
    norm = sum(x * x for x in v) ** 0.5
    if norm == 0:
        return v
    return [x / norm for x in v]


class _RealFinBERT:  # pragma: no cover — exercised only when extras installed
    """transformers / torch backend. Loaded lazily; failure falls back to stub."""

    name = "transformers"

    def __init__(self) -> None:
        import torch  # noqa: F401  (import to surface ImportError early)
        from transformers import AutoModel, AutoTokenizer

        self._torch = __import__("torch")
        self._tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
        self._model = AutoModel.from_pretrained(_MODEL_NAME)
        self._model.eval()
        # FinBERT classifier head is bundled with the model on HF; for simplicity
        # we use the base model embedding + a tiny logistic over the [CLS] token
        # would be ideal, but ProsusAI/finbert exposes the classifier directly.
        # The minimal path: AutoModelForSequenceClassification.
        from transformers import AutoModelForSequenceClassification
        self._clf = AutoModelForSequenceClassification.from_pretrained(_MODEL_NAME)
        self._clf.eval()
        # ProsusAI/finbert label order: [positive, negative, neutral].
        self._labels = ["positive", "negative", "neutral"]

    def score(self, text: str) -> FinBERTResult:
        torch = self._torch
        tokens = self._tokenizer(text or "", return_tensors="pt",
                                 truncation=True, max_length=256, padding=True)
        with torch.no_grad():
            clf_out = self._clf(**tokens).logits.softmax(dim=-1)[0].tolist()
            emb_out = self._model(**tokens).last_hidden_state[0]
            mask = tokens["attention_mask"][0].unsqueeze(-1).float()
            pooled = (emb_out * mask).sum(0) / mask.sum().clamp(min=1)
        p_pos, p_neg, p_neu = clf_out
        sentiment = p_pos - p_neg
        idx = int(max(range(3), key=lambda i: clf_out[i]))
        return FinBERTResult(
            sentiment=sentiment, label=self._labels[idx], conf=float(clf_out[idx]),
            embedding=_l2_normalize(pooled.tolist()),
        )


_singleton_lock = threading.Lock()
_singleton: "_StubFinBERT | _RealFinBERT | None" = None


def get_finbert():
    """Return the process-wide FinBERT instance, building it on first call."""
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is not None:
            return _singleton
        backend = os.environ.get("DW_FINBERT_BACKEND", "auto")
        if backend == "stub":
            _singleton = _StubFinBERT()
            return _singleton
        try:
            _singleton = _RealFinBERT()
            log.info("FinBERT loaded (transformers backend)")
        except Exception as exc:  # noqa: BLE001
            log.warning("FinBERT real backend unavailable (%s); using stub", exc)
            _singleton = _StubFinBERT()
        return _singleton


def reset_for_tests() -> None:
    """Drop the cached singleton so the next get_finbert() rebuilds it."""
    global _singleton
    with _singleton_lock:
        _singleton = None


# ---- BLOB encoding helpers used by the persistence layer (instrument.profile_embedding,
# update_log.body_embedding). Plain little-endian float32 packed bytes; we keep this
# self-contained to avoid numpy as a hard runtime dep.
import struct  # noqa: E402

EMBED_DIM = _EMBED_DIM


def embedding_to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def blob_to_embedding(blob: bytes | memoryview | None) -> list[float] | None:
    if blob is None:
        return None
    data = bytes(blob)
    n = len(data) // 4
    if n == 0:
        return None
    return list(struct.unpack(f"<{n}f", data))


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Inputs may or may not be normalized — we don't assume."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
