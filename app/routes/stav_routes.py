"""
Serves the STAV front-end (embedded depot via git subtree in /stav) directly
from Flask.
STAV is served under the root corresponding to the deployment observatory
(Config.STALT_observatoire), which puts it on the same origin.
"""
import os

from flask import Blueprint, send_from_directory, jsonify, redirect, request

from app.config import Config

# /stav is a sibling directory to app/ (embedded via git subtree).
STAV_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "stav"))
STAV_CONFIG_DIR = os.path.join(STAV_DIR, "config")

stav_bp = Blueprint("stav", __name__)


def _hex_to_rgba(hex_color, alpha):
    """'#rrggbb' -> 'rgba(r,g,b,alpha)', or None if not a 6-digit hex."""
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None
    return f"rgba({r},{g},{b},{alpha})"


def _qf_colors():
    """QF code -> rgba background for STAV's archive view, derived from the QF
    vocabulary (Config.STALT_OBSP_QF). STAV consumes this via the config
    descriptor instead of its own hardcoded map, so qf_flags.json stays the
    single source of truth (STAV included)."""
    out = {}
    for code, meta in (Config.STALT_OBSP_QF.get("properties") or {}).items():
        rgba = _hex_to_rgba(meta.get("color"), 0.40) if isinstance(meta, dict) else None
        if rgba:
            out[str(code)] = rgba
    return out


@stav_bp.route("/config/<observatoire>.json")
def stav_descriptor(observatoire):
    """
    STAV config file generator.

    /stav is dedicated to the observatory of this deployment. We generate the JSON on
    the fly from Config (the STA URLs / the mode in config.py), in two variants:

    - <obs>.json  -> "share" server (published / qualified data)
    - <obs>-archive.json   -> "archive" server (raw data, standard mode)
    """

    obs = Config.STALT_observatoire
    # the obs name need to be the the observatory of the application
    # else it's another STAV config
    if observatoire in (obs, f"{obs}-archive"):
        is_archive = observatoire != obs
        md = Config.APP_METADATA or {}
        # Archive = raw data: "archive" proxy + standard mode (no server-side
        # aggregation, we display the raw values). Otherwise "partage" proxy.
        base = (Config.STALT_archive_proxyname if is_archive
                else Config.STALT_partage_proxyname)
        return jsonify({

            "urlService": base.rstrip("/") + "/v1.1/",
            "mode": Config.STALT_mode_service,
            "archive": is_archive,
            # FROM the metadata (app/static/metadata/metadata_iso_19119.json)
            "nameService": md.get("name") or Config.APP_TITLE,
            "description": md.get("resume", ""),
            "metadata": md.get("metadata_url") or "/metadata",
            "metrology":  is_archive,
            "interventionTerrain": md.get("interventionTerrain") or None,
            "barObservedProperties": md.get("barObservedProperties") or [],
            # QF code -> rgba, so STAV colours the archive background from the
            # single-source vocabulary instead of a hardcoded map.
            "qfColors": _qf_colors(),
        })
    return send_from_directory(STAV_CONFIG_DIR, f"{observatoire}.json")


@stav_bp.route("/", defaults={"path": ""})
@stav_bp.route("/<path:path>")
def serve_stav(path):
    """Serves STAV static files."""
    full = os.path.join(STAV_DIR, path)
    if path == "" or os.path.isdir(full):
        # A directory must end with “/”, otherwise relative paths (../../css/...)
        # go up one level too far → redirect
        if path and not request.path.endswith("/"):
            new_url = request.path + "/"
            if request.query_string:
                new_url += "?" + request.query_string.decode()
            return redirect(new_url, code=308)
        return send_from_directory(full, "index.html")
    return send_from_directory(STAV_DIR, path)
