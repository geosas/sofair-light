#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jun 12 14:26:16 2024

@author: tloree
"""

import pandas as pd  # requires the openpyxl, xlrd libraries to open the xlsx
import json
import warnings

from app.sta_tools import sta_client
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning, module='openpyxl')
pd.options.mode.chained_assignment = None  # default='warn'


class instanceST():
    def __init__(self, urlServeur, username, password):
        self.urlServeur = urlServeur
        self.username = username
        self.password = password
        self.dico_bug_post_obs = {"name_thing": [], "id_thing": [
        ], "name_datastream": [], "id_datastream": []}

    def connexion(self):
        print("connexion", self.username, "to ", self.urlServeur)
        json_data = json.dumps(
            {"username": self.username, "password": self.password})
        r = sta_client.raw_post(self.urlServeur+"login",
                                headers={'Content-Type': 'application/json'}, data=json_data)
        print(r.status_code)
        if not r.ok:
            return False
        self.token = r.json()['token']
        return True

    def log_out(self):
        r = sta_client.raw_get(self.urlServeur+"logout")
        print(r.status_code)
        print(r.text)

    def post_data_serveur(self, objet, data):
        print('post Data')
        for i in data:
            self.test_json = i
            json_data = json.dumps(i)
            lien = "%s/%s" % (self.urlServeur, objet)

            r = sta_client.raw_post(lien,
                                    headers={'Content-Type': 'application/json',
                                             'Authorization': "Bearer {}".format(self.token)}, data=json_data)

            if not r.ok:
                print("error")
                print(lien)
                print(r.status_code)
                print(r.text)

                return {"error": r.text,
                        "code": r.status_code,
                        "url": lien
                        }
        return True

    def get_data(self, url_x):
        print("get Data")
        df_all = pd.DataFrame()
        r = sta_client.raw_get(url_x)
        data = r.json()
        df_all = pd.concat(
            [df_all, pd.DataFrame(data['value'])], ignore_index=True)

        while '@iot.nextLink' in data:
            r = sta_client.raw_get(data['@iot.nextLink'])
            data = r.json()
            df_all = pd.concat(
                [df_all, pd.DataFrame(data['value'])], ignore_index=True)
        return df_all

    def coord_lister(self, geom):  # if polygon in geopandas
        coords = list(geom.exterior.coords)
        return (coords)

    def split_list(self, a_list):  # if array data observations trop grande
        if len(a_list) > 15000:
            print("lightened list")
            half = len(a_list)//2
            return [a_list[:half], a_list[half:]]
        return [a_list]

    def addTableConfig(self, chemin):
        print("open xlsx table")
        self.cheminXlsx = chemin
        self.dataStreamSrc = pd.read_excel(
            self.cheminXlsx, sheet_name="4_datastream").drop_duplicates("name")
        self.variableName = self.dataStreamSrc['name'].unique()
        print("xlsx ok !")

    def checkDoublon(self, name, objet):
        # get name
        print("check if exist", objet)
        objetValue = self.get_data(self.urlServeur + "/"+objet)
        if len(objetValue) == 0:
            print("Empty table for", objet)
            return name
        else:
            objetNew = [x for x in name if x not in objetValue['name'].values]
            objetOk = [x for x in name if x in objetValue['name'].values]
            print(objet, 'already published:', objetOk, "\n")
            print(objet, 'nouveau :', objetNew)
            return objetNew

    def getIdObjet(self, objet, name):

        r = sta_client.raw_get("%s/%s?$filter=name eq '%s'" %
                               (self.urlServeur, objet, name))

        objet_json = r.json()['value']
        if len(objet_json) != 1:
            print("the object", objet, name, " could not be found")
            return -1
        else:
            return objet_json[0]['@iot.id']

    def creationSensor(self):
        print("publishing sensors")
        sensorSrc = pd.read_excel(self.cheminXlsx, sheet_name="2_sensor")
        self.sensorName = sensorSrc['name'].unique()
        sensorSrc = sensorSrc.drop_duplicates("name")

        sensorUnique = self.checkDoublon(sensorSrc['name'].values, "Sensors")
        if len(sensorUnique) == 0:
            print("no new Sensor to publish")
            return True
        sensorSrc = sensorSrc[sensorSrc['name'].isin(sensorUnique)]
        sensorSrc = sensorSrc.fillna("")

        valeurs_a_supprimer = [
            'name', 'description', 'encodingType', 'metadata']
        col = list(sensorSrc.columns)
        properties_name = [
            item for item in col if item not in valeurs_a_supprimer and not item.startswith('observedProperty')]

        Sensor = []
        for idx, row in sensorSrc.iterrows():
            print(row['name'])
            properties = {i: row[i] for i in properties_name if row[i] != ''}
            Sensor.append({
                "name": row['name'],
                "description": row['description'],
                "encodingType": row['encodingType'],
                "metadata": row['metadata'],
                "properties": properties
            })

        return self.post_data_serveur("Sensors", Sensor)

    def creationObservedProperties(self, code_qualification):
        print("publishing observed properties")
        obspSrc = pd.read_excel(
            self.cheminXlsx, sheet_name="1_observedProperty")
        self.obspName = obspSrc['name'].unique()
        obspSrc = obspSrc.drop_duplicates("name")

        obspUnique = self.checkDoublon(
            list(obspSrc['name'].values)+[code_qualification['name']], "ObservedProperties")
        if len(obspUnique) == 0:
            print("no new ObsP to publish")
            return True
        obspSrc = obspSrc[obspSrc['name'].isin(obspUnique)]
        obspSrc = obspSrc.fillna("")

        col = list(obspSrc.columns)
        valeurs_a_supprimer = ['name', 'definition', 'description',
                               'unit-name', 'unit-symbol', 'unit-definition']
        properties_name = [
            item for item in col if item not in valeurs_a_supprimer]

        obsp = []
        for idx, row in obspSrc.iterrows():
            print(row['name'])
            properties = {i: row[i] for i in properties_name if row[i] != ''}
            obsp.append({
                "name": row['name'],
                "description": row['description'],
                "definition": row['definition'],
                "properties": properties
            })
        if code_qualification['name'] in obspUnique:
            print(code_qualification['name'])
            # Build a valid STA ObservedProperty: only name/definition/description
            # + a free-form 'properties' JSON. The flag vocabulary goes in
            # 'properties'; app-only fields (severity, raw_default) stay in Config
            # and must NOT be posted as top-level entity fields (FROST rejects
            # unknown fields -> 500 "Failed to store data").
            obsp.append({
                "name": code_qualification['name'],
                "description": code_qualification.get('description', ''),
                "definition": code_qualification.get('definition', ''),
                "properties": code_qualification.get('properties', {}),
            })
        return self.post_data_serveur("ObservedProperties", obsp)

    def creationThings(self):
        print("publishing things")
        thingSrc = pd.read_excel(self.cheminXlsx, sheet_name="3_thing")

        self.thingName = thingSrc['name'].unique()
        thingSrc = thingSrc.drop_duplicates("name")

        thingSrcUnique = self.checkDoublon(thingSrc['name'].values, "Things")
        if len(thingSrcUnique) == 0:
            print("no new Things to publish")
            return True
        thingSrc = thingSrc[thingSrc['name'].isin(thingSrcUnique)]

        valeurs_a_supprimer = ['name', 'description', 'type', 'x', 'y']
        thingSrc = thingSrc.fillna("")
        col = list(thingSrc.columns)
        properties_name = [
            item for item in col if item not in valeurs_a_supprimer and not item.startswith('sensor')]

        thing = []
        for idx, row in thingSrc.iterrows():
            print(row['name'])

            properties = {i: row[i] for i in properties_name if row[i] != ''}

            thing.append({
                "name": row['name'],
                "description": row['description'],
                "properties": properties,
                "Locations": [
                    {
                        "name": row['name'],
                        "description":  row['description'],
                        "encodingType": "application/geo+json",
                        "location": {
                            "type": "Feature",
                                    "geometry": {
                                        "type": row['type'],
                                        "coordinates": [row['x'], row['y']]
                                    },
                        }
                    }
                ]
            })

        return self.post_data_serveur("Things", thing)

    def creationFeaturesOfInterest(self):
        """Create one FeatureOfInterest per Thing (name, description, geometry from
        the 3_thing sheet). The FOI carries the SAME name as the Thing: it's the key
        which then allows retrieving its id. Idempotent (checkDoublon)."""
        print("publishing FeaturesOfInterest")
        thingSrc = pd.read_excel(self.cheminXlsx, sheet_name="3_thing")
        thingSrc = thingSrc.drop_duplicates("name")

        foiUnique = self.checkDoublon(
            thingSrc['name'].values, "FeaturesOfInterest")
        if len(foiUnique) == 0:
            print("no new FeatureOfInterest to publish")
            return True
        thingSrc = thingSrc[thingSrc['name'].isin(foiUnique)]
        thingSrc = thingSrc.fillna("")

        foi = []
        for idx, row in thingSrc.iterrows():
            print(row['name'])
            foi.append({
                "name": row['name'],
                "description": row['description'],
                "encodingType": "application/geo+json",
                "feature": {
                    "type": "Feature",
                    "geometry": {
                        "type": row['type'],
                        "coordinates": [row['x'], row['y']]
                    }
                }
            })

        return self.post_data_serveur("FeaturesOfInterest", foi)

    def creationDataStreams(self):
        print("publishing datastreams")

        self.dataStreamName = self.dataStreamSrc['name'].unique()

        dataStreamUnique = self.checkDoublon(
            self.dataStreamSrc['name'].values, "Datastreams")
        if len(dataStreamUnique) == 0:
            print("no new Datastreams to publish")
            return True
        self.dataStreamSrc = self.dataStreamSrc[self.dataStreamSrc['name'].isin(
            dataStreamUnique)]

        datastream = []

        self.dataStreamSrc = self.dataStreamSrc.fillna("")

        col = list(self.dataStreamSrc.columns)
        valeurs_a_supprimer = ["name", "description", "observationType",
                               "unit-name", "unit-symbol", "unit-definition"]
        properties_name = [
            item for item in col if item not in valeurs_a_supprimer]

        for idx, row in self.dataStreamSrc.iterrows():

            properties = {i: row[i] for i in properties_name if row[i] != ''}

            idSensor = self.getIdObjet(
                "Sensors", row['nameUnique'].split('_')[1])
            idObsp = self.getIdObjet(
                "ObservedProperties", row['nameUnique'].split('_')[2])
            idThing = self.getIdObjet(
                "Things", row['nameUnique'].split('_')[0])
            if (idSensor == -1 or idObsp == -1 or idThing == -1):
                return {
                    "error": f"Can't find the link between Sensor-Thing-ObservedProperty AND the Datastream {row['nameUnique']}",

                }
            datastream.append({
                "name": row['name'],
                "description": row['description'],
                "observationType": row["observationType"],
                "unitOfMeasurement": {
                    "name": row['unit-name'],
                    "symbol": row['unit-symbol'],
                    "definition": row['unit-definition']
                },
                "Sensor": {"@iot.id": idSensor},
                "ObservedProperty": {"@iot.id": idObsp},
                "Thing": {"@iot.id": idThing},
                "properties": properties
            })

        return self.post_data_serveur("Datastreams", datastream)

    def creationMultiDataStreams(self, code_qualification):
        print("publishing datastreams")

        self.dataStreamName = self.dataStreamSrc['name'].unique()

        dataStreamUnique = self.checkDoublon(
            self.dataStreamSrc['name'].values, "MultiDatastreams")
        if len(dataStreamUnique) == 0:
            print("no new Datastreams to publish")
            return True
        self.dataStreamSrc = self.dataStreamSrc[self.dataStreamSrc['name'].isin(
            dataStreamUnique)]

        datastream = []

        self.dataStreamSrc = self.dataStreamSrc.fillna("")

        col = list(self.dataStreamSrc.columns)
        valeurs_a_supprimer = ["name", "description", "observationType",
                               "unit-name", "unit-symbol", "unit-definition"]
        properties_name = [
            item for item in col if item not in valeurs_a_supprimer]

        idQF = self.getIdObjet("ObservedProperties",
                               code_qualification['name'])
        if idQF == -1:
            return {
                "error": "Can't find the Qualification code in ObservedProperties : {code_qualification['name']}",

            }

        for idx, row in self.dataStreamSrc.iterrows():

            properties = {i: row[i] for i in properties_name if row[i] != ''}

            # frequency: publish as a structured object {value, unit} rather than
            # the raw "frequency (min)" spreadsheet column.
            freq = properties.pop('frequency (min)', '')
            if freq != '':
                try:
                    fval = float(freq)
                    fval = int(fval) if fval.is_integer() else fval
                except (TypeError, ValueError):
                    fval = freq
                properties['frequency'] = {'value': fval, 'unit': 'min'}

            thing_name = row['nameUnique'].split('_')[0]
            idSensor = self.getIdObjet(
                "Sensors", row['nameUnique'].split('_')[1])
            idObsp = self.getIdObjet(
                "ObservedProperties", row['nameUnique'].split('_')[2])
            idThing = self.getIdObjet("Things", thing_name)
            if (idSensor == -1 or idObsp == -1 or idThing == -1):
                return {
                    "error": f"Can't find the link between Sensor-Thing-ObservedProperty AND the Datastream {row['nameUnique']}",

                }
            # Thing's FeatureOfInterest (same name) -> id stored in properties,
            # read as-is at the time of POSTing observations.
            idFOI = self.getIdObjet("FeaturesOfInterest", thing_name)
            if idFOI == -1:
                return {
                    "error": f"FeatureOfInterest missing for the Thing {thing_name} (rerun the config)",
                }
            properties['foiId'] = idFOI

            datastream.append({
                "name": row['name'],
                "description": row['description'],
                "observationType": "http://www.opengis.net/def/observationType/OGC-OM/2.0/OM_ComplexObservation",
                "multiObservationDataTypes": [
                    row["observationType"],
                    "OM_CategoryObservation",
                    row["observationType"]
                ],

                "unitOfMeasurements": [{
                    "name": row['unit-name'],
                    "symbol": row['unit-symbol'],
                    "definition": row['unit-definition']
                },
                    {
                        "name": "Qualification",
                        "symbol": None,
                        "definition": "link to qualification"
                },
                    {
                        "name": row['unit-name'],
                        "symbol": row['unit-symbol'],
                        "definition": row['unit-definition']
                }
                ],
                "Sensor": {"@iot.id": idSensor},
                "ObservedProperties": [
                    {"@iot.id": idObsp},
                    {"@iot.id": idQF},
                    {"@iot.id": idObsp}

                ],
                "Thing": {"@iot.id": idThing},
                "properties": properties
            })

        return self.post_data_serveur("MultiDatastreams", datastream)

##################################################
