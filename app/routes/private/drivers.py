import os

from flask import render_template, request, jsonify, send_file
from flask_babel import gettext as _

from app.config import Config
from app.sta_tools import sta_client
from app.services.security import jwt_required_or_redirect

from app.driver_veloProcessing.manager import ScriptManagerVeloProcessing
from app.driver_LoRaWAN.manager import ScriptManagerLoRaWAN

from app.routes.private import private_bp


@private_bp.get('/driverInfo')
@jwt_required_or_redirect()
def driver_info():

    data = ScriptManagerVeloProcessing.get_metadata()

    return render_template('private/driver_sta_info.html', driver=data)


@private_bp.get('/driverTemplate')
@jwt_required_or_redirect()
def driver_template():
    """Download an empty driver skeleton (driver_template.py) to start from."""
    path = os.path.join(Config.BASEDIR, 'driver_veloProcessing',
                        'driver_template.py')
    return send_file(path, as_attachment=True,
                     download_name='driver_template.py',
                     mimetype='text/x-python')


@private_bp.post('/testDriver/<driver_name>')
@jwt_required_or_redirect()
def test_driver(driver_name):
    """Live-test a VeloProcessing driver: run it on a user uploaded file and
    return a preview of the resulting DataFrame (columns + first rows), or the
    error. No data are publish to STA"""
    import io
    import pandas as pd

    if driver_name not in ScriptManagerVeloProcessing.get_scripts_name():
        return jsonify({"error": _("Unknown driver")}), 404

    if 'test_file' not in request.files:
        return jsonify({"error": _("No file sent")}), 400
    file = request.files['test_file']
    if file.filename == '':
        return jsonify({"error": _("Invalid file name")}), 400

    # Observed property names normally come from the STA config. For a test run
    # the tester may type them (comma-separated), else we pass an empty list.
    obs = [s.strip() for s in (request.form.get(
        'observedProperties') or '').split(',') if s.strip()]

    # Re-readable in-memory copy of the upload for the driver.
    file_like = io.BytesIO(file.read())

    try:
        df = ScriptManagerVeloProcessing.run_script(
            driver_name, file_like, obs)
    except Exception as e:
        return jsonify({"error": _("The driver failed on this file."),
                        "exception": str(e)}), 400

    if not isinstance(df, pd.DataFrame):
        return jsonify({"error": _("The driver did not return a pandas DataFrame."),
                        "exception": type(df).__name__}), 400

    preview = df.head(10).astype(str)
    return jsonify({
        "msg": "ok",
        "columns": [str(c) for c in df.columns],
        "rows": preview.values.tolist(),
        "nrows": int(len(df)),
    })


@private_bp.get('/lorawanInfo')
@jwt_required_or_redirect()
def lorawan_info():

    params = {"$select": "name,description,properties,id",
              "$filter": "properties/observationProcedure eq 'LoRaWAN'",
              "$expand": "Sensor($select=name)"
              }

    try:
        r = sta_client.get("archive", "/MultiDatastreams", params=params)
    except:
        return render_template('error.html', error=_("SensorThings service not active or unreachable")), 500
    if not r.ok:
        return render_template('error.html', error=_("SensorThings service not active or unreachable")), 500
    data = r.json()['value']

    driver, identifiers, examples = ScriptManagerLoRaWAN.get_metadata()
    driver = [i['driver'] for i in driver]

    return render_template('private/lorawan_sta_info.html', datastreams=data,
                           driver=driver, identifiers=identifiers, examples=examples)


@private_bp.post('/lorawanInfo')
@jwt_required_or_redirect()
def post_lorawan_info():
    try:
        data = request.json
        print(data)
    except Exception as e:
        print(e)
        return jsonify({"error": str(e)}), 500

    idD = data['id']
    data.pop('id')
    params = {"$select": "properties,id"}

    try:
        r = sta_client.get(
            "archive", f"/MultiDatastreams({idD})", params=params)
    except:
        return jsonify({"error": "SensorThings service not active or unreachable"}), 500
    if not r.ok:
        return jsonify({"error": "SensorThings service not active or unreachable"}), 500

    propertiesMultiD = r.json()['properties']

    propertiesMultiD['LoRaWAN'] = data
    propertiesMultiD = {"properties": propertiesMultiD}
    r = sta_client.patch(
        "archive", f"/MultiDatastreams({idD})", json=propertiesMultiD)
    # if r.ok
    print(r.ok)
    print(r.text)
    return jsonify({"msg": "ok"}), 200


@private_bp.post('/lorawanDriver')
@jwt_required_or_redirect()
def test_lorawan_driver():
    data = request.json or {}
    driver = data.get('driver')
    identifier = data.get('identifier')
    payload = (data.get('payload') or '').strip()

    if not payload:
        return jsonify({"error": _("Please enter a payload to test.")}), 400

    try:
        # Live decode of the user-provided hex payload via the driver's run().
        ScriptManagerLoRaWAN.scripts = ScriptManagerLoRaWAN.get_scripts_name()
        decoded = ScriptManagerLoRaWAN.run_script(driver, payload, identifier)
    except Exception as e:
        print(e)
        return jsonify({"error": str(e)}), 500

    return jsonify({"msg": "ok", "decoded": str(decoded)}), 200
