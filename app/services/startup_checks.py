"""Startup guard against shipped-default secrets.
Set `STALT_ALLOW_INSECURE_DEFAULTS=1` to downgrade the error to a warning (local
development, CI, a quick first run after cloning).
"""
import os

# Config key -> the placeholder literal it is compared against. A match means
# the deployment never overrode it. 
_SIGNING_SECRETS = {
    "SECRET_KEY": "une_clé_secrète_très_sécurisée",
    "JWT_SECRET_KEY": "une_clé_jwt_sécurisée",
    "STALT_LORAWAN_SECRET": "changez-moi-lorawan",
}

# The environment variable a deployer must set for each of them.
_ENV_VAR = {
    "SECRET_KEY": "SECRET_KEY",
    "JWT_SECRET_KEY": "JWT_SECRET_KEY",
    "STALT_LORAWAN_SECRET": "STALT_LORAWAN_SECRET",
    "SENSOR_OTT_PASSWORD": "SENSOR_OTT_PASSWORD",
}

_OPT_OUT = "STALT_ALLOW_INSECURE_DEFAULTS"

# Only these values disable the guard
_OPT_OUT_ENABLED = {"1", "true", "yes", "on"}


def _opt_out_requested():
    return os.environ.get(_OPT_OUT, "").strip().lower() in _OPT_OUT_ENABLED


def insecure_defaults(config):
    """Return the list of (env var, reason) still sitting on a shipped default.

    Only credentials whose published value lets an attacker impersonate someone
    are reported. An empty DB password is a separate, self-announcing failure
    (Postgres refuses the connection), so it is deliberately left out.
    """
    
    from app.config import Config

    found = []
    for key, placeholder in _SIGNING_SECRETS.items():
        value = config.get(key, getattr(Config, key, None))
        if value == placeholder:
            found.append((_ENV_VAR[key],
                          f"{key} still uses the value published in config.py"))

    # Sensor credentials live outside app.config, in their own module.
    from app.config_sensor import SENSOR_CREDENTIALS
    if SENSOR_CREDENTIALS.get("OTT", {}).get("ott") == "change-me":
        found.append((_ENV_VAR["SENSOR_OTT_PASSWORD"],
                      "the OTT sensor accepts the published password "
                      "'change-me' on POST /sensors/OTT/<param>"))
    return found


def _format_report(found):
    lines = [
        "",
        "=" * 72,
        " INSECURE DEFAULT CREDENTIALS this deployment is not configured",
        "=" * 72,
    ]
    for env_var, reason in found:
        lines.append(f"  - {env_var}: {reason}")
    lines += [
        "",
        "  These fallback values are published in the public repository:",
        "  anyone can read them and forge a valid session or push fake",
        "  observations. Set the variables above (see .env.api.example and",
        "  .env.sensor.example), then restart.",
        "",
        f"  To run anyway (local development only): {_OPT_OUT}=1",
        "=" * 72,
        "",
    ]
    return "\n".join(lines)


def check_secrets(app):
    """Abort startup when a published placeholder credential is still in use.

    Raises RuntimeError unless `STALT_ALLOW_INSECURE_DEFAULTS` is set to one of
    1/true/yes/on, in which case the same report is logged as a warning and
    startup continues. Any other value (including 0 and false) keeps the guard.
    """
    found = insecure_defaults(app.config)
    if not found:
        return
    report = _format_report(found)
    if _opt_out_requested():
        app.logger.warning(report)
        return
    raise RuntimeError(report)
