"""Rating curve: stream discharge derived from a measured water level (height).

Q = a * (H - h0)^b        (H = water level, h0 = water level of zero discharge)

Valid only up to `h_max`: above it the curve is extrapolated, so those points
are flagged doubtful. `a`, `b`, `h0`, `h_max` are entered on the SoftSensor
configuration page (or applied from /tarage/list, which fits the curve on the
gaugings) and passed in `params`.
"""
import numpy as np
import pandas as pd

from app.sta_tools.qualify_observations import qf_code

# QF assigned to points above the validity range (h_max). Resolved from the
# single-source vocabulary (the 'douteux' flag), never a hardcoded number.
_DOUBTFUL = qf_code('douteux', 2)

METADATA = {
    "id": "rating_curve",
    "label": "Rating curve",
    "description": "Discharge Q = a . (H - h0)^b (H = water level); above h_max the "
                   "curve is extrapolated -> flagged doubtful.",
    "params": [
        {"key": "a", "label": "a", "type": "number"},
        {"key": "b", "label": "b", "type": "number"},
        {"key": "h0", "label": "h0 (water level of zero discharge, 0 if none)", "type": "number"},
        {"key": "h_max",
            "label": "h_max (validity max range)", "type": "number"},
    ],
}


def run(source_df, params):
    """Compute the discharge series from the qualified water-level series.

    Args:
        source_df: DataFrame[phenomenonTime, value] - the QUALIFIED water-level series.
        params: dict - `a`, `b`, `h0` (rating coefficients) and `h_max` (validity range).

    Returns:
        DataFrame[phenomenonTime, value, qf]. `qf` = doubtful where H > h_max,
        else NaN meaning "no override" (the derived point inherits the source QF).
    """
    a = float(params["a"])
    b = float(params["b"])
    h0 = float(params.get("h0", 0))   # associations made before h0 existed
    h_max = float(params["h_max"])

    out = source_df.copy()
    h = pd.to_numeric(out["value"])
    # No discharge at or below h0
    out["value"] = a * np.clip(h - h0, 0, None) ** b
    # Above the range -> doubtful; below -> NaN (inherit the source QF).
    out["qf"] = np.where(h > h_max, _DOUBTFUL, np.nan)
    return out[["phenomenonTime", "value", "qf"]]


def derived_max_value(params):
    """Max VALID derived value = discharge at the validity range: a * (h_max - h0)^b.
    """
    h0 = float(params.get("h0", 0))
    return float(params["a"]) * max(float(params["h_max"]) - h0, 0) ** float(params["b"])
