"""
Standalone entry point.

Builds a standalone Flask application wired with the example processes, a default
config and the autonomous SQLite job store. It serves the OGC API plus the
per-process OpenAPI spec / Swagger UI at ``/api`` (``?f=json`` for the spec,
``?f=html`` for the interactive UI), which the engine generates by looping over the
injected process registry. This is what ``run.py`` uses; it is also handy for tests.
Embedding hosts should call ``create_ogc_blueprint`` directly instead.
"""
import logging
import os

from flask import Flask

from .config import DefaultConfig, resolve_config
from .routes.ogc_process_routes import create_ogc_blueprint
from .ogc_process.registry import EXAMPLE_PROCESSES

logger = logging.getLogger(__name__)

_DEFAULT_SECRET_KEY = "change-me-in-production"


def _check_secret_key(secret_key):
    """Warn (or refuse to start in production) if the default SECRET_KEY is used.

    SECURITY_AUDIT.md #8: the default key is public; a real deployment must set the
    ``SECRET_KEY`` env var. In production (``FLASK_ENV``/``APP_ENV=production``) the
    default is a hard error rather than a warning.
    """
    if secret_key != _DEFAULT_SECRET_KEY:
        return
    env = (os.environ.get("FLASK_ENV") or os.environ.get("APP_ENV") or "").lower()
    if env == "production":
        raise RuntimeError(
            "Refusing to start in production with the default SECRET_KEY; "
            "set the SECRET_KEY environment variable to a secret random value.")
    logger.warning(
        "Using the default insecure SECRET_KEY. Set the SECRET_KEY environment "
        "variable to a random secret before deploying.")


def create_app(config=None, job_store=None, processes=None):
    """Create a standalone Flask app serving the OGC API - Processes (docs at /api)."""
    cfg = resolve_config(config)

    app = Flask(__name__)

    _check_secret_key(cfg.SECRET_KEY)

    # Expose a couple of values templates read from ``app.config``.
    app.config["APP_TITLE"] = cfg.APP_TITLE
    app.config["SECRET_KEY"] = cfg.SECRET_KEY
    # Cap the request body so a huge POST can't exhaust memory (SECURITY_AUDIT.md #3).
    app.config["MAX_CONTENT_LENGTH"] = cfg.MAX_CONTENT_LENGTH

    if processes is None:
        processes = EXAMPLE_PROCESSES

    bp = create_ogc_blueprint(processes, config=config, job_store=job_store)
    app.register_blueprint(bp)

    # Surface engine internals for tests/introspection.
    app.ogc_job_store = bp.ogc_job_store
    app.ogc_running = bp.ogc_running
    return app
