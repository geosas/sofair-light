from pydantic import BaseModel, Field
from werkzeug.utils import secure_filename

from app.config import Config
from app.ogc_process.scripts.exe_get_data_infos import ExeGetDataInfos


class GetDataInfos:
    metadata = {
        "id": "getDataInfos",
        "version": 1,
        "title": "Get info from a MultiDatastream",
        "description": "Get info from a MultiDatastream : min, max, med value and the last value qualified from the associated MultiDatastream who is shared ",
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
        idp: int = Field(..., title="id from MultiDataStream",
                         description="id from MultiDataStream")

    class OutputSchema(BaseModel):
        reponse: dict = Field(..., title="Result",
                              description="A dictionary containing the process response")
        code: int = Field(..., title="code",
                          description="HTML code of the process for the api")

    @classmethod
    def run(cls, validated_data: "GetDataInfos.Schema"):
        """
        The process below
        """
        print('start getDataInfos')
        idp = validated_data.idp
        result, code = ExeGetDataInfos.run(
            Config.STALT_archive,  Config.STALT_partage, idp)

        # output = OutputSchema(**data)
        # print(output.model_dump_json())  #
        return result, code

    @classmethod
    def get_metadata(cls):
        return cls.metadata
