"""Authentication credentials and secrets specific to each HTTPS sensor.

Non-LoRaWAN connected sensors (OTT, probes, etc.) push their files through
`POST /sensors/<driver>/<param>`. They cannot authenticate with the
application's cookie JWT: every driver therefore carries ITS OWN security
method (e.g. HTTP Basic auth) and reads its credentials from here.

The default values are placeholders: override them in production through
environment variables.
"""
import os

# driver -> { username: password }
SENSOR_CREDENTIALS = {
    "OTT": {
        os.environ.get("SENSOR_OTT_USER", "ott"):
            os.environ.get("SENSOR_OTT_PASSWORD", "change-me"),
    },
}
