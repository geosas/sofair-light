import pandas as pd



# File extensions accepted for HTTPS ingestion (/sensors/OTT/<param>)
ALLOWED_EXTENSIONS = {"csv"}
# Substring matched against Sensor/name to pick the MultiDatastreams this driver
SENSOR_NAME_MATCH = "OTT KL 010 Electric Contact Gauge"

def run(rawFile, observedProperties):
    """Driver for light probe

    This driver converts a Sonde csv file into a pandas DataFrame.
    Next update will be for xlsx file

    Args:
        rawFile (.txt): Sonde CSV file
        observerdProperties (list): list of the file's observedProperties

    Returns:
        pandas.DataFrame(): formatted DataFrame ready to be sent to SensorThings
    """
    print('sonde decode')

    sonde_groundwater = ['Groundwater depth']
    sonde_stream = ['Stream stage']

    df = pd.read_csv(rawFile, sep=',')

    if set(observedProperties).issubset(set(sonde_groundwater)) and len(observedProperties) == len(sonde_groundwater):
        if df.shape[1] != 2:
            raise ValueError(
                f"Expected 2 columns separated by ',', got {df.shape[1]}: check the file separator")

        df.columns = ['phenomenonTime', 'Groundwater depth']

    elif set(observedProperties).issubset(set(sonde_stream)) and len(observedProperties) == len(sonde_stream):
        if df.shape[1] != 2:
            raise ValueError(
                f"Expected 2 columns separated by ',', got {df.shape[1]}: check the file separator")

        df.columns = ['phenomenonTime', 'Stream stage']
    else:
        raise ValueError(
            f"Unable to find the correct ObservedProperties: {observedProperties}")

    
    df['phenomenonTime'] = pd.to_datetime(df['phenomenonTime'], utc=True)

    return df
