from flask import render_template, request, jsonify
from flask_babel import gettext as _
import pandas as pd
import psycopg
import numpy as np

from app.config import Config
from app.sta_tools import sta_client
from app.sta_tools.qualify_observations import qualify_archive, QF_SEVERITY_SQL
from app.services.security import jwt_required_or_redirect

from app.routes.private import private_bp


def _action_codes():
    """{action_name: qf_code} derived from the QF vocabulary (single source of
    truth, Config.STALT_OBSP_QF). Maps a UI action (delete/douteux/...) to the
    integer flag it writes."""
    return {meta["action"]: int(code)
            for code, meta in (Config.STALT_OBSP_QF.get("properties") or {}).items()
            if isinstance(meta, dict) and meta.get("action")}


@private_bp.get('/qualification')
@jwt_required_or_redirect()
def qualification():
    url_archive = Config.STALT_archive_proxyname.rstrip('/') + '/v1.1'
    return render_template('private/qualification.html', url_archive=url_archive,
                           qf_table=Config.STALT_OBSP_QF)


@private_bp.get('/qualification-overview')
@jwt_required_or_redirect()
def qualification_overview():
    """Overview: per day, min/max/mean (raw value) + the most severe QF of the
    day. Used to draw the overview curve colored by qualification."""

    idD = request.args.get('idData', '')
    if not idD.isdigit():
        return jsonify({"error": _("invalid idData")}), 400

    query = f'''
        SELECT
            TO_CHAR(DATE_TRUNC('day', "PHENOMENON_TIME_START") AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day,
            MIN(("RESULT_JSON"->>0)::numeric) AS mini,
            MAX(("RESULT_JSON"->>0)::numeric) AS maxi,
            AVG(("RESULT_JSON"->>0)::numeric) AS moy,
            (ARRAY_AGG(("RESULT_JSON"->>1)::int ORDER BY {QF_SEVERITY_SQL} DESC))[1] AS qf
        FROM "OBSERVATIONS"
        WHERE "MULTI_DATASTREAM_ID" = {int(idD)}
        GROUP BY DATE_TRUNC('day', "PHENOMENON_TIME_START")
        ORDER BY day ASC
    '''
    with psycopg.connect(**Config.DB_archive) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()

    def f(x):
        # min, max et mean come from PSQL in  Decimal.
        return float(x) if x is not None else None
    data = [{"day": r[0], "min": f(r[1]), "max": f(r[2]),
             "mean": f(r[3]), "qf": r[4]} for r in rows]
    return jsonify(data)


def _apply_qualification(id_data, rows):
    """Apply a qualification to archive and partage from
    [{id, phenomenonTime, result_raw, QF, result_share}],:
    - archive: qualify_archive (RESULT_JSON = [raw, QF, share], patch by id)
    - partage: apply_partage_qualification (bulk insert/update/delete + gap markers)

    If the datastream are a SoftSensorProducer, the SoftSensor Datastream
    will be qualify as well
    """
    from app.sta_tools.observations_partage import apply_partage_qualification

    # Matching partage Datastream (via the archive's nameShare property).
    # Also read the SoftSensor producer + Thing here.
    r = sta_client.proxy_get("archive", f"MultiDatastreams({id_data})",
                             params={"$select": "name,properties",
                                     "$expand": "Thing($select=name,properties)"})
    src = r.json()
    src_props = src.get('properties') or {}
    src_thing = src.get('Thing') or {}
    name_share = src_props['nameShare']
    r = sta_client.proxy_get("partage", "Datastreams",
                             params={"$select": "name,id,properties", "$filter": f"name eq '{name_share}'"})
    ds_partage = r.json()['value'][0]
    idD_partage = ds_partage['@iot.id']
    foi_partage = (ds_partage.get('properties') or {}).get('foiId')
    if foi_partage is None:
        return jsonify({"error": _("foiId missing on the partage Datastream '%(name)s': rerun the configuration", name=name_share)}), 500

    # Archive: patch RESULT_JSON = [raw, QF, share] by observation id.
    blocks = [{
        "MultiDatastream": {"@iot.id": id_data},
        "components": ["result", "id"],
        "dataArray": [
            [[r['result_raw'], int(r['QF']), r['result_share']], r['id']]
            for r in rows
        ],
    }]
    qualify_archive(blocks, Config.DB_archive)

    # Partage: BULK apply (insert COPY / update temp table / grouped delete).
    # Archive is left untouched here.
    summary = apply_partage_qualification(
        rows, idD_partage, foi_partage, Config.DB_partage)

    result = {"response": "ok", "changed": len(rows), "partage": summary,
              "idArchive": id_data, "idPartage": idD_partage}

    # SoftSensor: if this source declares a producer, (re)compute + publish the
    # derived datastream from the qualified values. Non-fatal: a failure is
    # reported but does not undo the source qualification above.
    from app.sta_tools.softsensor_publish import apply_softsensor, PRODUCER_KEY
    ss = apply_softsensor(src_props.get(PRODUCER_KEY), src_thing, rows,
                          Config.DB_archive, Config.DB_partage)
    if ss is not None:
        result["softSensor"] = ss

    return jsonify(result)


