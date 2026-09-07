from flask import request, redirect, url_for, has_request_context
from apiflask import APIFlask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, verify_jwt_in_request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_babel import Babel

from .services.security import inject_authentication_status

# from flask_cors import CORS
import os
# from werkzeug.middleware.proxy_fix import ProxyFix
# app.wsgi_app = ProxyFix(
#    app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
# )


# Extension initialisation
db = SQLAlchemy()
jwt = JWTManager()
babel = Babel()
limiter = Limiter(
    get_remote_address,  # Rate-limit per IP address
    # default_limits=["5 per minute"]
)

# Sensitive OGC endpoints to protect with the host's JWT: the
# flask_ogc_api_processes engine enforces NO auth at all, it is up to the host
# to wire it back. The discovery GETs (landing, conformance, processes, api)
# stay open (Grafana/STAV/OGC clients), as they were before the migration.
_OGC_PROTECTED_ENDPOINTS = {
    "flask_ogc_api_processes.execute_process_route",
    "flask_ogc_api_processes.get_jobs",
    "flask_ogc_api_processes.get_job_status",
    "flask_ogc_api_processes.get_job_results",
    "flask_ogc_api_processes.delete_job",
    "flask_ogc_api_processes.purge_job",
}


def _build_ogc_blueprint(app):
    """Build the OGC API - Processes blueprint from the reusable engine,
    injecting our processes, a config derived from Config, a standalone SQLite
    job store (persisted inside the project) and the host's auth guard.
    """
    from flask_ogc_api_processes import create_ogc_blueprint, SQLiteJobStore
    from app.ogc_process.registry import HOST_PROCESSES
    from app.config import Config

    # Standalone SQLite job store, kept inside the project (not in the package /
    # site-packages): DB + result files under app/ogc_process/job_store_data/.
    store_dir = os.path.join(os.path.dirname(__file__),
                             "ogc_process", "job_store_data")
    job_store = SQLiteJobStore(
        db_path=os.path.join(store_dir, "jobs.db"),
        results_dir=os.path.join(store_dir, "results"),
    )

    ogc_config = {
        "APP_TITLE": Config.APP_TITLE,
        # Base of the generated links (job/process): the host's /ogc-processes mount.
        "URL_PROJET": Config.URL_PROJET.rstrip("/") + "/ogc-processes",
        "SECRET_KEY": Config.SECRET_KEY,
        "THREAD_NUMBER": Config.THREAD_NUMBER,
    }

    bp = create_ogc_blueprint(HOST_PROCESSES, config=ogc_config,
                              job_store=job_store, url_prefix="/ogc-processes")

    bp.enable_openapi = False

    @bp.before_request
    def _ogc_auth_guard():
        # Mirrors jwt_required_or_redirect() on the sensitive endpoints.
        if request.endpoint in _OGC_PROTECTED_ENDPOINTS:
            try:
                verify_jwt_in_request(locations="cookies")
            except Exception:
                return redirect(url_for("auth.loginPage"))

    return bp


