"""Bulk Qualification Application on the Partage Series 

This process only affects the published/shared view.
The raw archive data is never modified here,
it is patched separately by patch_observations, 
while keeping the original raw data preserved.

"""
import io
import uuid
from datetime import timezone

import pandas as pd
import psycopg

from app.sta_tools.qualify_observations import qf_code

BLOCK_SIZE = 4_000_000  # 4 Mo

# FROST encoding in base :
RTYPE_NUMBER = 0   # result numeric
RTYPE_NULL = 2     # result null (mfor gap)

# QF values making a point INVALID (not published / gap marker)
# based on the single source vocabulary: the delete (false) and gap (missing) flags.
_INVALID_QF = tuple(c for c in (qf_code('delete'),
                    qf_code('gap')) if c is not None)


def _invalid_boundaries(invalid_flags):
    """For a data series with gap, get only the first and the last values 
    off the gap."""
    boundaries = set()
    n = len(invalid_flags)
    i = 0
    while i < n:
        if invalid_flags[i]:
            j = i
            while j + 1 < n and invalid_flags[j + 1]:
                j += 1
            boundaries.add(i)   # first
            boundaries.add(j)   # last
            i = j + 1
        else:
            i += 1
    return boundaries


def apply_partage_qualification(rows, datastream_id, feature_id, DB_partage):
    """Applies the qualification in bulk on the shared Datastream.

    Args:
        rows: list of dicts {phenomenonTime, QF, result_share, ...} (MODIFIED rows).
        datastream_id: ID of the shared Datastream.
        feature_id: ID of the FeatureOfInterest (foiId) of the Thing.
        DB_partage: psycopg connection dictionary for the shared database.

    Returns:
        dict {inserted, updated, deleted, markers}.
    """
    datastream_id = int(datastream_id)
    feature_id = int(feature_id)

    # Normalization + temporal sorting (required to detect boundaries)
    norm = []
    for r in rows:
        t = pd.Timestamp(r['phenomenonTime']).tz_convert('UTC').to_pydatetime()
        qf = int(r['QF'])
        rs = r.get('result_share')
        valid = qf not in _INVALID_QF and rs is not None
        norm.append((t, valid, rs))
    if not norm:
        return {"inserted": 0, "updated": 0, "deleted": 0, "markers": 0}
    norm.sort(key=lambda x: x[0])

    invalid_flags = [not valid for _, valid, _ in norm]
    boundaries = _invalid_boundaries(invalid_flags)

    targets = []
    for idx, (t, valid, rs) in enumerate(norm):
        if valid:
            targets.append((t, 'set', RTYPE_NUMBER, rs))
        elif idx in boundaries:
            targets.append((t, 'set', RTYPE_NULL, None))
        else:
            targets.append((t, 'drop', None, None))

    tmin = min(t for t, *_ in targets)
    tmax = max(t for t, *_ in targets)

    to_insert, to_update, to_delete = [], [], []
    markers = 0

    with psycopg.connect(**DB_partage) as conn:
        with conn.cursor() as cur:
            # Observations partage in the time range
            cur.execute(
                'SELECT "PHENOMENON_TIME_START", "ID" FROM "OBSERVATIONS" '
                'WHERE "DATASTREAM_ID" = %s '
                'AND "PHENOMENON_TIME_START" BETWEEN %s AND %s',
                (datastream_id, tmin, tmax))
            existing = {ts.astimezone(timezone.utc)                        : oid for ts, oid in cur.fetchall()}

            for t, kind, rtype, number in targets:
                oid = existing.get(t)
                if kind == 'drop':
                    if oid is not None:
                        to_delete.append(oid)
                    continue
                if rtype == RTYPE_NULL:
                    markers += 1
                sstr = None if number is None else str(number)
                if oid is not None:
                    to_update.append((oid, rtype, number, sstr))
                else:
                    to_insert.append((t, rtype, number, sstr))

            # for this DELETE maybe deactivate TRIGGER
            if to_delete:
                cur.execute(
                    'DELETE FROM "OBSERVATIONS" WHERE "ID" = ANY(%s)', (to_delete,))

            #  UPDATE, the date don't change so the TRIGGER is not triggered
            if to_update:
                tmp = 'obs_upd_' + uuid.uuid4().hex
                cur.execute(
                    f'CREATE TEMP TABLE {tmp} '
                    '("ID" bigint, "RESULT_TYPE" smallint, '
                    '"RESULT_NUMBER" double precision, "RESULT_STRING" text) '
                    'ON COMMIT DROP;')
                upd_df = pd.DataFrame(
                    to_update, columns=["ID", "RESULT_TYPE", "RESULT_NUMBER", "RESULT_STRING"])
                buf = io.StringIO()
                upd_df.to_csv(buf, index=False, header=True)
                buf.seek(0)
                cur.execute(
                    'ALTER TABLE "OBSERVATIONS" DISABLE TRIGGER datastreams_actualization_update;')
                with cur.copy(f'COPY {tmp} ("ID","RESULT_TYPE","RESULT_NUMBER","RESULT_STRING") FROM STDIN WITH CSV HEADER') as copy:
                    while chunk := buf.read(BLOCK_SIZE):
                        copy.write(chunk)
                cur.execute(f"""
                    UPDATE "OBSERVATIONS" AS o
                    SET "RESULT_TYPE" = t."RESULT_TYPE",
                        "RESULT_NUMBER" = t."RESULT_NUMBER",
                        "RESULT_STRING" = t."RESULT_STRING"
                    FROM {tmp} AS t
                    WHERE o."ID" = t."ID";
                """)
                cur.execute(
                    'ALTER TABLE "OBSERVATIONS" ENABLE TRIGGER datastreams_actualization_update;')

            #  BULK INSERT, the TRIGGER is deactivate
            if to_insert:
                ins = pd.DataFrame(
                    to_insert, columns=["t", "RESULT_TYPE",
                                        "RESULT_NUMBER", "RESULT_STRING"]
                ).sort_values("t")
                share = pd.DataFrame({
                    "PHENOMENON_TIME_START": ins["t"],
                    "PHENOMENON_TIME_END": ins["t"],
                    "RESULT_TYPE": ins["RESULT_TYPE"],
                    "RESULT_NUMBER": ins["RESULT_NUMBER"],
                    "RESULT_STRING": ins["RESULT_STRING"],
                    "FEATURE_ID": feature_id,
                    "DATASTREAM_ID": datastream_id,
                })
                subsets = [share] if len(share) == 1 else [
                    share.head(1), share.tail(1), share.iloc[1:-1]]
                for sub in subsets:
                    if len(sub) == 0:
                        continue
                    b = io.StringIO()
                    sub.to_csv(b, index=False, header=True)
                    b.seek(0)
                    if len(sub) > 1:
                        cur.execute(
                            'ALTER TABLE "OBSERVATIONS" DISABLE TRIGGER datastreams_actualization_insert;')
                    with cur.copy('COPY "OBSERVATIONS" ("PHENOMENON_TIME_START", "PHENOMENON_TIME_END", "RESULT_TYPE", "RESULT_NUMBER", "RESULT_STRING", "FEATURE_ID", "DATASTREAM_ID") FROM STDIN WITH CSV HEADER') as copy:
                        while chunk := b.read(BLOCK_SIZE):
                            copy.write(chunk)
                    if len(sub) > 1:
                        cur.execute(
                            'ALTER TABLE "OBSERVATIONS" ENABLE TRIGGER datastreams_actualization_insert;')

            conn.commit()

    return {"inserted": len(to_insert), "updated": len(to_update),
            "deleted": len(to_delete), "markers": markers}
