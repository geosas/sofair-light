from flask import Blueprint, render_template, redirect, url_for, request, jsonify, Response
import pandas as pd
import re
import orjson
from decimal import Decimal

from app.services.security import verify_jwt_api
from app.config import Config
from app.sta_tools import sta_client
from app.sta_tools.qualify_observations import qualify_archive, QF_SEVERITY_SQL
from app.sta_tools.proxy_sql import (
    correct_date_format, parse_filter, colonne_rename, parse_groupby,
    orderby_dir, int_arg, query_df, stream_csv, BadQueryParam)
from app.sta_tools.covjson import extract_lonlat, build_covjson
from app.sta_tools.archive_observations import write_archive_observations
from app.sta_tools.qualification_automatic import AutomaticQualification
import psycopg

# Blueprint for the STA proxy routes
sta_bp = Blueprint('sta', __name__)
sta_bp.enable_openapi = False


def _orjson_default(o):
    """Fallback for types orjson doesn't handle natively. Postgres numeric ->
    Decimal (from psycopg) becomes a JSON number, not a string."""
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError


def _json_response(obj, status=200):
    """Fast JSON response for the big proxy payloads (dataArray / covjson).

    orjson serialises straight to UTF-8 bytes
    and emits 'null' for NaN/Infinity, so data gaps stay valid JSON
    without any pandas NaN->None pass. More faster than jsonify
    """
    return Response(
        orjson.dumps(obj, option=orjson.OPT_SERIALIZE_NUMPY,
                     default=_orjson_default),
        status=status, mimetype="application/json")


def _forward_response(server, path, params=None):
    """Verbatim GET passthrough to STA: forward the raw JSON **bytes** as-is (no
    .json() parse + re-serialise round-trip) and propagate STA's status code and
    Content-Type. For pure passthroughs only (no body transformation)."""
    r = sta_client.forward(
        server, path, params=request.args if params is None else params)
    return Response(r.content, status=r.status_code,
                    content_type=r.headers.get("Content-Type", "application/json"))


