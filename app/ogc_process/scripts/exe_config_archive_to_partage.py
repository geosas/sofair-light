#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Mar  4 14:07:55 2025

@author: tloree
"""
import pandas as pd

from app.sta_tools import sta_client


class ExeConfigPostDatastream:

    @classmethod
    def get_data(cls, url_dl, parametre):
        df_all = pd.DataFrame()
        r = sta_client.raw_get(url_dl, params=parametre)
        data = r.json()
        df_all = pd.concat(
            [df_all, pd.DataFrame(data['value'])], ignore_index=True)

        while '@iot.nextLink' in data:
            r = sta_client.raw_get(data['@iot.nextLink'])
            data = r.json()
            df_all = pd.concat(
                [df_all, pd.DataFrame(data['value'])], ignore_index=True)
        return df_all

    @classmethod
    def checkDoublon(cls, name, objet):
        # get name
        print("check if exist", objet)
        objetValue = cls.get_data(cls.url_partage+"/"+objet, {})
        if len(objetValue) == 0:
            print("Empty table for", objet)
            return name
        else:
            objetNew = [x for x in name if x not in objetValue['name'].values]
            objetOk = [x for x in name if x in objetValue['name'].values]
            print(objet, 'already published:', objetOk, "\n")
            print(objet, 'nouveau :', objetNew)
            return objetNew

    @classmethod
    def get_Datastream_src(cls, url_Multidata):
        parametre = {"$select": "name,description,unitOfMeasurements,properties,multiObservationDataTypes,selfLink",
                     "$expand": "Thing($select=name),ObservedProperties($select=name),Sensor($select=name)"}

        df_all = cls.get_data(url_Multidata, parametre)

        list_partage = []
        for idx, row in df_all.iterrows():
            if row['properties']['Share'] == 'Yes':
                row['name'] = row['properties']['nameShare']
                row['multiObservationDataTypes'] = row['multiObservationDataTypes'][0]

                row['Thing'] = row['Thing']['name']
                row['ObservedProperties'] = row['ObservedProperties'][0]['name']
                row['Sensor'] = row['Sensor']['name']
                # Internal keys removed from the published view. `frequency`,
                # `minValue` and `maxValue` are KEPT on partage (thresholds / displayed).
                for i in ['observationProcedure', 'Share', 'nameShare', 'nameUnique', 'foiId']:
                    row['properties'].pop(i, None)
                row['unitOfMeasurements'] = row['unitOfMeasurements'][0]

                list_partage.append(row)

        df_partage = pd.DataFrame(list_partage)
        df_partage = df_partage.rename(columns={
            'unitOfMeasurements': 'unitOfMeasurement',
            'multiObservationDataTypes': 'observationType',
            'Sensor': 'Sensors',
            'Thing': 'Things'})

        df_partage = df_partage.groupby('name').agg({
            'description': 'first',
            'unitOfMeasurement': 'first',
            'properties': 'first',
            'observationType': 'first',
            'Things': 'first',
            'Sensors': 'first',
            'ObservedProperties': 'first',
            '@iot.selfLink': lambda x: list(x)
        }).reset_index()

        for idx, row in df_partage.iterrows():
            row['properties']['RawLink'] = row['@iot.selfLink']
        return df_partage

    @classmethod
    def create_objet(cls, objet, parametre, df_partage):
        url_sensor = cls.url_archive + "/" + objet
        sensor = cls.get_data(url_sensor, parametre)
        if 'Locations@iot.count' in sensor.columns:
            sensor = sensor.drop(columns='Locations@iot.count')

        sensorUnique = cls.checkDoublon(df_partage[objet].values, objet)

        for idx, row in sensor.iterrows():
            if row['name'] in sensorUnique:
                if row['name'] in df_partage[objet].values:
                    r = sta_client.raw_post(cls.url_partage+"/"+objet,
                                            json=row.to_dict())
                    if not r.ok:
                        print(r.status_code)
                        print(r.text)

                        return {"error": r.text,
                                "code": r.status_code,
                                "objet": row['name']
                                }
        return True

    @classmethod
    def create_features_of_interest(cls, df_partage):
        """Copy the FeatureOfInterest archive -> partage (1 per Thing, same name)."""
        thing_names = list(pd.unique(df_partage['Things']))
        foi_archive = cls.get_data(
            cls.url_archive + "/FeaturesOfInterest",
            {"$select": "name,description,encodingType,feature"})
        if len(foi_archive) == 0:
            return True
        foiUnique = cls.checkDoublon(thing_names, "FeaturesOfInterest")
        for idx, row in foi_archive.iterrows():
            if row['name'] in thing_names and row['name'] in foiUnique:
                payload = {"name": row['name'], "description": row['description'],
                           "encodingType": row['encodingType'], "feature": row['feature']}
                r = sta_client.raw_post(
                    cls.url_partage + "/FeaturesOfInterest", json=payload)
                if not r.ok:
                    return {"error": r.text, "code": r.status_code, "objet": row['name']}
        return True

    @classmethod
    def create_datastream(cls, df_partage):
        sensor_partage = cls.get_data(
            cls.url_partage + "/Sensors", {'$select': 'name,id'})
        obsp_partage = cls.get_data(
            cls.url_partage + "/ObservedProperties", {'$select': 'name,id'})
        thing_partage = cls.get_data(
            cls.url_partage + "/Things", {'$select': 'name,id'})
        foi_partage = cls.get_data(
            cls.url_partage + "/FeaturesOfInterest", {'$select': 'name,id'})

        for idx, row in df_partage.iterrows():

            id_sensor = int(
                sensor_partage[sensor_partage.name == row['Sensors']]['@iot.id'].values[0])
            id_obsP = int(
                obsp_partage[obsp_partage.name == row['ObservedProperties']]['@iot.id'].values[0])
            id_thing = int(
                thing_partage[thing_partage.name == row['Things']]['@iot.id'].values[0])
            # id of the partage FOI (same name as the Thing) -> stored in properties
            foi_match = foi_partage[foi_partage.name == row['Things']]['@iot.id'] \
                if len(foi_partage) else []
            if len(foi_match) == 0:
                return {"error": f"partage FeatureOfInterest missing for the Thing {row['Things']}"}
            id_foi = int(foi_match.values[0])

            dataS = row.to_dict()
            for i in ['Things', 'Sensors', 'ObservedProperties', '@iot.selfLink']:
                dataS.pop(i)
            dataS['Sensor'] = {"@iot.id": id_sensor}
            dataS['ObservedProperty'] = {"@iot.id": id_obsP}
            dataS['Thing'] = {"@iot.id": id_thing}
            if not isinstance(dataS.get('properties'), dict):
                dataS['properties'] = {}
            dataS['properties']['foiId'] = id_foi

            r = sta_client.raw_post(cls.url_partage+"/Datastreams", json=dataS)

            if not r.ok:
                print(r.status_code)
                print(r.text)

                return {"error": r.text,
                        "code": r.status_code,
                        "objet": row['name']
                        }
        return True

    @classmethod
    def run(cls, url_partage, url_archive):

        cls.url_partage = url_partage
        cls.url_archive = url_archive

        url_MultidataS = cls.url_archive + "/MultiDatastreams"

        print("get Data")
        df_partage = cls.get_Datastream_src(url_MultidataS)
        DataStreamUnique = cls.checkDoublon(
            df_partage['name'].values, 'Datastreams')
        if len(DataStreamUnique) == 0:
            return True

        df_partage = df_partage[df_partage.name.isin(DataStreamUnique)]

        print("create Sensors partage")
        parametre = {
            "$select": 'description,name,encodingType,metadata,properties'}
        retour_sensor = cls.create_objet("Sensors", parametre, df_partage)
        if retour_sensor != True:
            print(retour_sensor)
            return retour_sensor

        print("create ObservedProperties")
        parametre = {"$select": 'description,name,definition,properties'}
        retour_obsp = cls.create_objet(
            "ObservedProperties", parametre, df_partage)
        if retour_obsp != True:
            print(retour_obsp)
            return retour_obsp

        print("create Things+Location")
        parametre = {"$select": 'name,description,properties',
                     "$expand": "Locations($select=name,description,encodingType,location)"}
        retour_thing = cls.create_objet("Things", parametre, df_partage)
        if retour_thing != True:
            print(retour_thing)
            return retour_thing
        ###################################

        print("create FeaturesOfInterest partage")
        retour_foi = cls.create_features_of_interest(df_partage)
        if retour_foi != True:
            print(retour_foi)
            return retour_foi

        print("create Datastream")
        retour_datastream = cls.create_datastream(df_partage)
        if retour_datastream != True:
            print(retour_datastream)
            return retour_datastream

        return True

