# Running the FROST servers (archive + partage)

Two SensorThings servers (FROST) run as Docker containers. They hold **no**
database of their own: they connect to a **PostgreSQL running on the host
machine**.

| Database      | Role               | MultiDatastream | HTTP port |
|---------------|--------------------|-----------------|-----------|
| `sta_archive` | private / raw      | enabled         | 8081      |
| `sta_partage` | public / shared    | disabled        | 8080      |

These ports match `STALT_archive` / `STALT_partage` in `app/config.py`.

> **Everything goes through the scripts in this directory.** Never run
> `docker compose` by hand, and never write a `.env` file yourself:
> `create_db.sh` generates them from the credentials you type in.

---

## Prerequisite: allow access from the containers

Do this **once**, before the first `create_db.sh`. The containers connect from
the Docker subnet (e.g. `172.18.0.x`), which must be allowed in the cluster's
`pg_hba.conf`.

```bash
F=/etc/postgresql/17/main/pg_hba.conf
echo "host  sta_archive,sta_partage  postgres  172.16.0.0/12  scram-sha-256" | sudo tee -a "$F"
sudo systemctl reload postgresql@17-main
```

Reading the five columns: allow **TCP** connections (`host`) to the **two FROST
databases only**, for the **superuser only**, coming from the Docker address
range.

`172.16.0.0/12` spans `172.16.0.0` to `172.31.255.255` and therefore covers every
possible Docker subnet (172.17.x, 172.18.x…), so you never have to redo this when
the network is recreated. Pinning a single `/16` would break as soon as Docker
allocated a different one.


Only the superuser is listed because the FROST containers are the sole clients
coming from Docker, and they connect as `POSTGRES_USER`. The `sofair_api` role is
used by the API running on the host, over `127.0.0.1`.

If you changed `PGUSER`, `DB_ARCHIVE` or `DB_PARTAGE` when running `create_db.sh`,
substitute your own values in the line above.


---

## Installation

```bash
cd frost/
./create_db.sh
```

The script prompts for the PostgreSQL superuser password, then for the name and
password to give the API's least-privilege role. It then runs everything on its
own:

1. creates `sta_archive` + `sta_partage` (+ PostGIS);
2. creates the **`NOSUPERUSER`** API role and applies the CRUD grants;
3. starts the FROST containers, waits for the tables to be created, then grants
   ownership of `OBSERVATIONS` to the API role.

It is **idempotent**: safe to re-run. Pass `--no-frost` to skip starting the
containers (re-run the script afterwards to finalise the grants).

### The two generated files

| File | Read by | Contents |
|---|---|---|
| `../.env.api` | the Flask API (`run.py`) | credentials of the **least-privilege** role |
| `./.env` | **docker compose** | Postgres credentials of the **containers** |

Both are `chmod 600` and gitignored, they must **never** be committed. The
second one feeds the `${POSTGRES_*}` values interpolated in
`docker-compose.yaml`.

> ⚠️ The host differs on each side: the scripts reach Postgres at `127.0.0.1`
> (from the machine), while the containers must go through
> `host.docker.internal` (from Docker). Same database, two addresses 
> `create_db.sh` handles it.

---

## Day-to-day operation

All these scripts reuse the `frost/.env` generated at installation time.

| Command | Effect | Data |
|---|---|---|
| `./restart_frost.sh` | recreates the containers (picks up `docker-compose.yaml` changes) | untouched |
| `./restart_frost.sh --soft` | plain `restart`, faster, ignores the compose file | untouched |
| `./stop_frost.sh` | stops the containers | untouched |
| `./reset_db.sh` | **wipes** both databases and restarts FROST | ⚠️ **erased** |
| `./delete_db.sh` | drops the databases **and** the API role | ⚠️ **erased** |

`reset_db.sh` and `delete_db.sh` are irreversible and require an explicit
confirmation (`YES` / `DELETE`), which `-y` skips.

### Checking that FROST answers

```bash
curl -s http://localhost:8080/FROST-Server/v1.1 | head   # partage
curl -s http://localhost:8081/FROST-Server/v1.1 | head   # archive
```

Expected: a JSON `{"value":[ ... ]}` listing the STA resources.

---

## Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `frost/.env is missing` | `create_db.sh` was never run | `./create_db.sh` |
| `no pg_hba.conf entry for host "172.x.x.x"` | Docker subnet not allowed | see **Prerequisite** |
| `no pg_hba.conf entry for host "172.x.x.x", user "X", database "Y"` | subnet allowed, but the rule does not list that role or database | widen the `pg_hba.conf` line of the **Prerequisite** to include them |
| `Connection refused` in the FROST logs | Postgres unreachable from Docker | check `host.docker.internal` and the port in `frost/.env` |
| `password authentication failed` | wrong superuser password | re-run `./create_db.sh` (it regenerates `frost/.env`) |
| `database "sta_archive" does not exist` | databases not created | `./create_db.sh` |
| `Could not initialise database` at startup | one of the causes above | check `sudo docker compose logs` in `frost/` |

Credentials are never hard-coded: they are typed at the keyboard and only ever
live in the two local, gitignored files described above.
