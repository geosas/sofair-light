"""
Observatory configuration : create and add STA object easely
"""

from flask import render_template
from werkzeug.utils import secure_filename

from app.config import Config
from app.services.security import jwt_required_or_redirect

from app.routes.private import private_bp


@private_bp.get('/configuration-obs')
@jwt_required_or_redirect()
def createConfig():

    return render_template('private/createConfigObs.html', configObs=Config.APP_CONFIG_STA,
                           name_obs=secure_filename(Config.APP_METADATA['name']))


@private_bp.post('/configuration-obs')
@jwt_required_or_redirect()
def postConfig():
    return "ok"
