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

### 2. Configure

Customise the **first part** of `app/config.py` (`Config` class) for your deployment; the second
part (below the marker comment) must not be edited. Secrets and DB credentials come from
environment variables (see `app/config.py` and the `frost/` scripts).

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

