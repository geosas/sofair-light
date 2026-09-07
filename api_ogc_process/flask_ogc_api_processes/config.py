"""
Configuration for the OGC API - Processes engine.

The engine is *config-injected*: nothing in the routing/utility layer reads a
global ``Config`` object anymore. A host application passes its own config
(object or dict) to :func:`flask_ogc_api_processes.create_ogc_blueprint`; anything it omits falls
back to :class:`DefaultConfig`.
"""
import os
from types import SimpleNamespace

basedir = os.path.abspath(os.path.dirname(__file__))


class DefaultConfig:
    """Sensible defaults for a standalone deployment."""

    BASEDIR = basedir

    APP_TITLE = "OGC API - Processes"
    URL_PROJET = "http://127.0.0.1:5000"

    # Flask secret key (override in production via the SECRET_KEY env var).
    SECRET_KEY = os.environ.get("SECRET_KEY") or "change-me-in-production"

    # Number of concurrent async process executions.
    THREAD_NUMBER = 2

    # SSRF allowlist for inputs-by-reference (SECURITY_AUDIT.md #1).
    #   None                  -> no allowlist; any *public* host is fetchable
    #                            (internal/loopback/link-local IPs still blocked).
    #   list/set of hostnames -> only these hosts may be fetched by reference.
    #   []  (empty list)      -> inputs-by-reference DISABLED entirely (every href rejected).
    REF_ALLOWED_HOSTS = None

    # Max size (bytes) of a single fetched reference; larger responses are rejected
    # while streaming, before they are held in memory (SECURITY_AUDIT.md #2).
    MAX_REF_BYTES = 10 * 1024 * 1024  # 10 MiB

    # Max size (bytes) of an incoming request body; Flask returns 413 above it
    # (SECURITY_AUDIT.md #3). Applied by ``create_app``; embedding hosts set their own.
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MiB

    # Max number of inputs-by-reference (href) resolved per request, capping how
    # much SSRF/fetch work a single request can trigger (SECURITY_AUDIT.md #4).
    MAX_REFERENCES_PER_REQUEST = 20

    # Max number of async jobs in flight (running + queued) before new
    # ``respond-async`` requests are rejected with 429 (SECURITY_AUDIT.md #5).
    MAX_ASYNC_QUEUE = 100


# Backward-compatible alias (legacy code imported ``Config``).
Config = DefaultConfig


def build_service_info(url_projet: str, app_title: str) -> dict:
    """Build the landing-page service description for a given base URL/title.

    Built dynamically so the advertised links always reflect the *injected*
    base URL rather than a hard-coded one.
    """
    return {
        "@context": "https://schema.org",
        "@type": "WebAPI",
        "@id": url_projet,
        "url": url_projet,
        "title": app_title,
        "description": "API compliant with the OGC API - Processes standard, enabling the execution of processing tasks.",
        "keywords": ["Process", "OGC"],
        "termsOfService": "https://www.gnu.org/licenses/gpl-3.0.html",
        "license": "https://www.gnu.org/licenses/gpl-3.0.html",
        "provider": {
            "@type": "Organization",
            "name": "GéoSAS",
            "url": "https://geosas.fr",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "UMR SAS - INRAE - Institut Agro",
                "postalCode": 35042,
                "addressLocality": "Rennes",
                "addressCountry": "FR",
            },
            "contactPoint": {
                "@type": "ContactPoint",
                "email": "geosas_adm@framalistes.org",
                "contactType": "pointOfContact",
            },
        },
        "links": [
            {"href": url_projet, "rel": "self", "type": "application/json", "title": "This document"},
            {"href": url_projet + "/api", "rel": "service-desc",
             "type": "application/vnd.oai.openapi+json;version=3.0",
             "title": "API definition for this endpoint as JSON (OpenAPI 3.0)"},
            {"href": url_projet + "/api?f=html", "rel": "service-doc", "type": "text/html",
             "title": "API definition for this endpoint as HTML (Swagger UI)"},
            {"href": url_projet + "/conformance",
             "rel": "http://www.opengis.net/def/rel/ogc/1.0/conformance",
             "type": "application/json", "title": "OGC API conformance classes"},
            {"href": url_projet + "/processes",
             "rel": "http://www.opengis.net/def/rel/ogc/1.0/processes",
             "type": "application/json", "title": "Processes"},
            {"href": url_projet + "/jobs",
             "rel": "http://www.opengis.net/def/rel/ogc/1.0/job-list",
             "type": "application/json", "title": "Jobs"},
        ],
    }


# Attributes the engine reads from a config object, with their default source.
_CONFIG_ATTRS = (
    "APP_TITLE", "URL_PROJET", "SECRET_KEY", "THREAD_NUMBER", "REF_ALLOWED_HOSTS",
    "MAX_REF_BYTES", "MAX_CONTENT_LENGTH", "MAX_REFERENCES_PER_REQUEST", "MAX_ASYNC_QUEUE",
)


def resolve_config(config=None):
    """Normalize a user-supplied config (object, dict or None) into a namespace.

    Any attribute missing from the user config falls back to :class:`DefaultConfig`.
    """
    if config is None:
        source = {}
    elif isinstance(config, dict):
        source = dict(config)
    else:
        source = {attr: getattr(config, attr) for attr in _CONFIG_ATTRS if hasattr(config, attr)}
        # carry an explicit SERVICE_INFO override if the host provides one
        if hasattr(config, "SERVICE_INFO"):
            source["SERVICE_INFO"] = getattr(config, "SERVICE_INFO")

    resolved = {attr: source.get(attr, getattr(DefaultConfig, attr)) for attr in _CONFIG_ATTRS}
    if "SERVICE_INFO" in source:
        resolved["SERVICE_INFO"] = source["SERVICE_INFO"]
    return SimpleNamespace(**resolved)
