# SOFAIR Light 

**Sensor Observations to FAIR data.** A Flask application that sits in front of OGC
**SensorThings API** servers (FROST-Server by default). It ingests sensor data (LoRaWAN payloads, probe files...), decodes it via
pluggable drivers, posts it to STA, validates data and re-serves it through a proxy that adds CSV export and time
aggregation.

## Installation

### 1. Create the Python environment

```bash
git clone https://github.com/geosas/sofair-light.git
cd sofair-light
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1.1 (Optional) Deploy STA servers

If you don't have a SensorThings service available, deploy two STA servers (archive + partage).
A preconfigured `docker-compose.yaml` is in `/frost` or you can use `create_db.sh`.

This requires Docker and a PostgreSQL cluster with PostGIS on the host, listening on **port 5433**
by default (a dedicated cluster is recommended). For another port, run
`PGPORT=<port> ./create_db.sh`. Full instructions are in
[`frost/README_install.md`](frost/README_install.md).

### 2. Configure

Configuration is split between two places:

**a) `app/config.py` (`Config` class): deployment settings.** Edit only these values:

| Setting | Purpose |
|---------|---------|
| `APP_TITLE` | Name displayed by your instance |
| `URL_PROJET` | Public URL of the application |
| `BABEL_DEFAULT_LOCALE` | Default UI language (`'en'` or `'fr'`) |
| `SERVICE_INFO` | Service metadata (name, provider, address, contact) |
| `STALT_archive` / `STALT_partage` | URLs of your two FROST servers (archive = private, partage = public) |
| `STALT_archive_proxyname` / `STALT_partage_proxyname` | Public URLs of the `/sta/` proxy (based on `URL_PROJET`) |
| `STALT_observatoire` | Observatory name, also the URL root of the STAV front (`/<name>/`) |

Leave everything else unchanged (`STALT_CONFIG`, `STALT_OBSP_QF`, `DB_archive`/`DB_partage`…):
the application relies on it. With the FROST servers deployed by `frost/create_db.sh` and a local
run, the defaults already work.

**b) Environment files: secrets and DB credentials.** These are never written in `config.py`.
Copy the example files and fill in the empty values:

```bash
cp .env.api.example .env.api        # SECRET_KEY, JWT_SECRET_KEY, STALT_DB_*, STALT_LORAWAN_SECRET, ORCID_*
cp .env.sensor.example .env.sensor  # SENSOR_OTT_PASSWORD
```

`run.py` loads both files at startup (both are gitignored). If you use `frost/create_db.sh`, run
it **before** filling `.env.api`: it overwrites the whole file with the `STALT_DB_*` block only,
so add the other variables afterwards. The application **refuses to start** while `SECRET_KEY`,
`JWT_SECRET_KEY` or `SENSOR_OTT_PASSWORD` keep their default value. Generate keys with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 3.1 Run locally

```bash
python run.py
```

Flask listens on port 5000 by default: <http://localhost:5000/>

### 3.2 Production (WSGI)

Serve via a WSGI server, e.g. [mod_wsgi](https://modwsgi.readthedocs.io/en/master/) (point it at the
Python environment) or Gunicorn.

## Authentication

Accounts are **invite-only** (no public self-registration). For create an admin accoutn use
the Flask CLI command:

```bash
flask --app run create-admin        # prompts email + hidden password, role=admin
```

An admin then invites users from `GET /auth/admin/invite`. Each invitation carries an
**authentication method**:

- **Local password** the invite yields a single-use `set-password` link (24 h).
- **ORCID (SSO)** the admin registers the invitee's **ORCID iD**; that person then signs in with
  the *“Sign in with ORCID”* button and their account is provisioned on first login (strong binding
  on the ORCID iD). No matching invitation ⇒ no account (the invite-only model is preserved).


### ORCID SSO configuration

Set these as environment variables (secrets never committed):

| Variable | Purpose |
|----------|---------|
| `ORCID_CLIENT_ID` / `ORCID_CLIENT_SECRET` | Client credentials from the ORCID developer console |
| `ORCID_BASE_URL` | `https://sandbox.orcid.org` (dev) or `https://orcid.org` (prod) |
| `AUTH_MODE` | `local` \| `orcid` \| `both` (controls the ORCID button; default `both`) |

Without client credentials the ORCID provider is not registered and `/auth/orcid/*` returns 404
(local auth only). The `redirect_uri` (`…/auth/orcid/callback`) must match **exactly** the one
declared in the ORCID console (http on localhost in dev, https in prod).


## Internationalization (i18n)

The UI is bilingual via **Flask-Babel / gettext**. **English is the source language**; a `fr`
locale translates it back to French. The language comes from the `lang` cookie (`GET
/set-lang/<code>`); `fr` is the default. Human-facing strings are wrapped in `_()`; machine-facing
APIs (`/api` OGC processes, drivers, `/sta`, `/sensors`) stay in English by design.

Regenerate the catalog after adding/removing translatable strings:

```bash
pybabel extract -F babel.cfg -o messages.pot .        # note the trailing "."
pybabel update  -i messages.pot -d app/translations -l fr
# fill the empty msgstr in app/translations/fr/LC_MESSAGES/messages.po
pybabel compile -d app/translations
```

### 4. Try it with the demo dataset

A ready-to-use configuration and an OTT piezometer data file are provided in `app/static/demo/`
Use a test instance: the demo creates real objects in FROST.

1. **Configuration** (`/private/configuration-obs`): upload `config_demo_complete.xlsx` at **step 2**
    (its `4_datastream` tab is already filled in).
2. **Data import** (`/private/import-data`): driver **OTT**, measurement point **PZ1.1**,
    file `PZ1.1_OTT_20240829.csv` → inspect, then send.
3. **Visualise** in STAV (`/<observatory>/`): PZ1.1 → Groundwater depth / temperature.
4. **SoftSensor (water table elevation)**: the `PZ1.1_Orpheus mini OTT nappe_Water table elevation` datastream is a softSensor,
     it stays empty until you:
     - link it in **Configuration › Configure SoftSensors** (`/private/configure-softsensor`):
       source = `PZ1.1_Orpheus mini OTT nappe_Groundwater depth`, method = **Ground water level**,
       target = `PZ1.1_Orpheus mini OTT nappe_Water table elevation`;
     - then qualify the source in **Management › Qualify data** (`/private/qualification`):
       saving a qualification computes and publishes the elevation (= Thing elevation - depth).
