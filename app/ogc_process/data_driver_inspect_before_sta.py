from flask import url_for
import json
from typing import Optional
from pydantic import BaseModel, Field
import os
from werkzeug.utils import secure_filename

from app.config import Config
import math

import base64
from io import StringIO
import pandas as pd
import chardet
import re
from app.driver_veloProcessing.manager import ScriptManagerVeloProcessing
from app.sta_tools import sta_client
import pathlib

from time import time


class DataDriverInspectBeforeSTA:
    metadata = {
        "id": "dataDriverInspectBeforeSTA",
        "version": 1,
        "title": "Post Data to STA with driver",
        "description": "Post Data to STA with driver; data is pre-qualified as in-range (raw, to qualify) or out-of-range (bad data) based on the minValue, maxValue of the datastreams",
        "keywords": ["data", "STA", "OGC"],
        "links": [{
            "type": "text/html",
            "rel": "about",
            "title": "information",
            "href": Config.URL_PROJET,
            "hreflang": "en-US"
        }],
        "jobControlOptions": [
            "sync-execute",  # add async too
        ],
        "outputTransmission": [
            "value"
        ]
    }

    class Schema(BaseModel):
        # it is possible to replace ... with a default value
        rawFile64: str = Field(..., title="Raw data file", min_length=1,
                               description="Raw data file encoded in base64")
        driver: str = Field(..., title="driver", min_length=1,
                            description="Driver to use for read rawFile64")
        name: str = Field(..., title="name", min_length=1,
                          description="First name of the datastream, for exemple EAMQ_stream will be EAMQ")

    class OutputSchema(BaseModel):
        response: dict = Field(..., title="Result",
                               description="A dictionary containing the process response")
        code: int = Field(..., title="code",
                          description="HTML code of the process for the api")

    @classmethod
    def handle_date(cls, first_date, last_date):
        first_dt = pd.to_datetime(first_date)  # e.g. "2025-04-20T12:34:56Z"
        last_dt = pd.to_datetime(last_date)

        # Subtract/add 30 days
        start_window = first_dt - pd.Timedelta(days=30)
        end_window = last_dt + pd.Timedelta(days=30)

        # If you want to put them back in ISO format with 'Z'
        start_window = start_window.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_window = end_window.strftime('%Y-%m-%dT%H:%M:%SZ')

        return start_window, end_window

    @classmethod
    def run(cls, validated_data: "DataDriverInspectBeforeSTA.Schema"):
        """

        """

        base64_string = validated_data.rawFile64
        dataSname = validated_data.name
        driver = validated_data.driver

        dataSname = pathlib.Path(dataSname).stem
        dataSname = dataSname.split('_')[0]
        print(dataSname)

        try:
            csv_bytes = base64.b64decode(base64_string)
        except Exception as e:
            return {"error": "Error during Base64 decoding", "exception": str(e)}, 400

        # Detect the CSV file encoding

        detection = chardet.detect(csv_bytes[0:10000])
        # Default to utf-8 if not detected
        encoding = detection.get('encoding', 'utf-8')
        confidence = detection.get('confidence', 0)
        print(
            f"Detected encoding: {encoding} with a confidence of {confidence}")

        try:
            # Decode the bytes to a string using the detected encoding
            csv_string = csv_bytes.decode(encoding)
        except Exception as e:
            return {"error": f"Error while decoding using the {encoding} encoding",
                    "exception": str(e)}, 500

        # Turn the string into a file object via StringIO
        csv_file_like = StringIO(csv_string)

        # get info STA
        # Accept both bike-collected CSV (veloProcessing) and HTTPS-pushed
        # connected sensors (httpsConnected): same driver pipeline, two entry points.
        params = {"$filter": f"(properties/observationProcedure eq 'veloProcessing' or properties/observationProcedure eq 'httpsConnected') and substringof('{driver}',Sensor/name) and substringof('{dataSname}',name) ",
                     "$select": "id,name",
                     "$expand": "Sensor($select=name),ObservedProperties($select=name)"}
        try:
            r = sta_client.proxy_get(
                "archive", "MultiDatastreams", params=params)
        except Exception as e:
            return {"error": "The archive SensorThings service does not appear to be active", "exception": str(e)}, 500
        if not r.ok:
            return {"error": "Unable to find the measurement point in the SensorThings service, check its name", "exception": str(e)}, 500

        MultiDatastreams = r.json()['value']
        if len(MultiDatastreams) == 0:
            return {"error": "No Datastreams found for this file, check its Name and the Driver",
                    }, 500
        obsP = []
        for i in MultiDatastreams:
            i["ObservedProperties"] = i["ObservedProperties"][0]
            obsP.append(i["ObservedProperties"]['name'])
        #####################
        try:
            print("start driver")
            df = ScriptManagerVeloProcessing.run_script(
                driver, csv_file_like, obsP)

        except Exception as e:
            print(e)
            return {"error": "Error while reading the file", "exception": str(e)}, 500
        print("Driver decoding ok")

        df = df.sort_values('phenomenonTime').reset_index(drop=True)
        first_date = df['phenomenonTime'].iloc[0].strftime(
            '%Y-%m-%dT%H:%M:%S')+"Z"
        last_date = df['phenomenonTime'].iloc[-1].strftime(
            '%Y-%m-%dT%H:%M:%S')+"Z"

        first_window, last_window = cls.handle_date(first_date, last_date)
        print(first_window, last_window)
        for i in MultiDatastreams:

            params = {
                "$select": "result,phenomenonTime",
                "$orderby": "phenomenonTime asc",
                "$resultFormat": "dataArray",
                "$filter": f"phenomenonTime ge {first_window} and phenomenonTime le {last_window} "}
            obs_url = f"{Config.STALT_archive_proxyname}v1.1/MultiDatastreams({i['@iot.id']})/Observations"

            r = sta_client.raw_get(obs_url, params=params)

            data = r.json()
            if len(data['value']) == 0:
                continue
            if len(data['value'][0]['dataArray']) == 0:
                continue

            df_inter = pd.DataFrame(
                data['value'][0]['dataArray'], columns=data['value'][0]['components'])
            df_inter['result'] = df_inter['result'].apply(lambda x: x[2])
            df_inter = df_inter.rename(
                columns={"result": i['ObservedProperties']['name']+"_archive"})
            df_inter['phenomenonTime'] = pd.to_datetime(
                df_inter['phenomenonTime'])

            df = df.merge(df_inter, on='phenomenonTime', how='outer')

            df.loc[df[i['ObservedProperties']['name']] == df[i['ObservedProperties']
                                                             ['name']+"_archive"], i['ObservedProperties']['name']] = None

        if len(data['value']) != 0 and len(data['value'][0]['dataArray']) != 0:
            last_observations = df_inter['phenomenonTime'].iloc[0].strftime(
                '%Y-%m-%dT%H:%M:%S')+"Z"
        else:
            last_observations = ""
        df = df.sort_values('phenomenonTime').reset_index(drop=True)

        df_test = df[(df['phenomenonTime'] >= first_date) &
                     (df['phenomenonTime'] <= last_date)]
        archive_duplicates = len(
            df_test[df_test[i['ObservedProperties']['name']].isnull()])

        # phenomenonTime is a pandas Timestamp (parsed by the driver, then merged
        # with the archive observations): df.values.tolist() would put Timestamp
        # objects in the dataArray and json.dump can't serialise them. Format it
        # back to an ISO UTC string (done after the date comparisons above, which
        # need the datetime dtype).
        df['phenomenonTime'] = pd.to_datetime(
            df['phenomenonTime'], utc=True).dt.strftime('%Y-%m-%dT%H:%M:%SZ')

        df = df.replace(math.nan, None)
        data = {
            "components": df.columns.tolist(),
            "dataArray": df.values.tolist()
        }

        return {"message": "file decoded successfully", "values": data,
                "first_date": first_date, "last_date": last_date,
                "last_observations": last_observations,
                "archive_duplicates": archive_duplicates,
                "len_data_import": len(df_test)}, 200

    @classmethod
    def get_metadata(cls):
        return cls.metadata
