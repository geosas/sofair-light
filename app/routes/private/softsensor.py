from flask import render_template, request, jsonify
from flask_babel import gettext as _

from app.config import Config
from app.sta_tools import sta_client
from app.services.security import jwt_required_or_redirect
from app.driver_softSensor.manager import ScriptManagerSoftSensor

from app.routes.private import private_bp

# hook to compute + publish the derived datastream.
PRODUCER_KEY = 'softSensorProducer'


def _load_datastreams():
    """Archive MultiDatastreams with name/id/properties + their Thing (for elevation)."""
    params = {"$select": "name,id,properties",
              "$expand": "Thing($select=name,properties)"}
    r = sta_client.get("archive", "/MultiDatastreams", params=params)
    r.raise_for_status()
    return r.json()['value']


def _set_target_maxvalue(target_name, max_value):
    """Overwrite `maxValue` on the derived target, on BOTH the archive
    MultiDatastream and its partage Datastream (for rating-curve)"""
    out = {"archive": False, "partage": False}
    archive_response = sta_client.proxy_get("archive", "MultiDatastreams",
                                            params={"$select": "name,id,properties",
                                                    "$filter": f"name eq '{target_name}'"})
    archive_targets = archive_response.json().get('value', [])
    if not archive_targets:
        return out

    # Archive MultiDatastream
    target = archive_targets[0]
    target_properties = target.get('properties') or {}
    target_properties['maxValue'] = max_value
    patch_response = sta_client.patch("archive", f"/MultiDatastreams({target['@iot.id']})",
                                      json={"properties": target_properties})
    out["archive"] = bool(patch_response .ok)

    # Partage Datastream (via nameShare)
    name_share = target_properties.get('nameShare')
    if name_share:
        partage_response = sta_client.proxy_get("partage", "Datastreams",
                                                params={"$select": "name,id,properties",
                                                        "$filter": f"name eq '{name_share}'"})
        partage_datastreams = partage_response.json().get('value', [])
        if partage_datastreams:
            datastream = partage_datastreams[0]
            datastream_properties = datastream.get('properties') or {}
            datastream_properties['maxValue'] = max_value
            patch_response = sta_client.patch("partage", f"/Datastreams({datastream['@iot.id']})",
                                              json={"properties": datastream_properties})
            out["partage"] = bool(patch_response.ok)
    return out


@private_bp.get('/configure-softsensor')
@jwt_required_or_redirect()
def configure_softsensor():
    methods = ScriptManagerSoftSensor.get_metadata()
    try:
        datastreams = _load_datastreams()
    except Exception:
        return render_template('error.html', error=_("SensorThings service not active or unreachable")), 500

    # Derived (targets) vs candidate sources (the measured ones).
    targets = [d for d in datastreams
               if (d.get('properties') or {}).get('observationProcedure') == 'SoftSensor']
    sources = [d for d in datastreams
               if (d.get('properties') or {}).get('observationProcedure') != 'SoftSensor']

    # Existing associations (read from the sources' producer property).
    associations = []
    for d in datastreams:
        prod = (d.get('properties') or {}).get(PRODUCER_KEY)
        if prod:
            associations.append({"source": d['name'], "source_id": d['@iot.id'],
                                 "method": prod.get('method'),
                                 "target": prod.get('target'),
                                 "params": prod.get('params') or {}})

    return render_template('private/configure_softsensor.html',
                           methods=methods, targets=targets, sources=sources,
                           associations=associations)


@private_bp.post('/configure-softsensor')
@jwt_required_or_redirect()
def save_softsensor():
    """Create/remove a SoftSensor association by PATCHing the source datastream's
    `softSensorProducer` property. Body: {source_id, method, target, params} or
    {source_id, remove: true}."""
    data = request.get_json(silent=True) or {}
    try:
        source_id = int(data.get('source_id'))
    except (TypeError, ValueError):
        return jsonify({"error": _("Invalid source datastream")}), 400

    r = sta_client.get("archive", f"/MultiDatastreams({source_id})",
                       params={"$select": "properties"})
    if not r.ok:
        return jsonify({"error": _("SensorThings service not active or unreachable")}), 500
    props = r.json().get('properties') or {}

    if data.get('remove'):
        props.pop(PRODUCER_KEY, None)
    else:
        method = data.get('method')
        target = (data.get('target') or '').strip()
        if method not in ScriptManagerSoftSensor.get_scripts_name():
            return jsonify({"error": _("Unknown method")}), 400
        if not target:
            return jsonify({"error": _("Please select a derived datastream")}), 400
        # Keep only the params declared by the method's METADATA (numbers).
        meta = next((m for m in ScriptManagerSoftSensor.get_metadata()
                     if m['id'] == method), {})
        clean = {}
        for p in meta.get('params', []):
            v = (data.get('params') or {}).get(p['key'])
            if v in (None, ''):
                return jsonify({"error": _("Missing parameter %(k)s", k=p['key'])}), 400
            try:
                clean[p['key']] = float(v)
            except (TypeError, ValueError):
                return jsonify({"error": _("Parameter %(k)s must be a number", k=p['key'])}), 400
        props[PRODUCER_KEY] = {"method": method,
                               "target": target, "params": clean}

    r = sta_client.patch("archive", f"/MultiDatastreams({source_id})",
                         json={"properties": props})
    if not r.ok:
        return jsonify({"error": _("SensorThings service active but something gone wrong")}), 500

    result = {"msg": "ok"}
    # Methods that expose a validity range (for rating curve) overwrite the
    # derived target's partage maxValue with the computed bound (a * h_max^b).
    if not data.get('remove'):
        mod = ScriptManagerSoftSensor.load(method)
        if hasattr(mod, 'derived_max_value'):
            try:
                mv = mod.derived_max_value(clean)
                if mv is not None:
                    result['maxValue'] = mv
                    result['maxValue_applied'] = _set_target_maxvalue(
                        target, mv)
            except Exception as e:
                result['maxValue_error'] = str(e)
    return jsonify(result)
