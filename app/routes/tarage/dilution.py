"""Gauging tools: discharge by salt (NaCl) dilution.

Workflow of the /tarage/dilution page:
1. find the conductivity ObservedProperty and its Datastreams;
2. pick (or create) the measurement site (Thing);
3. upload a conductivity CSV, select one range per injection, compute the
   discharge of each range + its uncertainty;
4. publish the conductivity series and the discharges to SensorThings.

Archive STA / MultiDatastream layout: see common.py.
"""
import json
import re

import numpy as np
import pandas as pd
from flask import jsonify, render_template, request
from flask_babel import gettext as _

from app import config_tarage as cfg
from app.config import Config
from app.routes.tarage import tarage_bp
from app.routes.tarage.common import (SERVER, STREAMFLOW_DS_NAME, corrected, find_id,
                                      get_all, id_from_location, main_property, odata)
from app.services.security import jwt_required_or_redirect
from app.sta_tools import sta_client

OM_COMPLEX = "http://www.opengis.net/def/observationType/OGC-OM/2.0/OM_ComplexObservation"
QF_UNIT = {"name": "Qualification", "symbol": None, "definition": "link to qualification"}
# QF of freshly published values (not qualified yet)
QF_RAW = Config.STALT_OBSP_QF.get('raw_default', 0)
# observationProcedure of the gauging MultiDatastreams (keeps them out of the
# file-import pipeline, which only picks veloProcessing / httpsConnected)
OBSERVATION_PROCEDURE = "saltDilution"

# np.trapezoid exists from numpy 2.0, np.trapz before
_trapezoid = getattr(np, "trapezoid", None) or np.trapz


def _multi_ds_payload(name, unit, sensor_id, op_id, qf_id, thing_id, properties):
    """MultiDatastream in the app's archive layout [property, QF, property]."""
    return {
        "name": name,
        "description": name,
        "observationType": OM_COMPLEX,
        "multiObservationDataTypes": ["OM_Measurement", "OM_CategoryObservation", "OM_Measurement"],
        "unitOfMeasurements": [unit, QF_UNIT, unit],
        "Sensor": {"@iot.id": sensor_id},
        "ObservedProperties": [{"@iot.id": op_id}, {"@iot.id": qf_id}, {"@iot.id": op_id}],
        "Thing": {"@iot.id": thing_id},
        "properties": properties,
    }


def _create(collection, payload):
    """POST an entity and return its id (raises RuntimeError on failure)."""
    r = sta_client.post(SERVER, f"/{collection}", json=payload)
    if not r.ok:
        raise RuntimeError(r.text)
    return id_from_location(r.headers.get("Location"))


def _thing_foi_id(thing_id):
    """Id of the Thing's FeatureOfInterest (same name as the Thing, as created by
    the config publish); created from the Thing's Location when missing."""
    r = sta_client.get(SERVER, f"/Things({thing_id})",
                       params={"$select": "name,description",
                               "$expand": "Locations($select=location)"})
    if not r.ok:
        raise RuntimeError(r.text)
    thing = r.json()
    foi_id = find_id("FeaturesOfInterest", thing["name"])
    if foi_id is not None:
        return foi_id

    locations = thing.get("Locations") or []
    if not locations:
        raise RuntimeError(_("The Thing has no Location"))
    location = locations[0]["location"]
    if location.get("type") == "Feature":
        location = location["geometry"]
    return _create("FeaturesOfInterest", {
        "name": thing["name"],
        "description": thing.get("description") or thing["name"],
        "encodingType": "application/geo+json",
        "feature": location,
    })


def _post_archive_observations(multi_ds_id, foi_id, rows):
    """POST [[phenomenonTime, value], ...] to a MultiDatastream as
    [raw, QF, corrected] results (QF = not qualified yet)."""
    return sta_client.create_observations(SERVER, [{
        "MultiDatastream": {"@iot.id": multi_ds_id},
        "components": ["phenomenonTime", "result", "FeatureOfInterest/id"],
        "dataArray": [[t, [v, QF_RAW, v], foi_id] for t, v in rows],
    }])


def _read_csv(file):
    """Conductivity CSV (columns date, result) sorted by date."""
    df = pd.read_csv(file)
    df.columns = [c.strip() for c in df.columns]
    df['date'] = pd.to_datetime(df['date'], format=cfg.CSV_DATE_FORMAT)
    return df.sort_values('date').reset_index(drop=True)


def _range_df(df, r):
    """Rows of `df` inside the range {start, end}."""
    t_start = pd.to_datetime(r['start'], format=cfg.RANGE_DATE_FORMAT)
    t_end = pd.to_datetime(r['end'], format=cfg.RANGE_DATE_FORMAT)
    return df[(df['date'] >= t_start) & (df['date'] <= t_end)].copy()


