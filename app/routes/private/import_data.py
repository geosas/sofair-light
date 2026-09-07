from flask import render_template
from flask_babel import gettext as _

from app.sta_tools import sta_client
from app.services.security import jwt_required_or_redirect

from app.driver_veloProcessing.manager import ScriptManagerVeloProcessing

from app.routes.private import private_bp


@private_bp.get('/import-data')
@jwt_required_or_redirect()
def import_data():
    driver = ScriptManagerVeloProcessing.get_metadata()

    try:
        params = {"$select": "name",
                      "$filter": "properties/observationProcedure eq 'veloProcessing'",
                      "$expand": "Thing($select=description),Sensor($select=name)"
                      }
        r = sta_client.get("archive", "/MultiDatastreams", params=params)
    except:
        return render_template('error.html', error=_("SensorThings service not active or unreachable")), 500
    if not r.ok:
        return render_template('error.html', error=_("SensorThings service not active or unreachable")), 500
    data = r.json()['value']
    info = {}
    for i in data:
        name = i['name'].split("_")[0]
        if name in info:
            info[name]['sensor'].append(i['Sensor']['name'])
            continue
        info[name] = {"description": i['Thing']['description'],
                      "sensor": [i['Sensor']['name']]
                      }

    return render_template('private/import_data.html', driver=driver, pdm=info)
