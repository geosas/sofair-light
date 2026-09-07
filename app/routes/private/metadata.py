import os
import json
import uuid
from datetime import datetime

from flask import render_template, request, jsonify, current_app, redirect, url_for
from werkzeug.utils import secure_filename
from flask_babel import gettext as _

from app.config import Config
from app.services.security import jwt_required_or_redirect
from app.services.news_handler import generate_article
from app.services.utils import allowed_file, resize_image

from app.routes.private import private_bp, ALLOWED_EXTENSIONS


def _metadata_exists():
    """The observatory metadata is a singleton: it exists as soon as a record
    has been created (a non-empty `name`). Used to block any re-creation."""
    md = Config.APP_METADATA
    return bool(md and (md.get('name') or '').strip())


@private_bp.get('/createMetadata')
@jwt_required_or_redirect()
def createMetadata():
    # if the record already exists
    # redirect to the existing metadata instead.
    if _metadata_exists():
        return redirect(url_for('public.metadata'))
    # Service access point (connectPoint ISO 19119): STA "partage" proxy
    url_service = Config.STALT_partage_proxyname.rstrip("/") + "/v1.1/"
    # Default the creation date to today (YYYY-MM-DD for <input type="date">)
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template('private/createMetadata.html',
                           url_service=url_service, today=today)


@private_bp.post('/createMetadata')
@jwt_required_or_redirect()
def postMetadata():
    """ Need to validate with pydantic to avoid issues (when field are ok)

    a single observatory metadata record. Any re-creation is
    refused (otherwise each submit would stack another launch article).
    for modification change the json file in /app/static/metadata/
    """
    if _metadata_exists():
        return jsonify({"error": _(
            "Observatory metadata already exists; it can only be created once."
        )}), 409

    data = request.form.to_dict()
    data['Observatory creation'] = data.pop('date_creation')
    data['Record creation'] = datetime.now().strftime("%Y-%m-%d")
    data['id'] = str(uuid.uuid5(uuid.NAMESPACE_DNS, data['name']))

    # ISO 19119 service metadata

    data['serviceType'] = 'SensorThings'
    data['serviceTypeVersion'] = '1.1'
    data['status'] = (data.get('status') or 'onGoing').strip()
    # connectPoint: access point derived from the config (the front field is read-only)
    data['connectPoint'] = Config.STALT_partage_proxyname.rstrip(
        "/") + "/v1.1/"

    # Temporal extent (EX_TemporalExtent)
    data['temporalStart'] = (data.pop('temporal_start', '') or '').strip()
    data['temporalEnd'] = (data.pop('temporal_end', '') or '').strip()

    # Topic / keywords
    data['topicCategory'] = (data.get('topicCategory') or '').strip()
    kw = (data.get('keywords') or '').strip()
    data['keywords'] = [s.strip() for s in kw.split(',') if s.strip()]

    # License (MD_LegalConstraints, useConstraints)
    data['license'] = (data.get('license') or '').strip()

    data['metadata_url'] = (data.get('metadata_url') or '').strip()

    if 'image_obs' not in request.files:
        return jsonify({"error": _("No image sent")}), 400

    file = request.files['image_obs']
    if file.filename == '':
        return jsonify({"error": _("Invalid file name")}), 400

    if file and allowed_file(file.filename, ALLOWED_EXTENSIONS):
        extension = '.png'
        image_path = os.path.join(
            current_app.static_folder, 'img', 'news', 'observatoire' + extension)
        image_path_preview = os.path.join(
            current_app.static_folder, 'img', 'news', 'preview', 'observatoire_resize' + extension)

        resize_image(file, image_path, 750, 750)
        resize_image(image_path, image_path_preview, 350, 350)

    Config.APP_METADATA = data
    file_path = os.path.join(current_app.static_folder,
                             'metadata', 'metadata_iso_19119.json')

    with open(file_path, 'w', encoding="utf-8") as json_file:
        json.dump(data, json_file, indent=4)

    # news: the launch article title
    title = _("Platform launch for the observatory")
    summary = ""
    body = data['resume']
    generate_article(title, summary, body,  'observatoire' +
                     extension, 'observatoire_resize' + extension)

    return jsonify({"url": url_for("public.metadata")})
