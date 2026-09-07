#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QualifyObservations: qualification of the archive observations.

An in-house STA feature modelled on the CreateObservations format, but as a
PATCH and adapted to MultiDatastreams: every observation is updated by its id,
with the qualified result `RESULT_JSON = [raw, QF, corrected]`.

Body format (like CreateObservations, with adapted components):

    [
      {
        "MultiDatastream": { "@iot.id": 5 },
        "components": ["phenomenonTime", "result", "id"],
        "dataArray": [
          ["2025-03-30T23:55:00Z", [0.183, 4, 0.50], 63058],
          ...
        ]
      }
    ]

`result` = [raw, QF, corrected] (the RESULT_JSON), `id` = the observation id.
`phenomenonTime` is accepted (CreateObservations convention) but not required for
the patch (the id is enough).

Internals: builds the (ID, RESULT_JSON) buffer and reuses patch_observations
(COPY into a temporary table + UPDATE) -> fast. Touches the archive ONLY.
"""
import io
import json

import pandas as pd

from app.sta_tools.patch_observations import patch_observations
from app.config import Config


# QF severity ranking, used to pick the "worst" quality flag of a time bucket
# when aggregating (worst wins, so the bucket is coloured by its most severe
# point). Derived from Config.STALT_OBSP_QF['severity'] (an ordered list, worst
# first) so the whole vocabulary lives in one JSON file. Applied to
# ("RESULT_JSON"->>1)::int. Shared by the /sta archive $groupby aggregation and
# the private qualification overview. Computed at import (like the rest of the
# Config JSON state) - restart to pick up file edits.
def _qf_severity():
    """{code: rank} from the severity list (worst first -> highest rank)."""
    severity = (Config.STALT_OBSP_QF or {}).get("severity", [])
    n = len(severity)
    return {int(code): n - i for i, code in enumerate(severity)}


def _qf_severity_sql(col='("RESULT_JSON"->>1)::int'):
    """The same ranking as a SQL CASE expression (for ORDER BY / worst-of)."""
    whens = " ".join(f"WHEN {code} THEN {rank}"
                     for code, rank in _qf_severity().items())
    return f"CASE {col} {whens} ELSE 0 END"


QF_SEVERITY = _qf_severity()
QF_SEVERITY_SQL = _qf_severity_sql()


def qf_code(action, default=None):
    """QF code declared for a UI action in the vocabulary (Config.STALT_OBSP_QF),
    or `default`. The single-source lookup shared by the ingestion / softsensor /
    method code so no module hardcodes a numeric flag."""
    for code, meta in (Config.STALT_OBSP_QF.get('properties') or {}).items():
        if isinstance(meta, dict) and meta.get('action') == action:
            return int(code)
    return default


def worst_qf(*qfs):
    """Return the QF with the highest severity (worst wins), ignoring None/NaN.
    Used to combine an inherited QF with a method-asserted one (e.g. a rating
    curve flagging out-of-range points as doubtful)."""
    best, best_sev = None, -1
    for q in qfs:
        try:
            qi = int(q)
        except (TypeError, ValueError):
            continue  # None / NaN -> no contribution
        sev = QF_SEVERITY.get(qi, 0)
        if sev > best_sev:
            best, best_sev = qi, sev
    return best


def qualify_archive(blocks, DB_archive):
    """Apply the qualification (PATCH RESULT_JSON by id) from a
    CreateObservations-style payload. Returns the number of qualified observations."""
    if not isinstance(blocks, list):
        raise ValueError("the body must be an array of MultiDatastream blocks")

    ids, results = [], []
    for block in blocks:
        comps = block.get("components") or []
        if "result" not in comps or "id" not in comps:
            raise ValueError("every block must have components including 'result' and 'id'")
        i_res, i_id = comps.index("result"), comps.index("id")
        for row in block.get("dataArray") or []:
            ids.append(int(row[i_id]))
            # Valid JSON (None -> null) for the COPY's jsonb column
            results.append(json.dumps(row[i_res]))   # "[raw, QF, corrected]"

    if not ids:
        return 0

    df = pd.DataFrame({"ID": ids, "RESULT_JSON": results})
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=True)
    buf.seek(0)
    patch_observations(buf, DB_archive)
    return len(ids)
