from app.config import Config
from typing import Optional
from pydantic import BaseModel, Field
from time import sleep


class BufferProcess:
    metadata = {
        "id": "buffer",
        "version": 1,
        "title": "Buffer Process",
        "description": "Creates a buffer around the input geometry",
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
            "async-execute"
        ],
        "outputTransmission": [
            "value"
        ]
    }

    class Schema(BaseModel):
        # it is possible to replace ... with a default value
        x:  int = Field(..., title="X coordinate",
                        description="The horizontal coordinate", examples=48)
        y: int = Field(42, title="Y coordinate",
                       description="The vertical coordinate ", examples=-4)
        z: int = Field(None, title="Z coordinate",
                       description="The altitude coordinate ", examples=100)
        name:  str = Field(..., title="username",
                           description="Le user name", examples="alpha", min_length=1)

    class OutputSchema(BaseModel):
        sum: int = Field(..., title="Result", description="Sum of x and y")

    @classmethod
    def run(cls, validated_data: "BufferProcess.Schema"):
        """
        The process below
        """
        # Validate the JSON data with the Pydantic model
        # login_data = LoginSchema(**request.json)
        result = {"resultat": validated_data.x + validated_data.y}
        code = 200
        print("before sleep")
        sleep(10)
        print("finish sleep")
        return result, code

    @classmethod
    def get_metadata(cls):
        return cls.metadata