@sta_bp.after_request
def _cors_read_only(response):
    """Public CORS for SensorThings **reads only**.

    Only GET/HEAD responses get 'Access-Control-Allow-Origin: *' (no
    credentials -> no cookie ever crosses origins), so any third-party browser
    app can consume the open STA data. 

    """
    if request.method in ("GET", "HEAD"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers.setdefault("Vary", "Origin")
    elif request.method == "OPTIONS":
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, HEAD"
        response.headers.setdefault("Vary", "Origin")
    return response


@sta_bp.before_request
def _require_jwt_for_writes():
    """Reads (GET/HEAD) are public; **every write method requires a valid JWT**.

    Auth gate for the whole /sta blueprint: it covers the
    generic SensorThings passthrough writes (POST/PUT/PATCH/DELETE on
    /archive|/partage/<path>) AND the specific 'post-csv' / 'QualifyObservations'
    endpoints, so there is no way to add a write route that forgets auth.

    The actual JWT check is delegated to 'security.verify_jwt_api()' (single
    source of auth logic); this blueprint only owns the **method policy** (which
    verbs are public).
    'Bearer' header is also accepted for machine/SensorThings clients.

    The STA archive can also be check if needed 

    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    return verify_jwt_api()  # None -> continue ; (json, 401)


@sta_bp.errorhandler(BadQueryParam)
def _handle_bad_query_param(e):
    return jsonify({"error": "invalid query parameter"}), 400


@sta_bp.get('/archive/<path:path>')
def home_sta_archive(path):
    print(path)
    if any(ele in path for ele in ["v1.0", "v1.1"]):
        if '$resultFormat' in request.args and request.args['$resultFormat'].lower() == 'csv':

            # no datastreams in archive by design
            if "MultiDatastreams(" in path and "Observations" in path:

                id_data = re.search(r"Datastreams\(([^)]+)\)", path).group(1)
                if not id_data.isdigit():
                    return jsonify({"error": "invalid id"}), 400
                id_data = int(id_data)

                filt_sql, params = "", []
                if "$filter" in request.args:
                    filt_sql, params = parse_filter(request.args['$filter'])

                if "$groupby" in request.args:
                    gb = parse_groupby(request.args['$groupby'])
                    if gb is None:
                        return jsonify({"message": "groupby only for 'day','hour','month','week'"}), 400
                    unit, func = gb
                    # Explode RESULT_JSON into one column per slot
                    # (result_raw, QF, result_corrected). The QF column carries
                    # the WORST flag of the bucket (via QF_SEVERITY_SQL).
                    query = f"""SELECT
                    TO_CHAR(DATE_TRUNC('{unit}', "PHENOMENON_TIME_START")  AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || '+00:00' as "phenomenonTime",
                    {func}(("RESULT_JSON" ->> 0)::numeric) as result_raw,
                    (ARRAY_AGG(("RESULT_JSON" ->> 1)::int ORDER BY {QF_SEVERITY_SQL} DESC))[1] as "QF",
                    {func}(("RESULT_JSON" ->> 2)::numeric) as result_corrected
                    FROM "OBSERVATIONS" WHERE "MULTI_DATASTREAM_ID"={id_data} {filt_sql}
                    GROUP BY DATE_TRUNC('{unit}', "PHENOMENON_TIME_START")
                    ORDER BY "phenomenonTime" ASC"""
                else:
                    # Explode RESULT_JSON into one column per slot.
                    query = f"""SELECT TO_CHAR("PHENOMENON_TIME_START" AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || '+00:00' as "phenomenonTime", ("RESULT_JSON" ->> 0)::numeric as result_raw, ("RESULT_JSON" ->> 1)::int as "QF", ("RESULT_JSON" ->> 2)::numeric as result_corrected FROM "OBSERVATIONS" WHERE "MULTI_DATASTREAM_ID"={id_data} {filt_sql} ORDER BY "PHENOMENON_TIME_START" ASC"""
                skip = int_arg("$skip")
                if skip is not None:
                    query += f" OFFSET {skip}"
                top = int_arg("$top")
                if top is not None:
                    query += f" LIMIT {top}"

                return Response(
                    stream_csv(Config.DB_archive, query, params),
                    mimetype='text/csv',
                    headers={'Content-Disposition':
                             f'attachment; filename="datastreams_{id_data}.csv"'})

            else:
                return jsonify({'message': 'resultFormat only for observations'}), 400
        elif '$resultFormat' in request.args and request.args['$resultFormat'] == 'dataArray':
            if "MultiDatastreams(" in path and "Observations" in path:
                id_data = re.search(
                    r"MultiDatastreams\(([^)]+)\)", path).group(1)
                if not id_data.isdigit():
                    return jsonify({"error": "invalid id"}), 400
                id_data = int(id_data)

                filt_sql, params = "", []
                if "$filter" in request.args:
                    filt_sql, params = parse_filter(request.args['$filter'])

                if "$groupby" in request.args:
                    gb = parse_groupby(request.args['$groupby'])
                    if gb is None:
                        return jsonify({"message": "groupby only for 'day','hour','month','week'"}), 400
                    unit, func = gb
                    # Aggregated result mirrors the raw shape [raw, QF, corrected]:
                    # the QF slot carries the WORST flag of the bucket (via
                    # QF_SEVERITY_SQL) so the viewer can colour the bucket by its
                    # most severe point, like the qualification overview does.
                    query = f"""SELECT
                    TO_CHAR(DATE_TRUNC('{unit}', "PHENOMENON_TIME_START")  AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || '+00:00' as "phenomenonTime",
                    jsonb_build_array(
                        {func}(("RESULT_JSON" ->> 0)::numeric),
                        (ARRAY_AGG(("RESULT_JSON" ->> 1)::int ORDER BY {QF_SEVERITY_SQL} DESC))[1],
                        {func}(("RESULT_JSON" ->> 2)::numeric)) AS result
                    FROM "OBSERVATIONS" WHERE "MULTI_DATASTREAM_ID"={id_data} {filt_sql}
                    GROUP BY DATE_TRUNC('{unit}', "PHENOMENON_TIME_START")
                    ORDER BY "phenomenonTime" ASC"""
                else:
                    select_columns = ""
                    if '$select' in request.args:
                        select_columns += colonne_rename(
                            request.args['$select'].split(','))

                    query = f"""SELECT TO_CHAR("PHENOMENON_TIME_START" AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || '+00:00' as "phenomenonTime", "RESULT_JSON" as result {select_columns} FROM "OBSERVATIONS" WHERE "MULTI_DATASTREAM_ID"={id_data} {filt_sql}"""
                    if "$orderby" in request.args:
                        query += f' ORDER BY "PHENOMENON_TIME_START" {orderby_dir()}'
                    skip = int_arg("$skip")
                    if skip is not None:
                        query += f" OFFSET {skip}"

                top = int_arg("$top")
                if top is not None:
                    query += f" LIMIT {top}"

                df = query_df(Config.DB_archive, query, params)

                json_output = {
                    "value": [
                        {"Datastream@iot.navigationLink": Config.STALT_archive_proxyname+path.rsplit('/', 1)[0],
                            "components": list(df.columns),
                            "dataArray": df.values.tolist()
                         }
                    ]
                }

                return _json_response(json_output)
            else:
                return jsonify({'message': 'resultFormat only for observations'}), 400

        elif '$resultFormat' in request.args and request.args['$resultFormat'].lower() == 'covjson':
            if "MultiDatastreams(" not in path and not "Observations" in path:
                return jsonify({'message': 'resultFormat only for observations'}), 400
            id_data = re.search(r"MultiDatastreams\(([^)]+)\)", path).group(1)
            if not str(id_data).isdigit():
                return jsonify({"error": "invalid MultiDatastream id"}), 400

            # Metadata via STA: name, thesaurus (definition), unit, location
            try:
                meta = sta_client.get(
                    "archive", f"/MultiDatastreams({id_data})",
                    params={"$expand": "ObservedProperties($select=name,definition),"
                                       "Thing/Locations($select=location)"}).json()
            except Exception as e:
                return jsonify({"error": "STA archive unavailable", "exception": str(e)}), 502

            ops = meta.get("ObservedProperties") or []
            op = ops[0] if ops else {}
            units = meta.get("unitOfMeasurements") or []
            unit_symbol = units[0].get("symbol") if units else None
            lon, lat = extract_lonlat(
                (meta.get("Thing") or {}).get("Locations"))

            references = (Config.APP_METADATA or {}).get(
                "metadata_url") or None

            filt_sql, params = "", []
            if "$filter" in request.args:
                filt_sql, params = parse_filter(request.args['$filter'])

            # CovJSON archive: no aggregation, we return the whole series with its
            # qualification. RESULT_JSON = [raw, QF, published]
            query = f"""SELECT TO_CHAR("PHENOMENON_TIME_START" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as t, ("RESULT_JSON" ->> 2)::numeric as v_corr, ("RESULT_JSON" ->> 0)::numeric as v_raw, ("RESULT_JSON" ->> 1)::int as qc FROM "OBSERVATIONS" WHERE "MULTI_DATASTREAM_ID"={id_data} {filt_sql} ORDER BY "PHENOMENON_TIME_START" ASC"""
            skip = int_arg("$skip")
            if skip is not None:
                query += f" OFFSET {skip}"
            top = int_arg("$top")
            if top is not None:
                query += f" LIMIT {top}"

            df = query_df(Config.DB_archive, query, params)

            times = df['t'].tolist()
            values = [None if pd.isna(x) else float(x) for x in df['v_corr']]
            raw_values = [None if pd.isna(x) else float(x)
                          for x in df['v_raw']]
            qc_values = [None if pd.isna(x) else int(x) for x in df['qc']]
            cov = build_covjson(
                meta.get("name", f"MultiDatastream {id_data}"),
                op.get("definition"), op.get("name"),
                unit_symbol, lon, lat, times, values,
                references=references, raw_values=raw_values,
                qc_values=qc_values, qc_table=Config.STALT_OBSP_QF)
            return _json_response(cov)

        # frost date bug for grafana
        elif "$filter" in request.args.keys() and "Observation" in path:

            args = request.args.to_dict()

            if "$skipFilter" in request.args.keys():
                args["$skipFilter"] = correct_date_format(
                    request.args["$skipFilter"])
            if "$filter" in request.args.keys():
                args["$filter"] = correct_date_format(request.args["$filter"])

            # pass the date-CORRECTED args for the FROST/Grafana date fix
            return _forward_response("archive", path, params=args)
        else:
            return _forward_response("archive", path)
    else:
        return jsonify({"error": "nothing here"}), 404


@sta_bp.post('/archive/ImportCSV')
def post_csv():
    """Bulk-ingest a wide CSV into the archive "OBSERVATIONS".

    The CSV holds one time column plus one value column **per MultiDatastream,
    the header being the MultiDatastream 'name'**, e.g.

        phenomenonTime,Name 1,Name 2
        2024-01-25T10:45:00Z,-15,13

    For each value column we resolve its MultiDatastream (id + 'properties':
    'foiId', 'minValue'/'maxValue'), apply the automatic threshold
    pre-qualification ('AutomaticQualification'), store 'RESULT_JSON =
    [raw, QF, corrected]' (corrected initialised to raw) and bulk-COPY into the
    archive via 'write_archive_observations', the same pipeline as
    '/private/import-data', minus the driver decode (columns are already values).

    """
    if 'file' not in request.files:
        return jsonify({"error": "No file received"}), 400

    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({"error": "The file is not a CSV"}), 400

    overlap = request.form.get('overlap', 'skip')
    if overlap not in ('skip', 'overwrite'):
        overlap = 'skip'

    try:
        df = pd.read_csv(file)
    except Exception as e:
        return jsonify({"error": "Unable to read the CSV file", "exception": str(e)}), 400

    if df.shape[1] < 2:
        return jsonify({"error": "CSV must have a time column and at least one MultiDatastream column"}), 400

    # First column = time, remaining columns = MultiDatastream names.
    time_col = 'phenomenonTime' if 'phenomenonTime' in df.columns else df.columns[0]
    ds_names = [c for c in df.columns if c != time_col]

    try:
        df[time_col] = pd.to_datetime(df[time_col], utc=True)
    except Exception as e:
        return jsonify({"error": f"Unable to parse the time column '{time_col}'", "exception": str(e)}), 400

    result_time = pd.Timestamp.now(tz="UTC")

    posted, skipped = [], []
    for name in ds_names:
        # Resolve the MultiDatastream by its exact name.
        esc = name.replace("'", "''")
        params = {"$filter": f"name eq '{esc}'",
                  "$select": "id,name,properties"}
        try:
            r = sta_client.get("archive", "/MultiDatastreams", params=params)
        except Exception as e:
            return jsonify({"error": "The SensorThings archive service is unreachable",
                            "exception": str(e)}), 500
        if not r.ok:
            return jsonify({"error": "SensorThings archive query failed",
                            "column": name}), 500

        found = r.json().get('value', [])
        if len(found) == 0:
            skipped.append(
                {"column": name, "reason": "no MultiDatastream with this name"})
            continue
        mds = found[0]
        mds_id = mds["@iot.id"]
        properties = mds.get('properties') or {}
        foi_id = properties.get('foiId')
        if foi_id is None:
            return jsonify({"error": f"foiId missing in the MultiDatastream '{name}' properties: rerun the configuration"}), 500

        # Build the dataframe (mirror data_driver_post_to_sta, maybe refactor it).
        df_post = df[[time_col, name]].rename(
            columns={time_col: 'phenomenonTime', name: 'result'}).dropna()
        if len(df_post) == 0:
            skipped.append({"column": name, "reason": "no value rows"})
            continue

        df_post['phenomenonTime'] = df_post['phenomenonTime'].dt.strftime(
            '%Y-%m-%dT%H:%M:%SZ')
        df_post = df_post.sort_values('phenomenonTime').reset_index(drop=True)
        df_post['resultTime'] = result_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        df_post['qualification'] = -1
        df_post['FOI'] = foi_id

        # Threshold pre-qualification: out of [minValue, maxValue] -> Wrong.
        df_post = AutomaticQualification.qualify_dataframe(
            df_post, properties, result_col='result', qf_col='qualification')

        # RESULT_JSON = [raw, QF, corrected] (corrected starts as raw).
        df_post['result'] = df_post.apply(
            lambda row: [row['result'], row['qualification'], row['result']],
            axis=1).tolist()

        df_post["RESULT_TYPE"] = 2  # For FROST colum RESULT_JSON
        df_post["PHENOMENON_TIME_END"] = df_post['phenomenonTime']
        df_post["MULTI_DATASTREAM_ID"] = mds_id
        df_post.drop('qualification', axis=1, inplace=True)
        df_post = df_post.rename(columns={"phenomenonTime": "PHENOMENON_TIME_START",
                                          "result": "RESULT_JSON",
                                          "FOI": "FEATURE_ID",
                                          "resultTime": "RESULT_TIME"})
        for col in ('PHENOMENON_TIME_START', 'PHENOMENON_TIME_END', 'RESULT_TIME'):
            df_post[col] = pd.to_datetime(df_post[col])

        # Overlap with already-stored data (per datastream):
        # 'skip' (default) drops timestamps already stored; 'overwrite'
        # replaces the imported range (delete + insert).
        delete_range = None
        tmin = df_post['PHENOMENON_TIME_START'].min().to_pydatetime()
        tmax = df_post['PHENOMENON_TIME_START'].max().to_pydatetime()
        if overlap == "overwrite":
            delete_range = (tmin, tmax)
        else:
            with psycopg.connect(**Config.DB_archive) as conn_ov:
                with conn_ov.cursor() as cur_ov:
                    cur_ov.execute(
                        'SELECT TO_CHAR("PHENOMENON_TIME_START" AT TIME ZONE \'UTC\', '
                        '\'YYYY-MM-DD"T"HH24:MI:SS"Z"\') FROM "OBSERVATIONS" '
                        'WHERE "MULTI_DATASTREAM_ID" = %s '
                        'AND "PHENOMENON_TIME_START" BETWEEN %s AND %s',
                        (mds_id, tmin, tmax))
                    existing = {row[0] for row in cur_ov.fetchall()}
            if existing:
                df_post = df_post[~df_post['PHENOMENON_TIME_START']
                                  .dt.strftime('%Y-%m-%dT%H:%M:%SZ').isin(existing)]

        if len(df_post) == 0:
            skipped.append(
                {"column": name, "reason": "all rows already stored"})
            posted.append(mds_id)
            continue

        try:
            write_archive_observations(df_post, mds_id, Config.DB_archive,
                                       delete_range=delete_range)
        except Exception as e:
            return jsonify({"error": f"Error while writing observations for '{name}'",
                            "exception": str(e)}), 500
        posted.append(mds_id)

    if not posted and skipped:
        return jsonify({"error": "No column matched a MultiDatastream", "skipped": skipped}), 400

    return jsonify({"message": "file saved successfully",
                    "id": posted, "skipped": skipped}), 200


@sta_bp.patch('/archive/v1.1/QualifyObservations')
def qualify_observations():
    """STA "QualifyObservations" feature (PATCH), format modeled on
    CreateObservations, adapted to MultiDatastreams: updates each archive
    observation by its id with RESULT_JSON = [raw, QF, corrected].
    Acts only on the archive (qualified raw data)."""
    blocks = request.get_json(force=True)
    try:
        qualified = qualify_archive(blocks, Config.DB_archive)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": "qualification error", "exception": str(e)}), 500
    return jsonify({"qualified": qualified}), 200


@sta_bp.get('/partage/<path:path>')
def home_sta_partage(path):

    if '$resultFormat' in request.args and (request.args['$resultFormat'] == 'CSV' or request.args['$resultFormat'] == 'csv'):

        if "Datastreams(" in path and "Observations" in path:

            id_data = re.search(r"Datastreams\(([^)]+)\)", path).group(1)
            if not id_data.isdigit():
                return jsonify({"error": "invalid id"}), 400
            id_data = int(id_data)

            filt_sql, params = "", []
            if "$filter" in request.args:
                filt_sql, params = parse_filter(request.args['$filter'])

            if "$groupby" in request.args:
                gb = parse_groupby(request.args['$groupby'])
                if gb is None:
                    return jsonify({"message": "groupby only for 'day','hour','month','week'"}), 400
                unit = gb[0]
                query = f"""SELECT TO_CHAR(DATE_TRUNC('{unit}', "PHENOMENON_TIME_START")  AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || '+00:00' as "phenomenonTime", CASE WHEN bool_or("RESULT_NUMBER" IS NULL) THEN NULL ELSE AVG("RESULT_NUMBER") END as result FROM "OBSERVATIONS" WHERE "DATASTREAM_ID"={id_data} {filt_sql} GROUP BY DATE_TRUNC('{unit}', "PHENOMENON_TIME_START") ORDER BY "phenomenonTime" ASC"""
            else:
                query = f"""SELECT TO_CHAR("PHENOMENON_TIME_START" AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || '+00:00' as "phenomenonTime", "RESULT_NUMBER" as result FROM "OBSERVATIONS" WHERE "DATASTREAM_ID"={id_data} {filt_sql} ORDER BY "PHENOMENON_TIME_START" ASC"""
            skip = int_arg("$skip")
            if skip is not None:
                query += f" OFFSET {skip}"
            top = int_arg("$top")
            if top is not None:
                query += f" LIMIT {top}"
            return Response(
                stream_csv(Config.DB_partage, query, params),
                mimetype='text/csv',
                headers={'Content-Disposition':
                         f'attachment; filename="datastreams_{id_data}.csv"'})

        else:
            return jsonify({'message': 'resultFormat only for observations'}), 400

    elif '$resultFormat' in request.args and request.args['$resultFormat'] == 'dataArray':
        if "Datastreams(" in path:
            id_data = re.search(r"Datastreams\(([^)]+)\)", path).group(1)
            if not id_data.isdigit():
                return jsonify({"error": "invalid id"}), 400
            id_data = int(id_data)

            filt_sql, params = "", []
            if "$filter" in request.args:
                filt_sql, params = parse_filter(request.args['$filter'])

            if "$groupby" in request.args:
                gb = parse_groupby(request.args['$groupby'])
                if gb is None:
                    return jsonify({"message": "groupby only for 'day','hour','month','week'"}), 400
                unit, func = gb
                query = f"""SELECT TO_CHAR(DATE_TRUNC('{unit}', "PHENOMENON_TIME_START") AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || '+00:00' as "phenomenonTime", CASE WHEN bool_or("RESULT_NUMBER" IS NULL) THEN NULL ELSE {func}("RESULT_NUMBER") END as result FROM "OBSERVATIONS" WHERE "DATASTREAM_ID"={id_data} {filt_sql} GROUP BY DATE_TRUNC('{unit}', "PHENOMENON_TIME_START") ORDER BY "phenomenonTime" ASC"""
            else:
                query = f"""SELECT TO_CHAR("PHENOMENON_TIME_START" AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || '+00:00' as "phenomenonTime", "RESULT_NUMBER" as result FROM "OBSERVATIONS" WHERE "DATASTREAM_ID"={id_data} {filt_sql}"""
                if "$orderby" in request.args:
                    query += f' ORDER BY "PHENOMENON_TIME_START" {orderby_dir()}'
                skip = int_arg("$skip")
                if skip is not None:
                    query += f" OFFSET {skip}"

            top = int_arg("$top")
            if top is not None:
                query += f" LIMIT {top}"

            df = query_df(Config.DB_partage, query, params)

            json_output = {
                "value": [
                    {"Datastream@iot.navigationLink": Config.STALT_partage_proxyname + path.rsplit('/', 1)[0],
                        "components": list(df.columns),
                        "dataArray": df.values.tolist()
                     }
                ]
            }

            return _json_response(json_output)
        else:
            return jsonify({'message': 'resultFormat only for observations'}), 400

    elif '$resultFormat' in request.args and request.args['$resultFormat'].lower() == 'covjson':
        if "Datastreams(" not in path:
            return jsonify({'message': 'resultFormat only for observations'}), 400
        id_data = re.search(r"Datastreams\(([^)]+)\)", path).group(1)
        if not str(id_data).isdigit():
            return jsonify({"error": "invalid Datastream id"}), 400

        # Metadata via STA: name, thesaurus (definition), unit, location
        try:
            meta = sta_client.get(
                "partage", f"/Datastreams({id_data})",
                params={"$expand": "ObservedProperty($select=name,definition),"
                                   "Thing/Locations($select=location)"}).json()
        except Exception as e:
            return jsonify({"error": "STA partage unavailable", "exception": str(e)}), 502

        op = meta.get("ObservedProperty") or {}
        lon, lat = extract_lonlat((meta.get("Thing") or {}).get("Locations"))

        filt_sql, params = "", []
        if "$filter" in request.args:
            filt_sql, params = parse_filter(request.args['$filter'])

        # CovJSON: no aggregation, we return the whole series ($groupby
        # aggregation stays reserved for the viewer's dataArray).
        query = f"""SELECT TO_CHAR("PHENOMENON_TIME_START" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as t, "RESULT_NUMBER" as v FROM "OBSERVATIONS" WHERE "DATASTREAM_ID"={id_data} {filt_sql} ORDER BY "PHENOMENON_TIME_START" ASC"""
        skip = int_arg("$skip")
        if skip is not None:
            query += f" OFFSET {skip}"
        top = int_arg("$top")
        if top is not None:
            query += f" LIMIT {top}"

        df = query_df(Config.DB_partage, query, params)

        times = df['t'].tolist()
        values = [None if pd.isna(x) else float(x) for x in df['v']]
        cov = build_covjson(
            meta.get("name", f"Datastream {id_data}"),
            op.get("definition"), op.get("name"),
            (meta.get("unitOfMeasurement") or {}).get("symbol"),
            lon, lat, times, values,
            references=(Config.APP_METADATA or {}).get("metadata_url") or None)
        return _json_response(cov)

    return _forward_response("partage", path)


def _forward_write(server, path):
    """Relay a SensorThings write (POST/PUT/PATCH/DELETE) to the STA server and
    return its response verbatim (status + body + content-type).

    Auth is already enforced by '_require_jwt_for_writes' (this only runs for an
    authenticated request). Body + content-type are passed through untouched so
    STA validates the payload itself.
    """
    resp = sta_client.forward_request(
        server, path, method=request.method,
        params=request.args,
        data=request.get_data(),
        headers={"Content-Type": request.headers.get("Content-Type",
                                                     "application/json")},
    )
    return (resp.content, resp.status_code,
            {"Content-Type": resp.headers.get("Content-Type",
                                              "application/json")})


# Generic SensorThings write passthrough
# GET keeps its dedicated handlers above
# the static write routes (post-csv, QualifyObservations) win over
# this catch-all by because of werkzeug rule specificity.
# All non-GET methods are gated by JWT. So user can use STA requests
@sta_bp.route('/archive/<path:path>', methods=['POST', 'PUT', 'PATCH', 'DELETE'])
def write_sta_archive(path):
    return _forward_write("archive", path)


@sta_bp.route('/partage/<path:path>', methods=['POST', 'PUT', 'PATCH', 'DELETE'])
def write_sta_partage(path):
    return _forward_write("partage", path)
