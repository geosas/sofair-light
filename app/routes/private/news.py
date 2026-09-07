import os

from flask import render_template, request, jsonify, current_app, url_for
from werkzeug.utils import secure_filename
from flask_babel import gettext as _

from app.services.security import jwt_required_or_redirect
from app.services.news_handler import generate_article
from app.services.utils import allowed_file, resize_image

from app.routes.private import private_bp, ALLOWED_EXTENSIONS


@private_bp.get('/createNews')
@jwt_required_or_redirect()
def createNEws():
    return render_template('private/createNews.html')


@private_bp.post('/createNews')
@jwt_required_or_redirect()
def postNews():

    data = request.form.to_dict()

    title = data['titre']
    summary = data['resume']
    body = data['article']

    if 'image_obs' not in request.files:
        return jsonify({"error": _("No image sent")}), 400

    file = request.files['image_obs']

    if file.filename == '':
        return jsonify({"error": _("Invalid file name")}), 400

    if file and allowed_file(file.filename, ALLOWED_EXTENSIONS):
        filename = secure_filename(file.filename)
        image_path = os.path.join(
            current_app.static_folder, 'img', 'news', filename)
        image_path_preview = os.path.join(
            current_app.static_folder, 'img', 'news', 'preview', 'resize_' + filename)

        resize_image(file, image_path, 750, 750)
        resize_image(image_path, image_path_preview, 350, 350)

    article_id = generate_article(title, summary, body, os.path.basename(
        image_path), os.path.basename(image_path_preview))

    return jsonify({"url": url_for("public.news")+"/"+article_id})
