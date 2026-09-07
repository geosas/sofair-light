import os
import json

basedir = os.path.abspath(os.path.dirname(__file__))


def _load_json(path, default=None):
    """Load a JSON file; if it does not exist, create it with `default` and return it.

    Avoids breaking startup on first use (no record created yet). For the
    metadata, the `{}` default (empty dict) triggers the redirect to the
    creation form in public_routes.
    """
    if default is None:
        default = {}
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(default, file, indent=4)
        return default
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


class Config:

    OPENAPI_VERSION = '3.1.0'

    APP_METADATA = _load_json(
        os.path.join(basedir, 'static', 'metadata', 'metadata_iso_19119.json'))
    APP_NEWS = _load_json(
        os.path.join(basedir, 'data', 'news', 'news.json'))
    APP_CONFIG_STA = _load_json(
        os.path.join(basedir, 'data', 'configSTA', 'config_STA.json'))

    BASEDIR = basedir

    APP_TITLE = 'City Orchestra'
    URL_PROJET = 'http://127.0.0.1:5000'

    
    LICENSE_URL = 'https://www.gnu.org/licenses/gpl-3.0.html'
    SOURCE_URL = os.environ.get(
        'SOURCE_URL') or 'https://github.com/geosas/sofair-light'

    # Internationalisation (Flask-Babel). Language shown when the user has not
    # chosen yet (no `lang` cookie). Set it to 'en' for an international
    # instance (e.g. a GitHub showcase): this is the only setting to change.
    BABEL_DEFAULT_LOCALE = 'en'
    BABEL_SUPPORTED_LOCALES = ['fr', 'en']
    BABEL_TRANSLATION_DIRECTORIES = 'translations'

    # Flask secret key (change it in production)
    SECRET_KEY = os.environ.get(
        'SECRET_KEY') or 'une_clé_secrète_très_sécurisée'

    # SQLite database configuration
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(basedir, 'database.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # JWT configuration (optional)
    JWT_SECRET_KEY = os.environ.get(
        'JWT_SECRET_KEY') or 'une_clé_jwt_sécurisée'
    JWT_ACCESS_TOKEN_EXPIRES = 3600  # 1 hour, in seconds
    JWT_TOKEN_LOCATION = ["headers", "cookies"]
    JWT_COOKIE_SECURE = False  # set to True for HTTPS production
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_COOKIE_SAMESITE = "Strict"

    THREAD_NUMBER = 2

    SERVICE_INFO = {
        "@context": "https://schema.org/docs/jsonldcontext.jsonld",
        "@type": "DataCatalog",
        "@id": "http://127.0.0.1:5000/docs",
        "url": "http://127.0.0.1:5000/docs",
        "name": "API SOFAIR LIGHT",
        "description": "Sensor Observations to FAIR data. API de diffusion de données d'obseravtions en OGC SensorThings.",
        "keywords": [
            "SensorThings",
            "OGC",
            "INSPIRE"
        ],
        "termsOfService": "https://www.gnu.org/licenses/gpl-3.0.html",
        "license": "https://www.gnu.org/licenses/gpl-3.0.html",
        "codeRepository": "https://github.com/geosas/sofair-light",
        "provider": {
            "@type": "Organization",
            "name": "GéoSAS",
            "url": "http://127.0.0.1:5000",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "UMR SAS - INRAE - Institut Agro",
                "postalCode": 35042,
                "addressLocality": "Rennes",
                "addressRegion": "65 rue de Saint-Brieuc",
                "addressCountry": "France"
            },
            "contactPoint": {
                "@type": "Contactpoint",
                "email": "geosas_adm@framalistes.org",
                "telephone": None,
                "faxNumber":  None,
                "url": None,
                "hoursAvailable": {
                    "opens":  None,
                    "description": None,
                },
                "contactType": "pointOfContact",
                "description": "Position Title"
            }
        }
    }
    
    STALT_CONFIG = {
        # observationProcedure values:
        # bike-collected CSV, LoRaWAN, HTTPS-pushed connected sensors, derived,
        # native STA. `httpsConnected` and `veloProcessing` share the same
        # ingestion pipeline (DataDriverPostToSTA), which accepts both.
        "AquisitionMethode": ["veloProcessing", "httpsConnected", "LoRaWAN", "SoftSensor", "STA"],
        "observationType": ["OM_Measurement", "OM_CategoryObservation",
                            "OM_CountObservation", "OM_Observation", "OM_TruthObservation"],
        "share": ["Yes", "No", "No but need Qualification"],
        "graph": ["bar", 'line+point']
    }

    # Quality-flag vocabulary (single source of truth). Each flag carries a
    # description (+ ontology uri), a display color
    # and the qualification-UI `action` that writes it; `severity` orders the
    # flags worst -> best (drives the "worst flag of the day" overview). To
    # change the vocabulary for a new deployment, edit this file only.
    STALT_OBSP_QF = _load_json(
        os.path.join(basedir, 'data', 'qualification', 'qf_flags.json'))

    STALT_serveur = "FROST"  # if other no lorawan et no post or patch csv
    STALT_Frost_plus = True  # for faster data ingestion,
    STALT_archive = "http://localhost:8081/FROST-Server/v1.1"
    STALT_partage = "http://localhost:8080/FROST-Server/v1.1"
    STALT_archive_proxyname = "http://127.0.0.1:5000/sta/archive/"
    STALT_partage_proxyname = "http://127.0.0.1:5000/sta/partage/"
    STALT_mode_service = "Frost_Geosas"

    # Observatory name = URL root under which the STAV front is served
    # (e.g. http://localhost:5000/sites-urbains-rennais/). It is also the default
    # name of the STAV config file loaded (config/<STALT_observatoire>.json).
    STALT_observatoire = "sites-urbains-rennais"

    # Shared secret for LoRaWAN ingestion (value of the 'LoRaWAN-Request' header),
    # to be overridden by the STALT_LORAWAN_SECRET environment variable in production
    STALT_LORAWAN_SECRET = os.environ.get(
        'STALT_LORAWAN_SECRET') or 'changez-moi-lorawan'

    # ORCID SSO (federated login, on top of the local auth). ORCID ONLY performs
    # authentication; the role/authorisation stays local (see doc/sso_orcid.md).
    # Secrets live in environment variables only, never committed.
    #   ORCID_BASE_URL: https://sandbox.orcid.org in dev, https://orcid.org in production.
    #   AUTH_MODE     : 'local' | 'orcid' | 'both' (drives the ORCID button display).
    ORCID_CLIENT_ID = os.environ.get('ORCID_CLIENT_ID')
    ORCID_CLIENT_SECRET = os.environ.get('ORCID_CLIENT_SECRET')
    ORCID_BASE_URL = os.environ.get('ORCID_BASE_URL', 'https://orcid.org')
    AUTH_MODE = os.environ.get('AUTH_MODE', 'both')


    # Direct Postgres access for the API: LEAST-PRIVILEGE role (never the superuser).
    # The superuser stays ONLY in the frost/*.sh scripts 
    # and in the FROST docker-compose. API role credentials via env variables:
    #   STALT_DB_USER / STALT_DB_PASSWORD / STALT_DB_HOST / STALT_DB_PORT
    _DB_USER = os.environ.get('STALT_DB_USER', 'sofair_api')
    _DB_PASSWORD = os.environ.get('STALT_DB_PASSWORD', '')
    _DB_HOST = os.environ.get('STALT_DB_HOST', 'localhost')
    _DB_PORT = int(os.environ.get('STALT_DB_PORT', '5433'))
    DB_archive = {
        'dbname': 'sta_archive',
        'host': _DB_HOST,
        'port': _DB_PORT,
        'user': _DB_USER,
        'password': _DB_PASSWORD,
    }
    DB_partage = {
        'dbname': 'sta_partage',
        'host': _DB_HOST,
        'port': _DB_PORT,
        'user': _DB_USER,
        'password': _DB_PASSWORD,
    }

    @classmethod
    def __getitem__(cls, item):
        return getattr(cls, item)
