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


def _thing_photos(properties):
    """All photo URLs of a Thing as a list (`image` str/list + legacy `url_photo`), http -> https."""
    photos = properties.get("image") or []
    if isinstance(photos, str):
        photos = [photos]
    photos = list(photos)
    legacy = properties.get("url_photo")
    if legacy and legacy not in photos:
        photos.append(legacy)
    return [p.replace("http://", "https://", 1) for p in photos]


def _preview_url(url_photo):
    """URL of the resized preview: <dir>/preview/resize_<file>."""
    url_parts = url_photo.split('/')
    return '/'.join(url_parts[:-1]) + '/preview/resize_' + url_parts[-1]


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
            properties = item.get("properties") or {}
            item["properties"] = properties
            photos = _thing_photos(properties)
            item["photo_count"] = len(photos)
            if photos:
                # The template reads `url_photo`: expose the first preview there
                properties["url_photo"] = _preview_url(photos[0])

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

        try:
            r = sta_client.get(
                "partage", f"/Things({idThing})", params=params)
        except:
            return jsonify({"error": _("SensorThings service not active or unreachable")}), 500
        if not r.ok:
            return jsonify({"error": _("SensorThings service not active or unreachable")}), 500

        propertiesThing = r.json().get('properties') or {}

        # `image` is the list STAV reads; https so it loads on https pages
        photos = _thing_photos(propertiesThing)
        propertiesThing.pop('url_photo', None)  # legacy key, merged into `image`
        new_photo = url_for(
            'static', filename="img/things/"+filename, _external=True, _scheme='https')
        if new_photo not in photos:
            photos.append(new_photo)
        propertiesThing['image'] = photos
        properties = {'properties': propertiesThing}

        try:
            r = sta_client.patch("partage", f"/Things({idThing})", json=properties)
        except:
            return jsonify({"error": _("SensorThings service not active or unreachable")}), 500
        if not r.ok:
            return jsonify({"error": _("SensorThings service active but something gone wrong")}), 500
    else:
        return jsonify({"error": _("Invalid file name")}), 400

    return jsonify({"msg": "ok",
                    "url_photo": _preview_url(new_photo),
                    "photo_count": len(photos)})


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
              "$expand": "Locations($select=name,location),Datastreams($select=name,phenomenonTime,description;$expand=Sensor($select=name,metadata),ObservedProperty($select=name,definition))"
              }

    try:
        r = sta_client.get("partage", f"/Things({idThing})", params=params)
    except:
        return render_template('error.html', error=_("SensorThings service not active or unreachable")), 500
    if not r.ok:
        return render_template('error.html', error=_("SensorThings service not active or unreachable")), 500

    data = r.json()
    properties = data.get("properties") or {}
    data["properties"] = properties
    data["photos"] = _thing_photos(properties)

    return render_template('private/thing_info_id.html', thing=data)
