"""Template driver for VeloProcessing.

Copy this file into app/driver_veloProcessing/driver/ and rename it to a single
word matching the archive service Sensors.name (e.g. "OTT.py" for
"Orpheus mini OTT"). The manager auto-discovers any *.py in that folder.
"""
import pandas as pd


def run(rawFile, observedProperties):
    """One-line summary of what this driver decodes.

    Longer description: which sensor and file format this driver handles.

    Args:
        rawFile: the sensor file as an in-memory file-like object
            (open it with pandas).
        observedProperties (list): names of the observed properties expected
            for the point of measure (use them to name/select the columns).

    Returns:
        pandas.DataFrame: a "phenomenonTime" column (str, UTC,
            %Y-%m-%dT%H:%M:%SZ) followed by one column per observed property.
    """
    # parse rawFile and populate the dataframe below.
    df = pd.DataFrame({
        "phenomenonTime": [],
        # "observed property name": [],
    })
    return df
