"""Centralised client for the SensorThings API (SOFAIR).

The SINGLE entry point for every HTTP call to the STA servers (archive /
partage), be they direct, through the internal `/sta` proxy, or passthrough.
Goal: no more `requests.*` calls to STA scattered across the routes and the
processes - one place for the base URL, and later for timeouts / error handling
/ a shared session.

⚠️ This module covers the HTTP layer ONLY. Direct SQL queries (psycopg / COPY,
and the f-string-built SELECTs in sta_routes.py) stay out of it.

Deliberately WITHOUT a default timeout: some POSTs (large `dataArray`) are slow,
and we keep the historical behaviour. A timeout can be added here later, in the
same place for everyone.

API:
- Low level (full URL)        : raw_get / raw_post / raw_patch / raw_delete(url, ...)
- Per server (direct STA)     : get / post / patch / delete(server, path, ...)
- Through the /sta proxy      : proxy_get(server, path, ...)  + proxy_base(server)
- Passthrough (proxy -> STA)  : forward(server, path, params=...)
- Observation writes          : create_observations / patch_observation / delete_observation

`server` is either "archive" or "partage".
"""
import requests

from app.config import Config

_BASE = {"archive": "STALT_archive", "partage": "STALT_partage"}
_PROXY = {"archive": "STALT_archive_proxyname", "partage": "STALT_partage_proxyname"}


def _base(server):
    """Direct base URL of the STA server (ends with /v1.1)."""
    return getattr(Config, _BASE[server])


def proxy_base(server):
    """Base URL through the internal /sta proxy (ends with /v1.1/)."""
    return getattr(Config, _PROXY[server]).rstrip("/") + "/v1.1/"


# --- Low level: full URL (for parameterised clients: sessions, pagination) ---

def raw_request(method, url, **kw):
    return requests.request(method, url, **kw)


def raw_get(url, **kw):
    return raw_request("GET", url, **kw)


def raw_post(url, **kw):
    return raw_request("POST", url, **kw)


def raw_patch(url, **kw):
    return raw_request("PATCH", url, **kw)


def raw_delete(url, **kw):
    return raw_request("DELETE", url, **kw)


# --- Par serveur : STA en direct (STALT_archive / STALT_partage) ---

def get(server, path="", **kw):
    return raw_get(_base(server) + path, **kw)


def post(server, path="", **kw):
    return raw_post(_base(server) + path, **kw)


def patch(server, path="", **kw):
    return raw_patch(_base(server) + path, **kw)


def delete(server, path="", **kw):
    return raw_delete(_base(server) + path, **kw)


# --- Via le proxy interne /sta (formats CSV / dataArray / covjson) ---

def proxy_get(server, path="", **kw):
    return raw_get(proxy_base(server) + path, **kw)


# --- Passthrough: the proxy receives an already-versioned path, we send it to the STA root ---

def forward(server, path, params=None):
    # Same as the historical code: STALT_*[:-4] strips the trailing "v1.1" from the base.
    return raw_get(_base(server)[:-4] + path, params=params)


def forward_request(server, path, method="GET", params=None, **kw):
    """Passthrough of ANY method to STA (proxy -> STA).

    Rebuilds the full STA URL from the proxy path (which already carries the
    "/v1.1"). Used by the proxy to relay the SensorThings writes
    (POST/PATCH/DELETE) received on /sta/<server>/<path> to the STA server, with
    body and headers passed through verbatim via **kw (data=..., headers=...)."""
    return raw_request(method, _base(server)[:-4] + path, params=params, **kw)


# --- Observation writes (recurring URL patterns) ---

def create_observations(server, data_array):
    """POST /CreateObservations (data_array = list of STA blocks)."""
    return post(server, "/CreateObservations", json=data_array)


def patch_observation(server, obs_id, body):
    """PATCH /Observations(<id>)."""
    return patch(server, f"/Observations({obs_id})", json=body)


def delete_observation(server, obs_id):
    """DELETE /Observations(<id>)."""
    return delete(server, f"/Observations({obs_id})")
