from flask import url_for
import json
from typing import Optional
from pydantic import BaseModel, Field
import os
from werkzeug.utils import secure_filename

from app.config import Config
from app.ogc_process.scripts.exe_config_post_to_sta import instanceST
from app.ogc_process.scripts.exe_config_archive_to_partage import ExeConfigPostDatastream
from app.ogc_process.scripts.exe_config_create_datastream import ExeConfigCreateDatastream


class ConfigPostToSTA:
    metadata = {
        "id": "configPostToSTA",
        "version": 1,
        "title": "Config Post to STA",
        "description": "Convert (and POST) the xlsx config to STA, populate the archive and partage",
        "keywords": ["config", "STA", "OGC"],
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
        configFile: str = Field(..., title="Config file", min_length=1,
                                description="Config file with the datastreams encoded in base64")

    class OutputSchema(BaseModel):
        reponse: dict = Field(..., title="Result",
                              description="A dictionary containing the process response")
        code: int = Field(..., title="code",
                          description="HTML code of the process for the api")

    @classmethod
    def run(cls, validated_data: "ConfigPostToSTA.Schema"):
        """
        The process below
        """
        url_partage = Config.STALT_partage
        url_archive = Config.STALT_archive
        code_qualification = Config.STALT_OBSP_QF

        print("start process ConfigPostToSTA")
        name_secure = secure_filename(Config.APP_METADATA['name'])
        output_file_path = f"app/static/xlsx/{name_secure}_config_service.xlsx"
        try:
            ExeConfigCreateDatastream.decode_base64_to_excel(
                validated_data.configFile, output_file_path)
        except Exception as e:
            return {"error": str(e)}, 500

        try:
            sessionST = instanceST(url_archive, "", "")
            sessionST.token = ''
            sessionST.addTableConfig(output_file_path)
            if len(sessionST.dataStreamSrc['name']) == 0:
                return {"error": "4_datastream sheet empty"}, 500

            creation_Sensor = sessionST.creationSensor()
            if creation_Sensor != True:
                print(creation_Sensor)
                return creation_Sensor, 500

            # create the Observed Properties with duplicate checking, independent function
            creation_ObservedProperties = sessionST.creationObservedProperties(
                code_qualification)
            if creation_ObservedProperties != True:
                print(creation_ObservedProperties)
                return creation_ObservedProperties, 500

            # create the things + associated locations with duplicate checking (for things), independent function
            creation_Things = sessionST.creationThings()
            if creation_Things != True:
                print(creation_Things)
                return creation_Things, 500

            # create one FeatureOfInterest per Thing (same name): required
            # BEFORE the MultiDatastreams (which store the FOI id in properties)
            creation_FOI = sessionST.creationFeaturesOfInterest()
            if creation_FOI != True:
                print(creation_FOI)
                return creation_FOI, 500

            # create the MultiDatastreams, the Sensor + ObsP + Things must already exist
            creation_MultiDataStreams = sessionST.creationMultiDataStreams(
                code_qualification)
            if creation_MultiDataStreams != True:
                print(creation_MultiDataStreams)
                return creation_MultiDataStreams, 500

            ###
            print("##########  post config to partage ############")

            output_process = ExeConfigPostDatastream.run(
                url_partage, url_archive)
            if output_process is True:

                # if it's the first time, write an article
                #    generate_article(titre, resume, corps,  'observatoire' +
                #     extension, 'observatoire_resize' + extension)

                # signal to the service that the config is created
                Config.APP_CONFIG_STA = {"config": True}
                with open(os.path.join(Config.BASEDIR, 'data', 'configSTA', 'config_STA.json'), "w",
                          encoding="utf-8") as outfile:
                    outfile.write(json.dumps(Config.APP_CONFIG_STA, indent=4))

                return {"sta_partage": url_partage,
                        "sta_archive": url_archive}, 200
            else:
                return output_process, 500
        except Exception as e:
            return {"error": str(e)}, 500

    @classmethod
    def get_metadata(cls):
        return cls.metadata
