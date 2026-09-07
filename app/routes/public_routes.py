from flask_babel import gettext as _
from flask import Blueprint, render_template, redirect, url_for

from app.config import Config
from app.services.security import inject_authentication_status
# Blueprint for the public routes
home_bp = Blueprint('public', __name__)


@home_bp.get('/')
def home():
    if bool(Config.APP_METADATA) is False:
        if inject_authentication_status()['is_authenticated']:
            print("NEED TO CREATE METADATA")
            return redirect(url_for("private.createMetadata"))
    if bool(Config.APP_CONFIG_STA) is False:
        if inject_authentication_status()['is_authenticated']:
            print("NEED TO CREATE CONFIG")
            return redirect(url_for("private.createConfig"))

    return render_template('public/metadata.html', metadata=Config.APP_METADATA)


@home_bp.get('/metadata')
def metadata():

    return render_template('public/metadata.html', metadata=Config.APP_METADATA)


@home_bp.get('/news')
def news():

    return render_template('public/news.html', json_article=Config.APP_NEWS)


@home_bp.get('/news/<news_id>')
def news_article(news_id):
    article = Config.APP_NEWS[news_id]
    return render_template('public/news_article.html', article=article)