def create_app():
    # Application creation (APIFlask = Flask + OpenAPI/Swagger, 100% compatible)
    app = APIFlask(__name__, title="SOFAIR Light API", version="1.0.0",
                   docs_path="/docs", spec_path="/openapi.json")

    # Configuration loading
    app.config.from_object('app.config.Config')

    # Guard: refuse to start while a secret still holds the placeholder value
    # published in the repository (forgeable JWT, wide-open OTT sensor…).
    # Bypass with STALT_ALLOW_INSECURE_DEFAULTS=1 for local development.
    from app.services.startup_checks import check_secrets
    check_secrets(app)

    # Extension initialisation
    db.init_app(app)
    jwt.init_app(app)
    limiter.init_app(app)

    # Wires the JWT callback that reloads the User from the token (feeds
    # current_user). Called explicitly -> no "ghost" import someone could delete
    # by mistake. The stored identity is the username, so no identity_loader.
    from app.services.security import register_jwt_callbacks
    register_jwt_callbacks(jwt)

    # ORCID SSO (federated login): initialises the OAuth/OIDC client. Without
    # configured client credentials the provider is not registered and the
    # ORCID routes answer 404 (local auth only).
    from app.services.orcid import register_orcid
    register_orcid(app)

    # i18n: the language comes from the `lang` cookie (set by the /set-lang/<code>
    # switcher). Otherwise we fall back to BABEL_DEFAULT_LOCALE (see Config).
    def _select_locale():
        default = app.config.get("BABEL_DEFAULT_LOCALE", "fr")
        # Outside a request (the `create-admin` CLI, async OGC threads…) there is
        # neither a cookie nor a `request`: fall back to the default locale
        # without touching `request` (otherwise RuntimeError "Working outside of
        # request context").
        if not has_request_context():
            return default
        supported = app.config.get("BABEL_SUPPORTED_LOCALES", ["fr", "en"])
        lang = request.cookies.get("lang")
        if lang in supported:
            return lang
        return default

    babel.init_app(app, locale_selector=_select_locale)

    @app.get("/set-lang/<lang_code>")
    def set_lang(lang_code):
        # Language switch: remember the choice in a cookie and go back to the
        # previous page. GET on purpose (it is a plain link in the navbar).
        supported = app.config.get("BABEL_SUPPORTED_LOCALES", ["fr", "en"])
        response = redirect(request.referrer or "/")
        if lang_code in supported:
            response.set_cookie("lang", lang_code,
                                max_age=60 * 60 * 24 * 365, samesite="Lax")
        return response

    @app.context_processor
    def _inject_locale():
        # Expose the current locale to the templates (active state of the switcher).
        from flask_babel import get_locale
        return {"current_locale": str(get_locale() or "")}

    app.context_processor(inject_authentication_status)

    @app.before_request
    def protect_api_docs():
        # OpenAPI docs (/docs Swagger + /openapi.json) reserved for authenticated
        # users: we do not want to expose the endpoints publicly.
        if request.path in (app.spec_path, app.docs_path):
            try:
                verify_jwt_in_request()          # reads the JWT from the cookie
            except Exception:
                return redirect(url_for("auth.loginPage"))

    @app.error_processor
    def normalize_errors(error):
        # Keeps the historical {msg, errors:[{field,message}]} shape for ALL
        # APIFlask errors (422 validation, abort(), HTTP errors) -> incremental
        # migration without breaking the front-ends. Typical detail:
        # {"json": {"field": ["msg"]}}
        errors = []
        detail = error.detail if isinstance(error.detail, dict) else {}
        for _location, fields in detail.items():
            if isinstance(fields, dict):
                for field, msgs in fields.items():
                    for m in (msgs if isinstance(msgs, (list, tuple)) else [msgs]):
                        errors.append({"field": field, "message": m})
        return {"msg": error.message, "errors": errors}, error.status_code, error.headers

    # Route registration
    from app.routes.auth import auth_bp
    from app.routes.public_routes import home_bp
    from app.routes.private import private_bp
    from app.routes.sta_routes import sta_bp
    from app.routes.tarage import tarage_bp
    from app.routes.stav_routes import stav_bp
    from app.routes.sensors_routes import sensors_bp
    from app.config import Config

    limiter.limit("20 per minute")(auth_bp)
    app.register_blueprint(home_bp, url_prefix="/")
    app.register_blueprint(auth_bp, url_prefix="/auth", limiter=limiter)
    app.register_blueprint(private_bp, url_prefix="/private")

    app.register_blueprint(_build_ogc_blueprint(app))
    app.register_blueprint(sta_bp, url_prefix="/sta")
    #app.register_blueprint(tarage_bp, url_prefix="/tarage")
    # HTTPS ingestion for non-LoRaWAN sensors; security is built into each driver
    app.register_blueprint(sensors_bp, url_prefix="/sensors")
    # STAV front served under the root = observatory name (same origin -> auth OK)
    app.register_blueprint(stav_bp, url_prefix=f"/{Config.STALT_observatoire}")

    # Expose the observatory name to every template (links to STAV)
    app.context_processor(lambda: {"observatoire": Config.STALT_observatoire})

    # CLI commands (e.g. `flask --app run create-admin`)
    from app.cli import register_cli
    register_cli(app)

    with app.app_context():
        db.create_all()

    return app
