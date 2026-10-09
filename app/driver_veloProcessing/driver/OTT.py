import base64

import pandas as pd

from app.config_sensor import SENSOR_CREDENTIALS

# File extensions accepted for HTTPS ingestion (/sensors/OTT/<param>)
ALLOWED_EXTENSIONS = {"csv", "txt"}
# Substring matched against Sensor/name to pick the MultiDatastreams this driver
SENSOR_NAME_MATCH = "mini OTT"


def authenticate(request, param):
    """OTT sensor's own security: HTTP Basic authentication.

    Called by the /sensors/OTT/<param> route BEFORE any file processing.

    Args:
        request: the incoming Flask request.
        param (str): measurement point name (the <param> part of the URL).

    Returns:
        None if the request is authenticated, otherwise a Flask response tuple
        (body, code, headers) requesting Basic authentication.
    """
    users = SENSOR_CREDENTIALS.get("OTT", {})
    unauthorized = ("Unauthorized", 401, {
                    "WWW-Authenticate": 'Basic realm="OTT"'})

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        return unauthorized
    try:
        encoded = auth_header.split(" ", 1)[1]
        username, password = base64.b64decode(
            encoded).decode("utf-8").split(":", 1)
    except Exception:
        return unauthorized

    if username in users and users[username] == password:
        return None
    return unauthorized


def run(rawFile, observedProperties):
    """Driver for sensor OTT

    This driver converts a raw OTT Orpheus Mini file (',' separated, one
    header line) into a pandas DataFrame. The format depends on the
    observedProperties of the MultiDatastreams:

    Groundwater (Groundwater depth, Groundwater temperature), 4 columns:
    "DD/MM/YYYY","HH:MM:SS","m","°C"
    30/09/2021,00:00:00,-3.676,12.300

    Stream (Stream stage, Stream temperature), 6 columns:
    "DD/MM/YYYY","HH:MM:SS","m","","°C",""

    The output DataFrame columns are:
    "phenomenonTime", observedProperty 1, observedProperty 2


    Args:
        rawFile (StringIO): rawFile is a StringIO instance containing the CSV (or .txt) file content as text, allowing reading by pandas or other file-processing tools.
        observedProperties (list): list of the file's observedProperties

    Returns:
        pandas.DataFrame(): formatted DataFrame ready to be sent to SensorThings
    """
    print('OTT decoding')

    ott_grounwater = ['Groundwater depth', 'Groundwater temperature']
    ott_stream = ['Stream stage', 'Stream temperature']

    df = pd.read_csv(rawFile, sep=',', skiprows=1, header=None)

    if set(observedProperties).issubset(set(ott_grounwater)) and len(observedProperties) == len(ott_grounwater):
        if df.shape[1] != 4:
            raise ValueError(
                f"Expected 4 columns separated by ',', got {df.shape[1]}: check the file separator")

        df.columns = ['date', 'heure', 'Groundwater depth',
                      'Groundwater temperature']

    elif set(observedProperties).issubset(set(ott_stream)) and len(observedProperties) == len(ott_stream):
        if df.shape[1] != 6:
            raise ValueError(
                f"Expected 6 columns separated by ',', got {df.shape[1]}: check the file separator")

        df.columns = ['date', 'heure', 'Stream stage',
                      "chepas", 'Stream temperature', "chepas2"]
    else:
        raise ValueError(
            f"Unable to find the correct ObservedProperties: {observedProperties}")

    df['phenomenonTime'] = df['date'] + " " + df['heure']
    df['phenomenonTime'] = pd.to_datetime(
        df['phenomenonTime'], format="%d/%m/%Y %H:%M:%S", utc=True)

    df = df[['phenomenonTime'] + observedProperties]

    return df


# don't forget to zip the data in a dir afterwards or put it in parquet?
