#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bulk-write archive observations (COPY into "OBSERVATIONS"), shared by the
import (data_driver_post_to_sta) and the SoftSensor publishing.

Handles FROST's per-row actualization triggers, which recompute the datastream's
MIN/MAX bounds on every row and re-scan all observations when a boundary row is
touched on a range delete or a bulk insert. So:
  - the DELETE trigger is disabled for the range delete.
  - the INSERT trigger is disabled for the bulk (middle) rows, kept for the
    first/last inserted rows so the datastream bounds stay correct.
"""
import io

import psycopg

# FROST DB columns
_COLS = ["PHENOMENON_TIME_START", "RESULT_JSON", "RESULT_TIME", "FEATURE_ID",
         "RESULT_TYPE", "PHENOMENON_TIME_END", "MULTI_DATASTREAM_ID"]
_COPY_SQL = ('COPY "OBSERVATIONS" ("PHENOMENON_TIME_START","RESULT_JSON","RESULT_TIME",'
             '"FEATURE_ID","RESULT_TYPE","PHENOMENON_TIME_END","MULTI_DATASTREAM_ID") '
             'FROM STDIN WITH CSV HEADER')
_BLOCK = 4_000_000  # ~4 MB chunks: good speed/memory tradeoff


def write_archive_observations(df, multi_ds_id, DB_archive, delete_range=None):
    """COPY 'df' into the archive "OBSERVATIONS" in one transaction.

    Args:
        df: DataFrame with  the '_COLS' columns.
            RESULT_JSON holds the [raw, QF, corrected] lists.
        multi_ds_id: MultiDatastream id (for the range delete).
        delete_range: (tmin, tmax) to delete this datastream's observations in
            that range first (overwrite); None to only insert.
    """
    multi_ds_id = int(multi_ds_id)
    with psycopg.connect(**DB_archive) as conn:
        with conn.cursor() as cur:
            if delete_range is not None:
                tmin, tmax = delete_range
                # Range delete without the TRIGGER per-row bound recompute.
                cur.execute('ALTER TABLE "OBSERVATIONS" DISABLE TRIGGER '
                            'multidatastreams_actualization_delete;')
                cur.execute(
                    'DELETE FROM "OBSERVATIONS" WHERE "MULTI_DATASTREAM_ID" = %s '
                    'AND "PHENOMENON_TIME_START" BETWEEN %s AND %s',
                    (multi_ds_id, tmin, tmax))
                cur.execute('ALTER TABLE "OBSERVATIONS" ENABLE TRIGGER '
                            'multidatastreams_actualization_delete;')

            if len(df) == 0:
                conn.commit()
                return

            # Keep the insert trigger for the first/last rows (-> bounds updated),
            # disable it for the bulk. Guarded so 1-2 row writes keep the trigger
            # and a single row is never inserted twice.
            if len(df) == 1:
                subsets = [df]
            elif len(df) == 2:
                subsets = [df.head(1), df.tail(1)]
            else:
                subsets = [df.head(1), df.tail(1), df.iloc[1:-1]]

            for sub in subsets:
                if len(sub) == 0:
                    continue
                buf = io.StringIO()
                sub[_COLS].to_csv(buf, index=False, header=True)
                buf.seek(0)
                if len(sub) > 1:
                    cur.execute('ALTER TABLE "OBSERVATIONS" DISABLE TRIGGER '
                                'multidatastreams_actualization_insert;')
                with cur.copy(_COPY_SQL) as copy:
                    while chunk := buf.read(_BLOCK):
                        copy.write(chunk)
                if len(sub) > 1:
                    cur.execute('ALTER TABLE "OBSERVATIONS" ENABLE TRIGGER '
                                'multidatastreams_actualization_insert;')
            conn.commit()
