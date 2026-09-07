from pydantic import BaseModel, Field
from werkzeug.utils import secure_filename

from app.config import Config
from app.ogc_process.scripts.exe_config_create_datastream import ExeConfigCreateDatastream


class ConfigCreateDatastream:
    metadata = {
        "id": "configCreateDatastream",
        "version": 1,
        "title": "Config Create Datastream",
        "description": "Create the Datasreams, based on ObsP+Sensor+Thing and append the sheet to xlsx file of the config",
        "keywords": ["buffer", "OGC"],
        "links": [{
            "type": "text/html",
            "rel": "about",
            "title": "information",
            "href": Config.URL_PROJET,
            "hreflang": "en-US"
        }],
        "jobControlOptions": [
            "sync-execute",
        ],
        "outputTransmission": [
            "value"
        ]
    }

    class Schema(BaseModel):
        # it is possible to replace ... with a default value
        configFile: str = Field(..., title="Config file", min_length=1,
                                description="Config file encoded in base64")

    class OutputSchema(BaseModel):
        reponse: dict = Field(..., title="Result", description="A dictionary containing the process response")
        code: int = Field(..., title="code", description="HTML code of the process for the api")

    @classmethod
    def run(cls, validated_data: "ConfigCreateDatastream.Schema"):
        """
        The process below
        """
        name_secure = secure_filename(Config.APP_METADATA['name'])
        conf = Config.STALT_CONFIG
        result, code = ExeConfigCreateDatastream.run(
            validated_data.configFile, name_secure, conf)

        #output = OutputSchema(**data)
        #print(output.model_dump_json())  
        return result, code

    @classmethod
    def get_metadata(cls):
        return cls.metadata
