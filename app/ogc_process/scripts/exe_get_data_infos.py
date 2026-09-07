#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Mar  4 14:07:55 2025

@author: tloree
"""
import pandas as pd
from io import StringIO
from app.config import Config
from app.sta_tools import sta_client


class ExeGetDataInfos:

    @classmethod
    def get_data(cls, url_x, param):
        print("get Data")
        df_all = pd.DataFrame()
        r = sta_client.raw_get(url_x, params=param)
        data = r.json()
        if len(data['value']) == 0:
            return df_all
        if len(data['value'][0]['dataArray']) == 0:
            return df_all
        df_all = pd.DataFrame(
            data['value'][0]['dataArray'], columns=data['value'][0]['components'])
        return df_all

    @classmethod
    def run(cls, url_archive, url_partage, idp):

        print("start download")

        parametre = {
            "$select": "result,phenomenonTime",
            "$orderby": "phenomenonTime asc",
            "$resultFormat": "dataArray",
        }
        rqt = f"{Config.STALT_archive_proxyname}v1.1/MultiDatastreams({idp})/Observations"
        df = cls.get_data(rqt, parametre)
        if len(df) == 0:
            response = {
                "last_date_qualification": "",
                "value": []
            }
            return response, 201
        print("download finish")
        print("convert date")
        df["phenomenonTime"] = pd.to_datetime(
            df["phenomenonTime"], errors="raise", utc=True)
        df = df.sort_values(by="phenomenonTime")
        if len(df) < 100000:
            df["date"] = pd.to_datetime(
                df["phenomenonTime"].dt.strftime('%Y-%m-%d %H')
            )
        else:
            df["date"] = pd.to_datetime(
                df["phenomenonTime"].dt.strftime('%Y-%m-%d')
            )

        print("build metrics")
        df[['result', 'code', 'partage']] = pd.DataFrame(
            df['result'].tolist(), index=df.index)

        df_median = df.groupby(by="date", as_index=False).median()
        df_min = df.groupby(by="date", as_index=False).min()
        df_max = df.groupby(by="date", as_index=False).max()

        df_resume = pd.DataFrame()
        df_resume['date'] = df_median['date']
        df_resume['result'] = df_min['result'].astype(
            str) + ';' + df_median['result'].astype(str) + ';' + df_max['result'].astype(str)

        # the "pagination" for qualification is missing
        output = StringIO()
        df_resume.to_csv(output, index=False, header=False)
        output.seek(0)

        df_resume_2 = pd.DataFrame()
        df_resume_2['date'] = df_median['date']
        df_resume_2['result'] = df_min['partage'].astype(
            str) + ';' + df_median['partage'].astype(str) + ';' + df_max['partage'].astype(str)

        # the "pagination" for qualification is missing
        output_2 = StringIO()
        df_resume_2.to_csv(output_2, index=False, header=False)
        output_2.seek(0)


        r = sta_client.raw_get(
            f"{url_archive}/MultiDatastreams({idp})?$select=properties")

        data_name_partage = r.json()['properties']['nameShare']

        url_qualif = f"{url_partage}/Datastreams?$select=name,phenomenonTime,id&$filter=name eq '{data_name_partage}'"
        print(url_qualif)

        r = sta_client.raw_get(url_qualif)
        # here we must retrieve the dates at least daily to know whether the data is already qualified and
        # and set the background color
        datastream_partage = f"{Config.STALT_partage_proxyname}Datastreams({r.json()['value'][0]['@iot.id']})/Observations?$resultFormat=csv&$groupby=day"
        print(datastream_partage)
        df_qualif = pd.read_csv(datastream_partage)

        if r.json()['value'] == []:
            date_qualification = []
        date_qualification = list(df_qualif['phenomenonTime'].values)
        # return send_file(output, mimetype='text/csv', as_attachment=True, download_name=f'datastream_resume.csv')
        response = {
            "date_qualification": date_qualification,
            "value": output.getvalue(),
            "value_2": output_2.getvalue()
        }

        return response, 201
