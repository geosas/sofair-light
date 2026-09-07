"""Generic HTTPS ingestion for connected NON-LoRaWAN sensors and LoRaWAN.

These sensors speak HTTPS but not the SensorThings protocol: they push a raw
file to  POST /sensors/<driver>/<param>

- <driver>: driver name, resolved dynamically in
    app/driver_veloProcessing/driver/<driver>.py. Each driver carries ITS OWN
    authentication (`authenticate` function) and its list of allowed extensions
    (`ALLOWED_EXTENSIONS`). Credentials live in app/config_sensor.py.
- <param>: measurement-point name (the Thing name), the same name used on
    /private/import-data. It is matched as a substring of the target
    MultiDatastreams' name.

Security is NOT the application's cookie JWT (a sensor cannot provide it): it is
delegated to the driver. A driver without `authenticate` is refused (fail-safe).

STA prerequisite: reuses the `DataDriverPostToSTA` pipeline, whose STA lookup
selects MultiDatastreams whose `observationProcedure` is 'httpsConnected'
(connected sensors) OR 'veloProcessing' (bike-collected CSV), with Sensor/name
containing <driver> and name containing <param>. Tag connected datastreams
`httpsConnected` at config time (config xlsx dropdown = STALT_CONFIG.AquisitionMethode).
"""
import base64

from apiflask import APIBlueprint
from flask import request, jsonify, make_response

from app.config import Config
from app.driver_veloProcessing.manager import ScriptManagerVeloProcessing
from app.driver_LoRaWAN.manager import ScriptManagerLoRaWAN
from app.ogc_process.data_driver_post_to_sta import DataDriverPostToSTA
from app.sta_tools.lorawan_to_sta import DecodePayload
from app.services.security import verify_jwt_api
from app.schemas.sensors import (
    FileUploadIn, LoRaWANPayloadIn, IngestResult, RefreshResult)

sensors_bp = APIBlueprint("sensors", __name__, tag="Sensors")


def _extension_ok(filename, allowed):
    """True if `filename`'s extension is in `allowed` (or if there is no list)."""
    if not allowed:
        return True
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in {e.lower().lstrip(".") for e in allowed}


@sensors_bp.post("/refresh")
@sensors_bp.output(RefreshResult)
@sensors_bp.doc(summary="Refresh sensor caches",
                description="Invalidate the in-memory caches: LoRaWAN datastream "
                            "snapshot (automatic-qualification bounds) + hot-reload "
                            "of the LoRaWAN and veloProcessing driver modules. "
                            "Requires a JWT (cookie or `Authorization: Bearer`).")
def refresh_managers():
    auth = verify_jwt_api()  # None -> continue ; (json, 401)
    if auth is not None:
        return make_response(auth)

    # LoRaWAN datastream properties (drive the automatic-qualification bounds).
    info, code = DecodePayload.refresh()
    if code == 500:
        return make_response(jsonify(
            {"error": "unable to refresh LoRaWAN datastreams from STA",
             "detail": info}), 502)

    return {
        "message": "managers refreshed",
        "lorawan_deveuis": sorted(info.keys()),
        "lorawan_drivers": ScriptManagerLoRaWAN.refresh(),
        "veloProcessing_drivers": ScriptManagerVeloProcessing.refresh(),
    }


@sensors_bp.get("/info-lorawan/")
@sensors_bp.doc(summary="LoRaWAN decoders metadata",
                description="Metadata of the available LoRaWAN decoders "
                            "(identifiers + example payloads).")
def info_lorawan():
    """Metadata of the available LoRaWAN decoders."""
    info, code = DecodePayload.get_metadata()
    return jsonify(info), code


@sensors_bp.post("/post-lorawan/")
@sensors_bp.input(LoRaWANPayloadIn)
@sensors_bp.doc(summary="Ingest a LoRaWAN uplink",
                description="Decode a LoRaWAN payload and post the observations to "
                            "STA. Devices cannot provide a JWT: access is gated by "
                            "the shared header `LoRaWAN-Request: <secret>` (not the "
                            "app JWT). Body = the network-server JSON uplink; the "
                            "keys are defined by the `LoRaWANPayloadIn` schema "
                            "(default: `deveui`, `payload_deciphered`, `timestamp`) "
                            "- extra keys are forwarded to the decoder.")
