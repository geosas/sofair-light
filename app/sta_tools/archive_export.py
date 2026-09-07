"""Bulk export of the archive database (raw + qualified observations + relations).

Two products, built with DuckDB (which reads Postgres server-side via its
`postgres` extension -- no pulling rows through Python):

- ``export_observations_parquet`` -> a Parquet file of every observation
  (phenomenonTime, multi_datastream_id, result_raw, quality_flag,
  result_corrected). ``multi_datastream_id`` is the join key back to the
  relations DB.
- ``export_relations_duckdb`` -> a standalone DuckDB file holding every public
  relation table EXCEPT the big OBSERVATIONS one (Things, MultiDatastreams,
  Locations, ObservedProperties, Sensors, Features + link tables). Tables are
  discovered dynamically so it survives FROST schema/version differences.

Neither Parquet nor DuckDB can be streamed on the fly (Parquet writes its footer
at the end; a .duckdb file is a binary database), so the route materialises the
file to a temp dir and then streams it from disk.

⚠️ The `DB_archive` role must have SELECT on the relation tables (it owns
OBSERVATIONS but may not read Things/MultiDatastreams/... by default) -- grant it
or the relations export raises a permission error.
"""
from urllib.parse import quote

import psycopg

from app.config import Config

# The one big table: goes to Parquet, excluded from the relations DB.
_OBS_TABLE = "OBSERVATIONS"

# Tables kept OUT of the relations DB: the observations (exported to Parquet),
# PostGIS's generic EPSG catalogue, and FROST/Liquibase migration bookkeeping.
_RELATION_EXCLUDE = {
    _OBS_TABLE, "SPATIAL_REF_SYS",
    "DATABASECHANGELOG", "DATABASECHANGELOGLOCK",
}


def _pg_uri(db):
    """postgresql:// URI for DuckDB's postgres ATTACH. User/password are
    percent-encoded so special characters can't break the ATTACH string
    (which DuckDB itself wraps in single quotes)."""
    user = quote(str(db["user"]), safe="")
    password = quote(str(db["password"]), safe="")
    return f"postgresql://{user}:{password}@{db['host']}:{db['port']}/{db['dbname']}"


def _connect_pg(con, db):
    """LOAD the postgres extension and ATTACH the archive DB read-only as `pg`.
    The session timezone is forced to UTC so timestamptz values are read/rendered
    in UTC regardless of the server's local zone."""
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute("SET TimeZone = 'UTC';")
    con.execute(
        f"ATTACH '{_pg_uri(db)}' AS pg (TYPE POSTGRES, READ_ONLY);")


def export_observations_parquet(dest_path, db=None):
    """Write every observation to a Parquet file at ``dest_path``."""
    import duckdb
    db = db or Config.DB_archive
    con = duckdb.connect()
    try:
        _connect_pg(con, db)
        con.execute(f"""
            COPY (
                SELECT ("PHENOMENON_TIME_START" AT TIME ZONE 'UTC') AS "phenomenonTime",
                       "MULTI_DATASTREAM_ID"        AS multi_datastream_id,
                       ("RESULT_JSON"->>0)::DOUBLE  AS result_raw,
                       ("RESULT_JSON"->>1)::INTEGER AS quality_flag,
                       ("RESULT_JSON"->>2)::DOUBLE  AS result_corrected
                FROM pg.public."{_OBS_TABLE}"
            ) TO '{dest_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
    finally:
        con.close()


def _relation_tables(db):
    """Public table names to copy (everything except the big observations one),
    read straight from Postgres so we don't depend on FROST's exact naming."""
    with psycopg.connect(**db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' ORDER BY tablename")
            return [r[0] for r in cur.fetchall()
                    if r[0].upper() not in _RELATION_EXCLUDE]


def export_relations_duckdb(dest_path, db=None):
    """Copy the relation tables into a standalone DuckDB file at ``dest_path``."""
    import duckdb
    db = db or Config.DB_archive
    con = duckdb.connect(dest_path)   # creates the .duckdb file
    try:
        _connect_pg(con, db)
        for table in _relation_tables(db):
            con.execute(
                f'CREATE TABLE "{table}" AS SELECT * FROM pg.public."{table}"')
        con.execute("DETACH pg;")
    finally:
        con.close()