@private_bp.post('/qualification')
@jwt_required_or_redirect()
def qualification_update():
    """Range-based qualification (the qualification.html main workflow): the user
    marks time ranges over the displayed window (delete/calibration/
    interpolation/gap); everything else in the window is validated. Fetch the
    whole window, set the QF per range, then delegate to _apply_qualification
    """

    content = request.json
    id_data = content['idData']
    qualif = content['value']
    date_start = content['date_start']
    date_end = content['date_end']

    # Window observations from the archive (dataArray -> result = [raw, QF, share] + id)
    r = sta_client.proxy_get(
        "archive", f"MultiDatastreams({id_data})/Observations",
        params={"$select": "phenomenonTime,result,id",
                "$filter": f"phenomenonTime ge {date_start} and phenomenonTime lt {date_end}",
                "$resultFormat": "dataArray"})
    value = r.json().get('value', [])
    if not value or not value[0].get('dataArray'):
        return jsonify({"response": "ok", "changed": 0})

    block = value[0]
    df = pd.DataFrame(block['dataArray'], columns=block['components'])
    df[['result_raw', 'QF', 'result_share']] = pd.DataFrame(
        df['result'].tolist(), index=df.index)
    df['phenomenonTime'] = pd.to_datetime(df['phenomenonTime'])
    df = df.sort_values('phenomenonTime').reset_index(drop=True)

    # Apply each marked range -> QF, using the action->code map from the QF
    # vocabulary (Config.STALT_OBSP_QF). Interpolation additionally rebuilds the
    # published (share) value across the gap.
    action_codes = _action_codes()
    for plage, action in zip(qualif.get('plage', []), qualif.get('action', [])):
        start, end = plage.split('/')
        in_range = (df.phenomenonTime >= start) & (df.phenomenonTime < end)
        code = action_codes.get(action)
        if code is None:
            continue
        df.loc[in_range, 'QF'] = code
        if action == 'interpolation':
            df.loc[in_range, 'result_share'] = np.nan
            before = df.index[df.phenomenonTime < start]
            after = df.index[df.phenomenonTime >= end]
            if len(before) and len(after):
                lo, hi = before[-1], after[0]
                df.loc[lo:hi, 'result_share'] = df.loc[lo:hi,
                                                       'result_share'].interpolate()

    # Unqualified (raw / no-QC sentinel, and the legacy -1) -> validated.
    validated = action_codes.get('validated')
    raw_default = Config.STALT_OBSP_QF.get('raw_default', 0)
    if validated is not None:
        df.loc[df.QF.isin([raw_default, -1]), 'QF'] = validated

    # NaN -> None so nulls apply/serialise correctly downstream
    df = df.replace({np.nan: None})

    rows = [{"id": int(row['@iot.id']),
             "phenomenonTime": pd.Timestamp(row['phenomenonTime']).strftime('%Y-%m-%dT%H:%M:%SZ'),
             "result_raw": row['result_raw'],
             "QF": int(row['QF']),
             "result_share": row['result_share']}
            for _, row in df.iterrows()]

    return _apply_qualification(id_data, rows)


@private_bp.post('/qualification-rows')
@jwt_required_or_redirect()
def qualification_rows():
    """Differential upload: patches ONLY the rows that actually changed (the
    editable-table workflow). Expected body:
    {idData, rows: [{id, phenomenonTime, result_raw, QF, result_share}]}"""
    content = request.json
    id_data = content['idData']
    rows = content.get('rows', [])
    if not rows:
        return jsonify({"response": "ok", "changed": 0})
    return _apply_qualification(id_data, rows)