@tarage_bp.get('/dilution')
@jwt_required_or_redirect()
def dilution():
    return render_template('private/tarage/dilution.html')


@tarage_bp.get('/api/init')
@jwt_required_or_redirect()
def api_init():
    """Steps 1+2: the conductivity ObservedProperty, then its MultiDatastreams."""
    name = cfg.CONDUCTIVITY_NAME
    try:
        r = sta_client.get(SERVER, "/ObservedProperties",
                           params={"$filter": f"name eq '{odata(name)}'", "$select": "id,name"})
    except Exception:
        return jsonify({"error": _("SensorThings service not active or unreachable")}), 502
    if not r.ok:
        return jsonify({"error": _("SensorThings error (%(code)s)", code=r.status_code)}), 502

    op_values = r.json().get("value", [])
    if not op_values:
        return jsonify({"error": _("ObservedProperty '%(name)s' not found", name=name)}), 404
    op_id = op_values[0]["@iot.id"]

    datastreams, error = get_all(f"/ObservedProperties({op_id})/MultiDatastreams",
                                  params={"$select": "name,id"})
    if error:
        return jsonify({"error": _("Unable to fetch the Datastreams: %(error)s", error=error)}), 502

    return jsonify({
        "op_id": op_id,
        "datastreams": datastreams,
        "has_datastreams": len(datastreams) > 0,
    })


