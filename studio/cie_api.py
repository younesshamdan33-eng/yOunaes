"""CIE HTTP API — exposes the Cinema Intelligence Engine through Flask.

Blueprint prefix: /api/cie
Endpoints:
  POST /api/cie/plan   {idea}             -> full intelligence plan (no API calls)
  POST /api/cie/preview {idea}            -> minimal preview (story + direction summary)

This module NEVER makes paid API calls. It only runs the local rule-based
intelligence. Magic Hour generation is gated behind a separate, explicit
endpoint in the existing film API.
"""
from __future__ import annotations
from flask import Blueprint, request, jsonify
from studio import cie as cie_engine

bp = Blueprint("cie", __name__, url_prefix="/api/cie")

MAX_IDEA = 2000

def _ok(**kw):
    return jsonify(ok=True, **kw)

def _err(msg, code=400, **extra):
    return jsonify(ok=False, error=msg, **extra), code


@bp.post("/plan")
def plan():
    """idea -> full CIE plan: story + characters + direction."""
    data = request.get_json(silent=True) or {}
    idea = (data.get("idea") or "").strip()
    if not idea:
        return _err("idea required (non-empty string)")
    if len(idea) > MAX_IDEA:
        return _err(f"idea too long (max {MAX_IDEA} chars)")
    try:
        plan = cie_engine.plan(idea)
    except Exception as e:
        return _err(f"engine error: {type(e).__name__}: {e}", code=500)
    return _ok(plan=plan)


@bp.post("/preview")
def preview():
    """idea -> short preview (first scene + style + cast). No charges."""
    data = request.get_json(silent=True) or {}
    idea = (data.get("idea") or "").strip()
    if not idea:
        return _err("idea required")
    if len(idea) > MAX_IDEA:
        return _err(f"idea too long (max {MAX_IDEA} chars)")
    try:
        full = cie_engine.plan(idea)
    except Exception as e:
        return _err(f"engine error: {type(e).__name__}: {e}", code=500)
    first_scene = full["story"]["scenes"][0] if full["story"]["scenes"] else None
    return _ok(
        genre=full["story"].get("genre"),
        tone=full["story"].get("tone"),
        scene_count=len(full["story"]["scenes"]),
        cast_count=len(full.get("characters", [])),
        style=full["direction"].get("style"),
        location=full["direction"].get("location"),
        first_scene=first_scene,
    )


@bp.get("/health")
def health():
    return _ok(engine="cie", units=["story","character","director","lang"])
