import os
import shlex


def _load_env_file(path):
    """
    """
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                tokens = shlex.split(line)
            except ValueError:
                continue
            if tokens and tokens[0] == "export":
                tokens = tokens[1:]
            if tokens and "=" in tokens[0]:
                key, val = tokens[0].split("=", 1)
                os.environ.setdefault(key, val)

_load_env_file(os.path.join(os.path.dirname(__file__), ".env.api"))
# HTTPS sensor credentials (config_sensor.py: SENSOR_OTT_USER, ...).
_load_env_file(os.path.join(os.path.dirname(__file__), ".env.sensor"))

from app import create_app  

app = create_app()

if __name__ == '__main__':
    app.run(debug=False)
