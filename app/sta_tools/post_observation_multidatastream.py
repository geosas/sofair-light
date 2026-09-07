from app.config import Config
from app.sta_tools import sta_client
from app.sta_tools.qualification_automatic import AutomaticQualification
from datetime import datetime, timezone


class PostObservationMultiDatastream:
    """
    Post an Observation to STA archive and and
    create a Multidatastream Observation with QF if properties contain QF info
    Format of the Observation = [Raw, QF, Partage]
    """

    url_archive = Config.STALT_archive

    @classmethod
    def run(cls, value, date, properties, idD):
        """
        """
        try:
            # threshold pre-qualification: out of [minValue, maxValue] -> Wrong
            qF = AutomaticQualification.qualify_value(value, properties)
            try:
                phenomenonTime = datetime.fromtimestamp(
                    date, timezone.utc)
            except:
                phenomenonTime = datetime.fromisoformat(date)

            phenomenonTime = phenomenonTime.strftime('%Y-%m-%dT%H:%M:%SZ')

            data = {
                "MultiDatastream": {
                    "@iot.id": idD
                },
                "phenomenonTime": phenomenonTime,
                "resultTime": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                "result": [value, qF, value]
            }
            r = sta_client.post(
                "archive", f"/MultiDatastreams({idD})/Observations", json=data)
            if not r.ok:
                return {"error": "impossible to POST data to STA"}, 500
            else:
                return {"message": "value decoded"}, 200
        except Exception as e:
            print(e)
            return {"error": "error in POST data to TA"}, 500
