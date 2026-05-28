"""Curated X-account CRUD (DESIGN.md §7.1, §11.E).

The X-handle list is roughly time-invariant — seeded from social_watch.yaml and
edited from Settings. Adding a handle synchronously calls the X User: Read
endpoint (billed once at ~$0.01) to resolve numeric external_id; deletes are
soft so historical posts remain queryable.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from server.adapters.x_api import resolve_user_id
from server.db import execute, one, rows

bp = Blueprint("social", __name__, url_prefix="/api")


def _view(r: dict) -> dict:
    return {
        "id": r["id"],
        "handle": r["handle"],
        "label": r["label"],
        "external_id": r["external_id"],
        "active": bool(r["active"]),
        "added_at": r["added_at"],
        "last_polled_at": r["last_polled_at"],
        "last_post_id": r["last_post_id"],
    }


@bp.get("/social/accounts")
def list_accounts():
    active_only = request.args.get("active", "true").lower() == "true"
    if active_only:
        data = rows("SELECT * FROM social_account_watch WHERE active=1 ORDER BY handle")
    else:
        data = rows("SELECT * FROM social_account_watch ORDER BY handle")
    return jsonify([_view(r) for r in data])


@bp.post("/social/accounts")
def add_account():
    body = request.get_json(silent=True) or {}
    handle = (body.get("handle") or "").lstrip("@").strip()
    label = body.get("label")
    if not handle:
        return jsonify({"error": "handle is required"}), 400
    if one("SELECT 1 FROM social_account_watch WHERE source='x' AND handle=?",
           (handle,)):
        return jsonify({"error": f"@{handle} already tracked"}), 409

    ext_id = resolve_user_id(handle)  # bills $0.01 if real X token is configured
    cur = execute(
        "INSERT INTO social_account_watch(source, handle, label, external_id) "
        "VALUES('x',?,?,?)",
        (handle, label, ext_id),
    )
    r = one("SELECT * FROM social_account_watch WHERE id=?", (cur.lastrowid,))
    return jsonify(_view(r)), 201


@bp.patch("/social/accounts/<int:account_id>")
def patch_account(account_id: int):
    if not one("SELECT 1 FROM social_account_watch WHERE id=?", (account_id,)):
        return jsonify({"error": "account not found"}), 404
    body = request.get_json(silent=True) or {}
    sets, params = [], []
    if "label" in body:
        sets.append("label=?")
        params.append(body["label"])
    if "active" in body:
        sets.append("active=?")
        params.append(1 if body["active"] else 0)
    if not sets:
        return jsonify({"error": "nothing to update"}), 400
    params.append(account_id)
    execute(f"UPDATE social_account_watch SET {', '.join(sets)} WHERE id=?",
            tuple(params))
    return jsonify({"ok": True})


@bp.delete("/social/accounts/<int:account_id>")
def delete_account(account_id: int):
    if not one("SELECT 1 FROM social_account_watch WHERE id=?", (account_id,)):
        return jsonify({"error": "account not found"}), 404
    execute("UPDATE social_account_watch SET active=0 WHERE id=?", (account_id,))
    return jsonify({"ok": True})
