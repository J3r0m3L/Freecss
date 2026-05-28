"""Bucket-level alert rules (Phase 5)."""
from server.alerts import Severity
from server.alerts.bucket_rules import (
    DEFAULT_Z_CRITICAL,
    DEFAULT_Z_HIGH,
    DEFAULT_Z_WARN,
    BucketAlertInput,
    evaluate_bucket,
)


def _inp(*, beta: float, bucket_return: float, z: float,
         direction: str = "BULL") -> BucketAlertInput:
    return BucketAlertInput(
        bucket_id=1, bucket_label="Semis", rep_symbol="SOXX",
        beta=beta, bucket_return=bucket_return, z=z, direction=direction,
    )


def test_below_threshold_returns_none():
    assert evaluate_bucket(inp=_inp(beta=1.0, bucket_return=-0.01, z=-2.0)) is None


def test_warn_at_z_warn():
    hit = evaluate_bucket(inp=_inp(beta=1.0, bucket_return=-0.02, z=-DEFAULT_Z_WARN))
    assert hit is not None
    assert hit.severity == Severity.WARN
    assert hit.kind == "factor:Semis"
    assert hit.adverse is True


def test_high_at_z_high():
    hit = evaluate_bucket(inp=_inp(beta=1.0, bucket_return=-0.03, z=-DEFAULT_Z_HIGH))
    assert hit is not None and hit.severity == Severity.HIGH


def test_critical_at_z_critical():
    hit = evaluate_bucket(inp=_inp(beta=1.0, bucket_return=-0.05, z=-DEFAULT_Z_CRITICAL))
    assert hit is not None and hit.severity == Severity.CRITICAL


def test_aligned_bull_with_positive_beta_and_positive_return():
    """BULL + β>0 + bucket UP → aligned (sector tailwind), still fires (above
    threshold) but with adverse=False so the engine logs without paging."""
    hit = evaluate_bucket(inp=_inp(beta=1.0, bucket_return=0.04, z=4.5))
    assert hit is not None and hit.adverse is False


def test_negative_beta_inverts_adversity():
    """BULL with β<0 (an inverse ETF, say): bucket DOWN actually helps → aligned."""
    hit = evaluate_bucket(inp=_inp(beta=-1.5, bucket_return=-0.04, z=-4.5))
    assert hit is not None and hit.adverse is False


def test_bear_thesis_with_positive_bucket_is_adverse():
    hit = evaluate_bucket(inp=_inp(beta=1.0, bucket_return=0.04, z=4.5,
                                   direction="BEAR"))
    assert hit is not None and hit.adverse is True


def test_zero_beta_not_adverse_even_if_z_large():
    hit = evaluate_bucket(inp=_inp(beta=0.0, bucket_return=-0.05, z=-5.5))
    assert hit is not None and hit.adverse is False


def test_kind_namespacing_uses_bucket_label():
    hit = evaluate_bucket(inp=_inp(beta=1.0, bucket_return=-0.03, z=-3.5))
    # Engine dedup is per-kind; the suffix prevents simultaneous-bucket clashes.
    assert hit and hit.kind.startswith("factor:")
    assert hit.kind != "factor"


def test_payload_includes_diagnostics():
    hit = evaluate_bucket(inp=_inp(beta=0.75, bucket_return=-0.022, z=-3.4))
    assert hit is not None
    p = hit.payload
    assert p["rep_symbol"] == "SOXX"
    assert p["bucket_label"] == "Semis"
    assert p["beta"] == 0.75
    assert p["thesis"] == "BULL"


def test_threshold_overrides():
    # Loose thresholds → z=2.5 now warn.
    hit = evaluate_bucket(inp=_inp(beta=1.0, bucket_return=-0.02, z=-2.5),
                          z_warn=2.0, z_high=10.0, z_critical=20.0)
    assert hit is not None and hit.severity == Severity.WARN
