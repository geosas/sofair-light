"""
Modify thing and add photo
"""
import os

from flask import render_template, request, jsonify, current_app, url_for
from werkzeug.utils import secure_filename
from flask_babel import gettext as _

from app.config import Config
from app.sta_tools import sta_client
from app.services.security import jwt_required_or_redirect
from app.services.utils import allowed_file, resize_image

from app.routes.private import private_bp, ALLOWED_EXTENSIONS


@private_bp.get('/thingInfo')
@jwt_required_or_redirect()
def thing_info():

    params = {"$select": "name,description,properties,id"}

    try:
        r = sta_client.get("partage", "/Things", params=params)
    except:
        return render_template('error.html', error=_("SensorThings service not active or unreachable")), 500
    if not r.ok:
        return render_template('error.html', error=_("SensorThings service not active or unreachable")), 500
    try:
        data = r.json()['value']

        for item in data:
            properties = item.get("properties", {})
            url_photo = properties.get("url_photo")
            if url_photo:
                url_parts = url_photo.split('/')
                filename = url_parts[-1]
                new_url = '/'.join(url_parts[:-1]) + \
                    '/preview/resize_' + filename
                properties["url_photo"] = new_url  # Update the URL

        return render_template('private/thing_info.html', things=data)
    except:
        return render_template('error.html', error=_("SensorThings service active but something gone wrong")), 500


@private_bp.post('/postThingInfo')
@jwt_required_or_redirect()
def post_thing_info():
    print("add photo to thing")

    data = request.form.to_dict()
    idThing = data['id']

    if 'thing_photo' not in request.files:
        return jsonify({"error": _("No image sent")}), 400

    file = request.files['thing_photo']

    if file.filename == '':
        return jsonify({"error": _("Invalid file name")}), 400

    if file and allowed_file(file.filename, ALLOWED_EXTENSIONS):
        filename = secure_filename(file.filename)
        image_path = os.path.join(
            current_app.static_folder, 'img', 'things', filename)
        image_path_preview = os.path.join(
            current_app.static_folder, 'img', 'things', 'preview', 'resize_' + filename)

        resize_image(file, image_path, 750, 750)
        resize_image(image_path, image_path_preview, 350, 350)
        params = {"$select": "properties"}
        r = sta_client.get("partage", f"/Things({idThing})", params=params)

        try:
            r = sta_client.get(
                "partage", f"/Things({idThing})", params=params)
        except:
            return jsonify({"error": "SensorThings service not active or unreachable"}), 500
        if not r.ok:
            return jsonify({"error": "SensorThings service not active or unreachable"}), 500

        propertiesThing = r.json()['properties']

        propertiesThing['url_photo'] = request.host_url[:-1] + url_for(
            'static', filename="img/things/"+filename)
        properties = {'properties': propertiesThing}

        r = sta_client.patch("partage", f"/Things({idThing})", json=properties)
        # if r.ok
    url_parts = propertiesThing['url_photo'].split('/')
    filename = url_parts[-1]
    new_url = '/'.join(url_parts[:-1]) + '/preview/resize_' + filename

    return jsonify({"msg": "ok",
                    "url_photo": new_url})


@private_bp.post('/patchThingDescription')
@jwt_required_or_redirect()
def patch_thing_description():
    """Edit a Thing's description on the 'partage' STA (partial PATCH: only the
    'description' field is sent, everything else on the Thing is left intact)."""
    data = request.get_json(silent=True) or {}
    try:
        id_thing = int(data.get('id'))
    except (TypeError, ValueError):
        return jsonify({"error": _("Invalid Thing id")}), 400
    description = (data.get('description') or '').strip()

    try:
        r = sta_client.patch("partage", f"/Things({id_thing})",
                             json={"description": description})
    except Exception:
        return jsonify({"error": _("SensorThings service not active or unreachable")}), 500
    if not r.ok:
        return jsonify({"error": _("SensorThings service active but something gone wrong")}), 500

    return jsonify({"msg": "ok", "description": description})


@private_bp.get('/thingInfo(<idThing>)')
@jwt_required_or_redirect()
def thing_info_id(idThing):

    params = {"$select": "name,description,properties,id",
              "$expand": "Locations($select=name,location),Datastreams($select=name,phenomenonTime,description;$expand=Sensor($select=name,metadata);$expand=ObservedProperty($select=name,definition))"
              }

    try:
        r = sta_client.get("partage", f"/Things({idThing})", params=params)
    except:
        return render_template('error.html', error=_("SensorThings service not active or unreachable")), 500
    if not r.ok:
        return render_template('error.html', error=_("SensorThings service not active or unreachable")), 500

    data = r.json()

    return render_template('private/thing_info_id.html', thing=data)
