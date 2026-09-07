"""ORCID OAuth2/OIDC client (federated login).
https://orcid.org/developer-tools
"""
from authlib.integrations.flask_client import OAuth

# Global OAuth registry, initialised in create_app() through register_orcid(app).
oauth = OAuth()


def register_orcid(app):
    """Initialize Authlib and register the orcid provider from the configuration.

    """
    oauth.init_app(app)

    client_id = app.config.get("ORCID_CLIENT_ID")
    client_secret = app.config.get("ORCID_CLIENT_SECRET")
    if not client_id or not client_secret:
        return

    base_url = app.config.get(
        "ORCID_BASE_URL", "https://orcid.org").rstrip("/")
    oauth.register(
        name="orcid",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=f"{base_url}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid"},
    )


def orcid_enabled():
    """True if the ORCID provider is actually configured (client registered)."""
    return "orcid" in getattr(oauth, "_clients", {})
