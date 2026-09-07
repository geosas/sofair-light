"""Example process shipped for the standalone/demo mode.

The process contract is intentionally decoupled from any global config: metadata
carries only static, self-descriptive values. A host application injects its own
process classes into ``create_ogc_blueprint`` instead of importing these.
"""
from pydantic import BaseModel, Field
from time import sleep


class BufferProcess:
    metadata = {
        "id": "buffer",
        "version": 1,
        "title": "Buffer Process",
        "description": "Creates a buffer around the input geometry",
        "keywords": ["buffer", "OGC", "processing 1"],
        "links": [{
            "type": "text/html",
            "rel": "about",
            "title": "information",
            "href": "https://example.org/processes/buffer",
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
        # ... means required, no default value
        # 42 means optional, defaults to 42 when omitted
        # None means optional with no default
        x:  int = Field(..., title="X coordinate",
                        description="The horizontal coordinate",
                        examples=48)
        y: int = Field(42, title="Y coordinate",
                        description="The vertical coordinate",
                        examples=-4)
        z: int = Field(None, title="Z coordinate",
                        description="The altitude coordinate",
                        examples=100)
        name:  str = Field(..., title="username",
                        description="The user name",
                        examples="alpha",
                        min_length=1, max_length=256)

    class OutputSchema(BaseModel):
        result: int = Field(..., title="Result", description="Sum of x and y")
        message: str = Field(..., title="Message", description="Confirmation message")

    @classmethod
    def run(cls, validated_data: "BufferProcess.Schema"):
        """
        The process logic below.
        """
        result = {
            "result": validated_data.x + validated_data.y,
            "message": f"Computation completed for {validated_data.name}"
        }
        code = 200
        sleep(1)
        return result, code

    @classmethod
    def get_metadata(cls):
        return cls.metadata

# Register processes in ``flask_ogc_api_processes/ogc_process/registry.py`` (EXAMPLE_PROCESSES),
# not here - this module only defines the BufferProcess example.
