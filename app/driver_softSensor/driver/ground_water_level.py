"""Ground water level: water-table derived from a measured depth.

altitude = elevation - depth

`elevation` is the reference altitude of the measurement point, resolved at
from the source datastream's Thing (`properties.elevation`, added
to the `thing` sheet of the config xlsx) and passed in `params`.
"""
import pandas as pd

METADATA = {
    "id": "ground_water_level",
    "label": "Ground water level",
    "description": "Water-table altitude = Thing elevation - measured depth.",
    "params": [],
    "elevationFromThing": True,
}


def run(source_df, params):
    """Compute the water-table altitude series from the qualified depth series.

    Args:
        source_df: DataFrame[phenomenonTime, value] - the qualified depth series.
        params: dict - must contain `elevation` (float), the Thing's reference altitude.

    Returns:
        DataFrame[phenomenonTime, value] - the water-table altitude series.
    """
    elevation = float(params["elevation"])
    out = source_df.copy()
    out["value"] = elevation - pd.to_numeric(out["value"])
    return out[["phenomenonTime", "value"]]
