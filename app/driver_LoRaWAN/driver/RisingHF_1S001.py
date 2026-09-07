import struct

def get_identifier():

    identifier={"Temperature":"Temperature",
                "Humidity":"Humidity",
                "Battery":"Battery"}

    return identifier


def run(payload, identifier):
    """Driver for sensor RisingHF - RHF1S001

    This driver extracts from the payload the value observed by the sensor RisingHF - RHF1S001,
    it is an air temperature and humidity sensor

    Args:
        payload (str): payload to decode
        identifier (str): if the payload has several values to extract, identifies the Datastream value
 
    Returns:
        decoded_value (float): decoded value
    """
    payload_bytes = bytes.fromhex(payload)

    temp_raw, = struct.unpack_from('<H', payload_bytes, 1)  
    humidity_raw = payload_bytes[3]                          
    battery_raw = payload_bytes[-1]                          

    decoded_data = {
        'Temperature': ((175.72 * temp_raw) / 65536) - 46.85,
        'Humidity': (125 * humidity_raw / 256) - 6,
        'Battery': (battery_raw + 150) * 0.01
    }

    return decoded_data[identifier]


# Example payload for the UI decoding test (prefills the payload field).
EXAMPLE_PAYLOAD = "81ce47d9c20148189c"
