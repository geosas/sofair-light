"""SQL for the `/sta` proxy (CSV / dataArray / covjson / groupby).

Security against SQL injection: 'parse_filter'/'colonne_rename' bind VALUES as '%s'
parameters (no value interpolation), but the '$groupby'/'$orderby'/'$top'/'$skip'
handling and field names are structural and are guarded by a whitelist
('GROUPBY_UNITS', 'AGG_FUNCS', the column/field mappings). Keep any new SQL on
that model, never interpolate a raw request value into the query string.
"""
import re

import psycopg
import pandas as pd
from flask import request


def correct_date_format(url):
    """Sanitize the comma-decimal timestamps Grafana's FROST datasource sends
    (e.g. 2024-09-13T09:45:42,609+00:00) down to 2024-09-13T09:45:42Z, which
    FROST/OData accepts.

    The trailing offset is optional and may arrive as '+00:00', a bare space
    ('+' decoded to ' ' in the query string), 'Z', or nothing -- all handled.
    A dot-decimal date (…42.000Z) is valid ISO 8601 and left untouched (no comma).
    """
    pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}),\d+(?:[ +]\d{2}:\d{2}|Z)?'
    return re.sub(pattern, r'\1Z', url)


def parse_filter(filter_str):

    field_mapping = {
        "phenomenonTime": "PHENOMENON_TIME_START",
        "result": "RESULT_JSON",
    }
    # ge/le/gt/lt/eq -> SQL operator. VALUES become bound parameters (%s): no
    # value interpolation => no injection. Field is whitelisted.
    operators = [(" ge ", ">="), (" le ", "<="), (" gt ", ">"),
                 (" lt ", "<"), (" eq ", "=")]
    conditions, params = [], []
    for condition in filter_str.split(" and "):
        for token, sql_op in operators:
            if token in condition:
                field, value = condition.split(token, 1)
                db_field = field_mapping.get(field.strip())
                if db_field is not None:
                    conditions.append(f'"{db_field}" {sql_op} %s')
                    params.append(value.strip())
                break
    if not conditions:
        return "", []
    return "AND " + " AND ".join(conditions), params


def colonne_rename(col_name):
    # Whitelisted $select columns added to the dataArray SELECT.
    # Any unknown column is IGNORED (anti-injection).
    replacements = {
        'id': '"ID" AS "@iot.id"',
        '@iot.id': '"ID" AS "@iot.id"',
        'resultTime': '"RESULT_TIME" AS resultTime',
    }
    cols, seen = [], set()
    for x in col_name:
        mapped = replacements.get(x.strip())
        if mapped and mapped not in seen:
            seen.add(mapped)
            cols.append(mapped)
    return ", " + ", ".join(cols) if cols else ""


# --- Anti-injection guards for structural parameters (not bindable) ---
GROUPBY_UNITS = {"day", "hour", "month", "week"}
AGG_FUNCS = {"avg", "sum", "min", "max", "count"}


def parse_groupby(raw):
    """'unit[,func]' -> (unit, FUNC) validated against a whitelist, or None if invalid."""
    parts = raw.split(",")
    if parts[0] not in GROUPBY_UNITS:
        return None
    func = "AVG"
    if len(parts) >= 2:
        if parts[1].lower() not in AGG_FUNCS:
            return None
        func = parts[1].upper()
    return parts[0], func


def orderby_dir():
    """$orderby direction -> 'ASC' or 'DESC' (whitelist, default ASC)."""
    return "DESC" if request.args.get("$orderby", "").split(" ")[-1].upper() == "DESC" else "ASC"


def int_arg(name):
    """Integer value of an arg (e.g. $top/$skip), or None if absent/not an int."""
    v = request.args.get(name, "")
    return int(v) if v.isdigit() else None


class BadQueryParam(Exception):
    """Invalid query value (e.g. malformed $filter) -> 400, not 500."""


def query_df(dbconf, query, params=None):
    """Run a PARAMETERIZED SELECT (psycopg) and return a DataFrame."""
    try:
        with psycopg.connect(**dbconf) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params or [])
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
    except psycopg.errors.DataError:
        raise BadQueryParam()
    return pd.DataFrame(rows, columns=cols)


def stream_csv(dbconf, query, params):
    """COPY (query) TO STDOUT as CSV, streamed chunk-by-chunk (constant memory).

    Returns a generator of CSV byte chunks to hand straight to a Flask Response
    (no full-file BytesIO buffering -> O(1) memory, first byte as soon as
    Postgres produces it, arbitrarily large exports).

    The first chunk (the CSV header + start of execution) is pulled **eagerly**,
    so a query-level error (bad cast in the filter) surfaces as BadQueryParam
    (-> 400) BEFORE the HTTP response starts. Per-row errors that only appear
    mid-scan cannot become a 400 once streaming has begun (headers already sent).

    The dedicated connection is kept open for the life of the generator and
    closed when it is exhausted or the client disconnects (finally).
    """
    copy_sql = f"COPY ({query}) TO STDOUT WITH (FORMAT CSV, HEADER TRUE)"
    conn = psycopg.connect(**dbconf)
    try:
        cm = conn.cursor().copy(copy_sql, params)
        cp = cm.__enter__()
        it = iter(cp)
        try:
            first = next(it)          # triggers execution; errors raise here
        except StopIteration:
            first = None              # (COPY always emits the header, so rare)
    except psycopg.errors.DataError:
        conn.close()
        raise BadQueryParam()
    except BaseException:
        conn.close()
        raise

    def generate():
        try:
            if first is not None:
                yield bytes(first)
            for chunk in it:
                yield bytes(chunk)
            # fully consumed: finalize the COPY cleanly, then close.
            cm.__exit__(None, None, None)
        finally:
            # On any interruption (client disconnect -> GeneratorExit, error) we
            # skip the drain and just drop the dedicated connection, which aborts
            # the COPY server-side. Always runs.
            conn.close()
    return generate()
