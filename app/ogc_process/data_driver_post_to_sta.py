from flask import url_for
import json
from typing import Optional
from pydantic import BaseModel, Field
import os
from werkzeug.utils import secure_filename

from app.config import Config
from app.sta_tools import sta_client
from app.sta_tools.archive_observations import write_archive_observations
from app.sta_tools.qualification_automatic import AutomaticQualification
import math

import base64
from io import StringIO
import pandas as pd
import chardet
import re
from app.driver_veloProcessing.manager import ScriptManagerVeloProcessing
import pathlib

from time import time

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
import psycopg


class DataDriverPostToSTA:
    metadata = {
        "id": "dataDriverPostToSTA",
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
            "sync-execute",  # add async as well
        ],
        "outputTransmission": [
            "value"
        ]
    }

    class Schema(BaseModel):
        # it is possible to replace ... with a default value
        rawFile64: str = Field(..., title="Fichier data brute", min_length=1,
                               description="Raw data file encoded in base64")
        driver: str = Field(..., title="driver", min_length=1,
                            description="Driver to use for read rawFile64")
        name: str = Field(..., title="name", min_length=1,
                          description="First name of the datastream, for exemple EAMQ_stream will be EAMQ")
        overlap: str = Field("skip", title="overlap",
                             description="How to handle rows overlapping already-stored data: "
                                         "'skip' (default, keep stored) or 'overwrite'")

    class OutputSchema(BaseModel):
        reponse: dict = Field(..., title="Result",
                              description="A dictionary containing the process response")
        code: int = Field(..., title="code",
                          description="HTML code of the process for the api")

    @classmethod
    def run(cls, validated_data: "DataDriverPostToSTA.Schema"):
        """

        """

        base64_string = validated_data.rawFile64
        dataSname = validated_data.name
        driver = validated_data.driver
        overlap = validated_data.overlap if validated_data.overlap in (
            "skip", "overwrite") else "skip"

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
        parametre = {"$filter": f"(properties/observationProcedure eq 'veloProcessing' or properties/observationProcedure eq 'httpsConnected') and substringof('{driver}',Sensor/name) and substringof('{dataSname}',name) ",
                     "$select": "id,name,properties",
                     "$expand": "Sensor($select=name),ObservedProperties($select=name)"}
        try:
            r = sta_client.get(
                "archive", "/MultiDatastreams", params=parametre)
        except Exception as e:
            return {"error": "Le service sensorThings archive ne semble pas actif", "exception": str(e)}, 500
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
            df = ScriptManagerVeloProcessing.run_script(
                driver, csv_file_like, obsP)

        except Exception as e:
            return {"error": "Erreur lors de la lecture du fichier", "exception": str(e)}, 500

        df['phenomenonTime'] = df['phenomenonTime'].dt.strftime(
            '%Y-%m-%dT%H:%M:%SZ')
        df = df.sort_values('phenomenonTime').reset_index(drop=True)
        df["resultTime"] = (
            pd.Timestamp.today().tz_localize("Europe/Paris").astimezone("UTC")
        )
        df["resultTime"] = df["resultTime"].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        df['qualification'] = -1

        id_MultiDatastreams = []
        for i in MultiDatastreams:

            # id of the Thing's FeatureOfInterest, stored in properties at config time
            foi_id = (i.get('properties') or {}).get('foiId')
            if foi_id is None:
                return {"error": f"foiId missing in the MultiDatastream '{i.get('name')}' properties: rerun the configuration"}, 500

            df_post = df[['phenomenonTime', i["ObservedProperties"]['name'],
                          'qualification', 'resultTime']]
            df_post = df_post.rename(
                columns={i["ObservedProperties"]['name']: 'result'})
            df_post = df_post.dropna()
            df_post['FOI'] = foi_id

            # threshold pre-qualification: out of [minValue, maxValue] -> Wrong
            df_post = AutomaticQualification.qualify_dataframe(
                df_post, i['properties'],
                result_col='result', qf_col='qualification')

            df_post['result'] = df_post.apply(lambda row: [row['result'],
                                                           row['qualification'],
                                                           row['result']], axis=1).tolist()

            df_post["RESULT_TYPE"] = 2
            df_post["PHENOMENON_TIME_END"] = df_post['phenomenonTime']
            df_post["MULTI_DATASTREAM_ID"] = i["@iot.id"]
            # df_post['result'] = df_post['result'].apply(json.dumps)
            df_post.drop('qualification', axis=1, inplace=True)

            df_post = df_post.rename(columns={"phenomenonTime": "PHENOMENON_TIME_START",
                                              "result": "RESULT_JSON",
                                              "FOI": "FEATURE_ID",
                                              "resultTime": "RESULT_TIME"
                                              })
            datetime_cols = [
                'PHENOMENON_TIME_START',
                'PHENOMENON_TIME_END',
                'RESULT_TIME'
            ]

            for col in datetime_cols:
                df_post[col] = pd.to_datetime(df_post[col])

            # --- Overlap with already-stored data (per datastream) ---
            # 'skip' (default): drop rows whose timestamp is already stored.
            # 'overwrite': replace the imported range (delete + insert).
            delete_range = None
            if len(df_post):
                tmin = df_post['PHENOMENON_TIME_START'].min().to_pydatetime()
                tmax = df_post['PHENOMENON_TIME_START'].max().to_pydatetime()
                if overlap == "overwrite":
                    delete_range = (tmin, tmax)
                else:
                    with psycopg.connect(**Config.DB_archive) as conn_ov:
                        with conn_ov.cursor() as cur_ov:
                            cur_ov.execute(
                                'SELECT TO_CHAR("PHENOMENON_TIME_START" AT TIME ZONE \'UTC\', '
                                '\'YYYY-MM-DD"T"HH24:MI:SS"Z"\') FROM "OBSERVATIONS" '
                                'WHERE "MULTI_DATASTREAM_ID" = %s '
                                'AND "PHENOMENON_TIME_START" BETWEEN %s AND %s',
                                (i["@iot.id"], tmin, tmax))
                            existing = {row[0] for row in cur_ov.fetchall()}
                    if existing:
                        df_post = df_post[~df_post['PHENOMENON_TIME_START']
                                          .dt.strftime('%Y-%m-%dT%H:%M:%SZ').isin(existing)]

            if len(df_post) == 0:
                id_MultiDatastreams.append(i["@iot.id"])
                continue  # nothing new to insert for this datastream

            print('envoie data')
            write_archive_observations(df_post, i["@iot.id"], Config.DB_archive,
                                       delete_range=delete_range)
            id_MultiDatastreams.append(i["@iot.id"])

        return {"message": "file saved successfully",
                "id": id_MultiDatastreams}, 200

    @classmethod
    def get_metadata(cls):
        return cls.metadata
