from app.config import Config
from app.sta_tools import sta_client
from app.driver_LoRaWAN.manager import ScriptManagerLoRaWAN
from app.sta_tools.post_observation_multidatastream import PostObservationMultiDatastream


class DecodePayload:
    active_lorawan = {}

    @classmethod
    def get_metadata(cls):
        """
        get infos for the Multidatastreams who use LoRaWAN.
        """
        print('get metadata lorawan')
        cls.active_lorawan = {}
        parametre = {"$select": "name,properties,id",
                     "$filter": "properties/observationProcedure eq 'LoRaWAN'",
                     }
        try:
            r = sta_client.get(
                "archive", "/MultiDatastreams", params=parametre)

        except:
            return {"error": "SensorThings service not active or unreachable"}, 500
        if not r.ok:
            return {"error": "SensorThings service not active or unreachable"}, 500

        for i in r.json()['value']:
            if "LoRaWAN" in i['properties']:
                deveui = i['properties']["LoRaWAN"]['DevEUI']
                if deveui not in cls.active_lorawan:
                    cls.active_lorawan[deveui] = [i]
                else:
                    cls.active_lorawan[deveui] += [i]
        return cls.active_lorawan, 200

    @classmethod
    def refresh(cls):
        """Force-rebuild the multidatastream snapshot from STA.

        'get_metadata' resets 'active_lorawan' and re-reads every LoRaWAN
        datastream's 'properties' (incl. minValue/maxValue used by the automatic
        qualification). Call after changing a multidatastream config in STA so the new
        bounds / driver / identifier apply without an app restart.
        """
        return cls.get_metadata()

    @classmethod
    def decode_and_post(cls, payload):
        """ Decode a payload and POST to STA archive
        'payload' uses the keys produced by LoRaWANPayloadIn
        (deveui / payload / date), the mapping from the network server's own key
        names lives in that schema's field aliases, not here.
        """

        deveui = payload["deveui"].lower()

        # 'active_lorawan' caches each datastream's 'properties' (incl.
        # minValue/maxValue used by the automatic qualification).
        # Payloads can arrive at high frequency, so we do nit re-fetch STA per payload.
        # This is why we need a refesh method.
        if cls.active_lorawan == {}:
            info, code = cls.get_metadata()
            if code == 500:
                return info, code
        if deveui not in cls.active_lorawan:
            return {"error": f"The DevEUI {deveui} doesn't exist"}, 404
        else:
            active_sensor = cls.active_lorawan[deveui]
            payload_value = payload["payload"]
            date = payload["date"]
            for datastream in active_sensor:
                datastreamP = datastream['properties']
                value_decoded = ScriptManagerLoRaWAN.run_script(
                    datastreamP['LoRaWAN']['driver'], payload_value,
                    datastreamP['LoRaWAN']['identifier'])
                if value_decoded == False:
                    continue
                info, code = PostObservationMultiDatastream.run(
                    value_decoded, date, datastreamP, datastream['@iot.id'])
                if code == 500:
                    return info, code
            return info, code