@tarage_bp.post('/api/thing')
@jwt_required_or_redirect()
def create_thing():
    """Create a Thing + Location + its FeatureOfInterest (the MultiDatastreams
    are created at publication)."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": _("The site name is required.")}), 400
    desc = data.get("description") or name
    try:
        lng, lat = float(data["lng"]), float(data["lat"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": _("Invalid coordinates")}), 400

    payload = {
        "name": name,
        "description": desc,
        # Marks the gauging sites: listed even before their first publication
        "properties": {"gaugingSite": True},
        "Locations": [{
            "name": name,
            "description": desc,
            "encodingType": "application/geo+json",
            "location": {"type": "Feature",
                         "geometry": {"type": "Point", "coordinates": [lng, lat]}},
        }],
    }
    try:
        thing_id = _create("Things", payload)
        _thing_foi_id(thing_id)
    except RuntimeError as e:
        return jsonify({"error": _("Thing creation failed"), "detail": str(e)}), 502

    return jsonify({"ok": True, "thing_id": thing_id}), 201


@tarage_bp.get('/api/things')
@jwt_required_or_redirect()
def get_things():
    """Step 3: the gauging sites = Things created by this page (gaugingSite
    marker, even with no gauging published yet) + the Things of the given
    conductivity MultiDatastream ids."""
    things = {}
    marked, _error = get_all("/Things", params={"$filter": "properties/gaugingSite eq true",
                                                "$select": "id,name"})
    for thing in marked:
        things.setdefault(thing["@iot.id"], {"id": thing["@iot.id"], "name": thing["name"]})
    for ds_id in request.args.getlist("ds_ids", type=int):
        r = sta_client.get(SERVER, f"/MultiDatastreams({ds_id})/Thing",
                           params={"$select": "name,id"})
        if r.ok:
            thing = r.json()
            things.setdefault(thing["@iot.id"], {"id": thing["@iot.id"], "name": thing["name"]})

    return jsonify({"things": sorted(things.values(), key=lambda t: t["name"])})


@tarage_bp.post('/api/calculate')
@jwt_required_or_redirect()
def calculate():
    """Step 4: discharge by salt (NaCl) dilution, one value per range."""
    data = request.form.to_dict()

    if 'csv_file' not in request.files or request.files['csv_file'].filename == '':
        return jsonify({"error": _("No CSV sent")}), 400

    try:
        salt_masses_g = json.loads(data['masse_sel'])   # [g, g, ...], one per range
        delta_t = float(data['delta_t'])
        ranges = json.loads(data.get('ranges', '[]'))
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        return jsonify({"error": _("Invalid parameters: %(error)s", error=e)}), 400

    if not ranges:
        return jsonify({"error": _("No measurement range defined")}), 400
    if len(salt_masses_g) != len(ranges):
        return jsonify({"error": _("Number of masses (%(masses)s) != number of ranges (%(ranges)s)",
                                  masses=len(salt_masses_g), ranges=len(ranges))}), 400

    try:
        df = _read_csv(request.files['csv_file'])
    except Exception as e:
        return jsonify({"error": _("Error while reading the CSV: %(error)s", error=e)}), 400

    # Calibration factor (conductivity -> salt concentration)
    calibration = 0.486 * 0.001

    debits = []
    for i, r in enumerate(ranges):
        df_range = _range_df(df, r)
        if df_range.empty:
            return jsonify({"error": _("No data in the range %(start)s -> %(end)s",
                                      start=r['start'], end=r['end'])}), 400

        # Initial (background) conductivity from the first 5 values: their
        # median when stable, else the first one (not enough values before the cloud)
        first_values = df_range.head(5)['result']
        if first_values.max() - first_values.min() <= 2:
            initial_conductivity = first_values.median()
        else:
            initial_conductivity = first_values.iloc[0]

        integration = _trapezoid(df_range['result'] - initial_conductivity, dx=delta_t)
        if integration <= 0:
            return jsonify({
                "error": _("Zero or negative integral on the range %(start)s. "
                           "Check that the range contains the conductivity peak.",
                           start=r['start'])
            }), 400
        debits.append(salt_masses_g[i] / (calibration * integration * delta_t))  # L/s

    # Uncertainty (GUM §4.3.7: uniform distribution when n < 6)
    arr = np.array(debits)
    mean_val = arr.mean()
    if len(debits) < 6:
        u_abs = (arr.max() - arr.min()) / (2 * np.sqrt(3))
    else:
        u_abs = arr.std()
    u_rel = (u_abs / mean_val) if mean_val != 0 else 0

    return jsonify({
        "debit": debits,
        "units": "L/s",
        "incertitude": round(u_rel * 100, 2),   # relative, %
        "incertitude_abs": round(u_abs, 3),     # absolute, L/s
    })


@tarage_bp.get('/api/observations')
@jwt_required_or_redirect()
def get_observations():
    """Corrected values of a MultiDatastream (FROST pagination handled)."""
    ds_id = request.args.get('ds_id', type=int)
    if ds_id is None:
        return jsonify({"error": _("Missing ds_id")}), 400

    observations, error = get_all(
        f"/MultiDatastreams({ds_id})/Observations",
        params={"$select": "phenomenonTime,result", "$orderby": "phenomenonTime asc"})
    if error:
        return jsonify({"error": error}), 502
    for o in observations:
        o["result"] = corrected(o.get("result"))
    return jsonify({"observations": observations})


@tarage_bp.post('/api/publish')
@jwt_required_or_redirect()
def publish():
    """Step 5: publish the conductivity series and the discharges to STA."""
    data = request.form.to_dict()

    if 'csv_file' not in request.files or request.files['csv_file'].filename == '':
        return jsonify({"error": _("No CSV sent")}), 400

    try:
        thing_id = int(data['thing_id'])
        thing_name = data.get('thing_name', '')
        ranges = json.loads(data['ranges'])
        debits = json.loads(data['debits'])
        salt_masses_g = json.loads(data.get('masse_sel', '[]'))
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return jsonify({"error": _("Invalid parameters: %(error)s", error=e)}), 400

    try:
        df = _read_csv(request.files['csv_file'])
    except Exception as e:
        return jsonify({"error": _("Error while reading the CSV: %(error)s", error=e)}), 400

    # ── Shared ids ──────────────────────────────────────────────────────
    conductivity_name = cfg.CONDUCTIVITY_NAME
    sensor_id = find_id("Sensors", cfg.CONDUCTIMETER_NAME)
    if sensor_id is None:
        return jsonify({"error": _("Sensor '%(name)s' not found",
                                  name=cfg.CONDUCTIMETER_NAME)}), 404
    op_cond_id = find_id("ObservedProperties", conductivity_name)
    if op_cond_id is None:
        return jsonify({"error": _("ObservedProperty '%(name)s' not found", name=conductivity_name)}), 404
    qf_id = find_id("ObservedProperties", Config.STALT_OBSP_QF["name"])
    if qf_id is None:
        return jsonify({"error": _("ObservedProperty '%(name)s' not found",
                                  name=Config.STALT_OBSP_QF["name"])}), 404
    try:
        foi_id = _thing_foi_id(thing_id)
    except RuntimeError as e:
        return jsonify({"error": _("Unable to get the FeatureOfInterest: %(error)s", error=e)}), 502

    # MultiDatastreams of the Thing with their main ObservedProperty
    thing_ds, error = get_all(
        f"/Things({thing_id})/MultiDatastreams",
        params={"$select": "id,name,phenomenonTime",
                "$expand": "ObservedProperties($select=name)"})
    if error:
        return jsonify({"error": _("Unable to fetch the Datastreams: %(error)s", error=error)}), 502

    # ── A. Conductivity observations ────────────────────────────────────
    # One conductivity MultiDatastream per gauging, numbered "<name> <site> (n)"
    cond_properties = {
        "observationProcedure": OBSERVATION_PROCEDURE,
        "foiId": foi_id,
        cfg.STREAMFLOW_NAME: {"value": debits, "units": "L/s"},
        "tracer": {"name": "salt", "weights": salt_masses_g, "units": "g"},
    }
    cond_ds_list = [ds for ds in thing_ds if main_property(ds) == conductivity_name]

    def ds_number(ds):
        m = re.search(r'\((\d+)\)$', ds.get('name', ''))
        return int(m.group(1)) if m else 0

    def create_cond_ds(n):
        return _create("MultiDatastreams", _multi_ds_payload(
            f"{conductivity_name} {thing_name} ({n})", cfg.CONDUCTIVITY_UNIT,
            sensor_id, op_cond_id, qf_id, thing_id, cond_properties))

    try:
        if not cond_ds_list:
            # First publication for this site
            cond_ds_id = create_cond_ds(1)
        else:
            # The highest number is the latest one; reuse it while it is empty
            latest_ds = max(cond_ds_list, key=ds_number)
            cond_ds_id = latest_ds["@iot.id"]
            pt = latest_ds.get("phenomenonTime") or ""
            if pt and pt != "/":
                cond_ds_id = create_cond_ds(max(ds_number(ds) for ds in cond_ds_list) + 1)
    except RuntimeError as e:
        return jsonify({"error": _("Unable to create the conductivity Datastream: %(error)s", error=e)}), 502

    df["phenomenonTime"] = df["date"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df_obs = df[["phenomenonTime", "result"]].dropna()

    r_obs = _post_archive_observations(cond_ds_id, foi_id, df_obs.values.tolist())
    if not r_obs.ok:
        return jsonify({"error": _("Error while posting the conductivity: %(error)s", error=r_obs.text)}), 502

    # ── B. Discharge observations ───────────────────────────────────────
    sf_ds_name = STREAMFLOW_DS_NAME
    sf_ds_list = [ds for ds in thing_ds if ds.get("name") == sf_ds_name]

    if sf_ds_list:
        sf_ds_id = sf_ds_list[0]["@iot.id"]
    else:
        op_sf_id = find_id("ObservedProperties", cfg.STREAMFLOW_NAME)
        if op_sf_id is None:
            return jsonify({"error": _("ObservedProperty '%(name)s' not found",
                                      name=cfg.STREAMFLOW_NAME)}), 404
        try:
            # Discharge Sensor: find or create
            sensor_sf_id = find_id("Sensors", cfg.DISCHARGE_SENSOR["name"])
            if sensor_sf_id is None:
                sensor_sf_id = _create("Sensors", cfg.DISCHARGE_SENSOR)
        except RuntimeError as e:
            return jsonify({"error": _("Unable to create the Sensor: %(error)s", error=e)}), 502
        try:
            sf_ds_id = _create("MultiDatastreams", _multi_ds_payload(
                sf_ds_name, cfg.STREAMFLOW_UNIT, sensor_sf_id, op_sf_id, qf_id,
                thing_id, {"observationProcedure": OBSERVATION_PROCEDURE, "foiId": foi_id}))
        except RuntimeError as e:
            return jsonify({"error": _("Unable to create the discharge Datastream: %(error)s",
                                      error=e)}), 502

    # phenomenonTime of a discharge = conductivity peak of its range
    discharge_obs = []
    for r_range, debit in zip(ranges, debits):
        df_range = _range_df(df, r_range)
        if df_range.empty:
            return jsonify({"error": _("No data in the range %(start)s -> %(end)s",
                                      start=r_range['start'], end=r_range['end'])}), 400
        peak_time = df_range.loc[df_range["result"].idxmax(), "date"]
        discharge_obs.append([peak_time.strftime("%Y-%m-%dT%H:%M:%SZ"), debit])

    r_sf_obs = _post_archive_observations(sf_ds_id, foi_id, discharge_obs)
    if not r_sf_obs.ok:
        return jsonify({"error": _("Error while posting the discharge: %(error)s", error=r_sf_obs.text)}), 502

    return jsonify({
        "ok": True,
        "cond_ds_id": cond_ds_id,
        "sf_ds_id": sf_ds_id,
        "n_conductivity_obs": len(df_obs),
        "n_discharge_obs": len(discharge_obs),
        "discharge_obs": discharge_obs,   # [[phenomenonTime, discharge], ...]
    })
