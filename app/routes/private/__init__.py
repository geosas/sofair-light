from flask import Blueprint

from app.config import Config

# Image extensions accepted for uploads (metadata, news, things).
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

private_bp = Blueprint('private', __name__)

# create blueprint and after import
from app.routes.private import (  # noqa: E402,F401
    metadata,
    config,
    news,
    things,
    drivers,
    import_data,
    qualification,
    softsensor,
    export,
)
