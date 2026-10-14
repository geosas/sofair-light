"""Shared helpers of the gauging tools.

Everything lives in the ARCHIVE STA, with the app's MultiDatastream layout:
ObservedProperties [property, QF, property] and results [raw, QF, corrected]
(see exe_config_post_to_sta.creationMultiDataStreams). The share STA is fed
later by the qualification, like any other archive data.
All STA calls go through `sta_client`.
"""
import os
import re

import pandas as pd
from flask import current_app
from flask_babel import gettext as _
from flask_babel import get_locale

from app import config_tarage as cfg
from app.sta_tools import sta_client

SERVER = "archive"

# Generated PNG plots, under static/
PLOTS_SUBDIR = "plots/tarage"

# Discharge MultiDatastream of a site (one per Thing)
STREAMFLOW_DS_NAME = f"{cfg.STREAMFLOW_NAME} by tracing"


def odata(value):
    """Escape a value for an OData string literal (single quotes doubled)."""
    return str(value).replace("'", "''")


def id_from_location(location_header):
    """Integer id from a FROST Location header: .../Things(42) -> 42."""
    m = re.search(r'\((\d+)\)$', location_header or '')
    return int(m.group(1)) if m else None


def get_all(path, params=None):
    """GET a STA collection, following @iot.nextLink. Returns (values, error)."""
    values = []
    r = sta_client.get(SERVER, path, params=params)
    while True:
        if not r.ok:
            return values, _("SensorThings error (%(code)s)", code=r.status_code)
        body = r.json()
        values.extend(body.get("value", []))
        next_link = body.get("@iot.nextLink")
        if not next_link:
            return values, None
        r = sta_client.raw_get(next_link)  # nextLink already carries the params


def find_id(collection, name):
    """@iot.id of the entity of `collection` named `name`, or None."""
    r = sta_client.get(SERVER, f"/{collection}",
                       params={"$filter": f"name eq '{odata(name)}'", "$select": "id"})
    values = r.json().get("value", []) if r.ok else []
    return values[0]["@iot.id"] if values else None


def corrected(result):
    """Corrected value of an archive result [raw, QF, corrected]."""
    return result[2] if isinstance(result, list) else result


def fetch_observations(ds_id, t_min=None, t_max=None):
    """[{phenomenonTime, result}] of a MultiDatastream (corrected values),
    optionally restricted to [t_min, t_max] (Timestamps)."""
    params = {"$select": "phenomenonTime,result", "$orderby": "phenomenonTime asc"}
    if t_min is not None and t_max is not None:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        params["$filter"] = (f"phenomenonTime ge {t_min.strftime(fmt)}"
                             f" and phenomenonTime le {t_max.strftime(fmt)}")
    observations, _error = get_all(f"/MultiDatastreams({ds_id})/Observations", params)
    for o in observations:
        o["result"] = corrected(o.get("result"))
    return observations


def main_property(ds):
    """Name of the main ObservedProperty of a MultiDatastream ($expand-ed)."""
    ops = ds.get("ObservedProperties") or []
    return ops[0]["name"] if ops else None


def things_with_property(op_name):
    """[{id, name}] of the Things having a MultiDatastream of `op_name`."""
    op_id = find_id("ObservedProperties", op_name)
    if op_id is None:
        return []
    datastreams, _error = get_all(f"/ObservedProperties({op_id})/MultiDatastreams",
                                  params={"$select": "id", "$expand": "Thing($select=id,name)"})
    things = {}
    for ds in datastreams:
        t = ds.get("Thing") or {}
        if t.get("@iot.id") is not None:
            things.setdefault(t["@iot.id"], {"id": t["@iot.id"], "name": t.get("name", "")})
    return sorted(things.values(), key=lambda t: t["name"])


def parse_pt(pt_str):
    """FROST phenomenonTime -> (start, end) UTC Timestamps, (None, None) if invalid."""
    if not pt_str or pt_str == '/':
        return None, None
    try:
        if '/' in pt_str:
            s, e = pt_str.split('/', 1)
            return pd.to_datetime(s, utc=True), pd.to_datetime(e, utc=True)
        dt = pd.to_datetime(pt_str, utc=True)
        return dt, dt
    except Exception:
        return None, None


def plots_dir():
    """Absolute directory of the generated plots (created if missing)."""
    path = os.path.join(current_app.static_folder, *PLOTS_SUBDIR.split("/"))
    os.makedirs(path, exist_ok=True)
    return path


def plot_name(prefix, key):
    """Plot file name. The locale is part of it: plots carry translated labels."""
    return f"{prefix}_{key}_{get_locale()}_plot.png"
