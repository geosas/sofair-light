"""Schemas for the /sensors ingestion API"""
from typing import Any, Optional

from apiflask.fields import UploadFile
from pydantic import BaseModel, ConfigDict, Field


class FileUploadIn(BaseModel):
    """Multipart file upload for a connected sensor.

    The endpoint ALSO accepts the file as the raw request body
    This schema only documents the common multipart case. No extension validator here,
    that is per-driver (`ALLOWED_EXTENSIONS`, checked at runtime).
    """
    file: Optional[UploadFile] = Field(
        default=None,
        description="Sensor data file. Its format is defined by the driver "
                    "(e.g. OTT CSV); the extension is checked against the driver's "
                    "ALLOWED_EXTENSIONS.")


class LoRaWANPayloadIn(BaseModel):
    """LoRaWAN uplink pushed by the network server.

    **This schema is the single source of truth for the incoming JSON keys.**
    The three fields carry stable internal names ('deveui' / 'payload' / 'date')
    while the 'alias' is the key the network server actually sends. To support a
    different LoRaWAN network server, change the 'alias=' values here, nothing
    else).

    Extra keys are allowed and forwarded to the decoder.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    deveui: str = Field(alias="deveui", examples=["a84041000181bd6d"])
    payload: str = Field(alias="payload_deciphered",
                         examples=["0167010a027fff"])
    date: str = Field(alias="timestamp", examples=["2026-07-09T10:00:00Z"])


class IngestResult(BaseModel):
    """Successful ingestion: the file was decoded and written to STA."""
    message: str = Field(examples=["file saved successfully"])
    id: Optional[list[int]] = Field(
        default=None,
        description="IDs of the MultiDatastreams written to.",
        examples=[[12, 13]])


class RefreshResult(BaseModel):
    """Result of manually refreshing the in-memory sensor caches."""
    message: str = Field(examples=["managers refreshed"])
    lorawan_deveuis: list[str] = Field(
        default_factory=list, description="DevEUIs known after refresh.")
    lorawan_drivers: Any = Field(
        default=None, description="LoRaWAN driver modules reloaded.")
    veloProcessing_drivers: Any = Field(
        default=None, description="veloProcessing driver modules reloaded.")
