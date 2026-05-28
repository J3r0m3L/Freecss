"""Settings GET/PATCH + credential surface (DESIGN.md §7.1, §11.E)."""


def test_defaults_returned(client):
    body = client.get("/api/settings").json
    s = body["settings"]
    assert s["thresholds"]["px_jump_pct"] == 0.03
    assert s["thresholds"]["spread_bps_max"] == 50.0
    assert s["quiet_hours"]["work_start_et"] == "09:00"
    assert s["quiet_hours"]["work_end_et"] == "17:00"
    assert s["exit_liquidity"]["participation"] == 0.10


def test_credentials_surface_only_booleans(client):
    body = client.get("/api/settings").json
    creds = body["credentials"]
    assert all(isinstance(v, bool) for v in creds.values())
    # No key material in the response payload.
    for v in creds.values():
        assert not isinstance(v, str)


def test_patch_persists(client):
    r = client.patch("/api/settings",
                     json={"quiet_hours": {"digest_time_et": "09:30"}})
    assert r.status_code == 200
    assert r.json["settings"]["quiet_hours"]["digest_time_et"] == "09:30"
    # Re-fetch — change survived.
    s = client.get("/api/settings").json["settings"]
    assert s["quiet_hours"]["digest_time_et"] == "09:30"
