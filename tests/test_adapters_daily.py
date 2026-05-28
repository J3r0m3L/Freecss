"""Massive daily-bars adapter — stub mode (DESIGN.md §9)."""
from server.adapters.massive_daily import fetch_daily_bars, stub_returns


def test_stub_returns_have_requested_length(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    bars = fetch_daily_bars("SPY", days=120)
    assert len(bars) == 120
    assert all(b.symbol == "SPY" for b in bars)
    assert all(b.c > 0 for b in bars)


def test_deterministic_per_symbol(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    a = fetch_daily_bars("SPY", days=50)
    b = fetch_daily_bars("SPY", days=50)
    assert [bar.c for bar in a] == [bar.c for bar in b]


def test_basket_members_are_correlated(monkeypatch):
    """SPY / IVV / VOO map to the 'broad' factor → returns should correlate >> 0.5."""
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    spy = stub_returns("SPY", 80)
    ivv = stub_returns("IVV", 80)
    n = min(len(spy), len(ivv))
    if n < 50:
        return  # nothing useful to assert
    import statistics
    mean_s = statistics.mean(spy[:n])
    mean_i = statistics.mean(ivv[:n])
    cov = sum((s - mean_s) * (i - mean_i) for s, i in zip(spy[:n], ivv[:n])) / n
    var_s = statistics.pvariance(spy[:n])
    var_i = statistics.pvariance(ivv[:n])
    rho = cov / ((var_s ** 0.5) * (var_i ** 0.5))
    assert rho > 0.6   # the stub designs in shared market factor; never < 0.6


def test_unrelated_buckets_are_less_correlated(monkeypatch):
    """SPY (broad) vs USO (energy) should NOT correlate as tightly as IVV/VOO."""
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    spy = stub_returns("SPY", 80)
    uso = stub_returns("USO", 80)
    ivv = stub_returns("IVV", 80)
    n = min(len(spy), len(uso), len(ivv))
    import statistics

    def _rho(a, b):
        ma, mb = statistics.mean(a), statistics.mean(b)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / n
        va, vb = statistics.pvariance(a), statistics.pvariance(b)
        return cov / ((va ** 0.5) * (vb ** 0.5))

    assert _rho(spy[:n], ivv[:n]) > _rho(spy[:n], uso[:n])
