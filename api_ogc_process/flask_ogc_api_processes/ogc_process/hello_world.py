"""A second example process, to show how to add your own.

Copy this file, rename the class and its ``metadata["id"]``, adjust ``Schema`` /
``OutputSchema`` / ``run`` - then register the class in ``EXAMPLE_PROCESSES``
(see ``Example_OGC_Process.py``). Nothing else to wire up.
"""
from pydantic import BaseModel, Field


class HelloWorldProcess:
    metadata = {
        "id": "hello-world",                     # unique id, used in the URL
        "version": 1,
        "title": "Hello World",
        "description": "Returns a greeting for the given name.",
        "keywords": ["hello", "demo", "OGC"],
        "jobControlOptions": ["sync-execute", "async-execute"],
        "outputTransmission": ["value"],
    }

    class Schema(BaseModel):
        name: str = Field(..., title="Name", description="Who to greet",
                          examples="JC", min_length=1, max_length=256)
        shout: bool = Field(False, title="Shout",
                            description="Upper-case the greeting")

    class OutputSchema(BaseModel):
        greeting: str = Field(..., title="Greeting", description="The greeting message")

    @classmethod
    def run(cls, validated_data: "HelloWorldProcess.Schema"):
        greeting = f"Hello, {validated_data.name}!"
        if validated_data.shout:
            greeting = greeting.upper()
        return {"greeting": greeting}, 200

    @classmethod
    def get_metadata(cls):
        return cls.metadata
