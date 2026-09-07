import struct


def get_identifier():

    identifier={"0710":"0710 Soil Humidity",
                "0610":"0610 Soil Temperature",
                "battery":"battery",}

    return identifier

def run(payload, identifier):
    """Driver for sensor SenseCAP S2104

    This driver extracts from the payload the value observed by the sensor SenseCAP,
    (second sensor version) it is a soil temperature and humidity sensor
    
    Args:
        payload (str): payload to decode
        identifier (str) :  Identifier to extract ('battery' or hex tag like '0700').
 
    Returns:
        decoded_value (float): decoded value
    """
   
    if payload[0:8] ==  "00000003":
        return False

    payload_bytes = bytes.fromhex(payload)

    decoded_data = {}

    if len(payload) == 32:
        if payload[2:6] == identifier:
            value_raw = struct.unpack_from('<I', payload_bytes, 3)[0]
            decoded_data[identifier] = value_raw / 1000

        elif payload[16:20] == identifier:
            value_raw = struct.unpack_from('<I', payload_bytes, 10)[0]
            decoded_data[identifier] = value_raw / 1000

        elif identifier == 'battery':
            return False

    elif len(payload) == 46:
        if payload[2:6] == identifier:
            value_raw = struct.unpack_from('<I', payload_bytes, 3)[0]
            decoded_data[identifier] = value_raw / 1000

        elif payload[16:20] == identifier:
            value_raw = struct.unpack_from('<I', payload_bytes, 10)[0]
            decoded_data[identifier] = value_raw / 1000

        elif identifier == 'battery' and payload[30:34] == "0700":
            
            battery_raw = struct.unpack_from('<H',payload_bytes,17)[0]
            decoded_data['battery'] = battery_raw

    return decoded_data.get(identifier, False)


# Example payload for the UI decoding test (prefills the payload field).
EXAMPLE_PAYLOAD = "0106102c1a0000010710449300009ea0"