def post_lorawan(json_data):
    """Ingest a LoRaWAN payload (devices cannot provide a JWT: access is
    'protected' by the shared header 'LoRaWAN-Request').
    """
    if request.headers.get('LoRaWAN-Request') != Config.STALT_LORAWAN_SECRET:
        return jsonify({"error": "not authorized"}), 401

    # model_dump() -> canonical keys (deveui/payload/date) + extra=allow keys;
    # the network server's own key names were mapped by the schema aliases.
    data = json_data.model_dump()

    try:
        info, code_response = DecodePayload.decode_and_post(data)
    except Exception as e:
        print(e)
        info, code_response = {"error": "decoding error"}, 500
    return jsonify(info), code_response


@sensors_bp.post("/<driver>/<param>")
@sensors_bp.input(FileUploadIn, location="files", arg_name="files_data")
@sensors_bp.output(IngestResult)
@sensors_bp.doc(summary="Ingest a connected-sensor file",
                description="Generic HTTPS ingestion for non-LoRaWAN sensors. "
                            "`driver` = a module in driver_veloProcessing/driver/ "
                            "(e.g. `OTT`); `param` = the measurement-point name "
                            "(matched as a substring of the target MultiDatastreams' "
                            "name). The driver owns its authentication (e.g. OTT = "
                            "HTTP Basic) and its allowed extensions. The file may be "
                            "sent multipart OR as the raw request body. Error bodies "
                            "keep the historical `{\"error\": ...}` shape.")
def ingest(driver, param, files_data):
    # `files_data` is injected by @input for the OpenAPI doc.

    # 1. Dynamic driver resolution (hot-reload).
    # maybe change it for a more 'getCapabilities' function
    # who stores informations in the app
    try:
        module = ScriptManagerVeloProcessing.load(driver)
    except ValueError:
        return make_response(jsonify({"error": f"Unknown driver '{driver}'"}), 404)

    # 2. Driver-OWNED security (fail-safe: refused if not defined).
    authenticate = getattr(module, "authenticate", None)
    if not callable(authenticate):
        return make_response(jsonify(
            {"error": f"Driver '{driver}' does not define authentication"}), 403)
    rejected = authenticate(request, param)
    if rejected is not None:
        # Driver returns a Flask response tuple (body, code, headers); wrap it so
        # it passes through @output untouched (401 + WWW-Authenticate preserved).
        return make_response(rejected)

    # 3. File retrieval (multipart, otherwise the raw request body).
    if request.files:
        file = next(iter(request.files.values()))
        filename = file.filename or param
        raw = file.read()
    else:
        raw = request.get_data()
        filename = param

    if not raw:
        return make_response(jsonify({"error": "No data received"}), 400)

    # 4. Driver-owned extension validation (only when a filename is provided;
    #    a sensor pushing a raw body has none).
    allowed = getattr(module, "ALLOWED_EXTENSIONS", None)
    if request.files and not _extension_ok(filename, allowed):
        return make_response(jsonify(
            {"error": f"Extension not allowed (expected: {sorted(allowed)})"}), 415)

    # 5. Decode + send to STA through the existing pipeline.
    # maybe change it, heritance from OGC PROCESS API who read JSON only at first
    rawFile64 = base64.b64encode(raw).decode("ascii")
    try:
        validated = DataDriverPostToSTA.Schema(
            rawFile64=rawFile64, driver=driver, name=param)
        result, code = DataDriverPostToSTA.run(validated)
    except Exception as e:
        return make_response(jsonify(
            {"error": "Error during processing", "exception": str(e)}), 500)
    # Business errors from the pipeline keep their body + code; success (200)
    # is serialised by IngestResult.
    if code != 200:
        return make_response(jsonify(result), code)
    return result
