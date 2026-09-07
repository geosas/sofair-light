import struct

def get_identifier():

    identifier={"V_bat":"V_bat batterie",
                "rain_rate":"rain_rate",
                "pulses":"pulses Basculment auget"}

    return identifier


def run(payload, identifier):
    """Driver for sensor CONCEPT60 

    This driver extracts from the payload the value observed by the sensor CONCEPT60 6466M,
    Rain gauge, measures the number of tips (cumulative) since sensor initialization


    Args:
        payload (str) : Hexadecimal string representing the payload (12 bytes).
        identifier (str): if the payload has several values to extract, identifies the Datastream value
 
    Returns:
        decoded_value (float): decoded value
    """
    payload_bytes = bytes.fromhex(payload)

    # Unpack the payload 
    v_bat, rain_rate, pulses, temperature, humidity = struct.unpack(
        '>HHIHH', payload_bytes
    )
    #  > : Big-endian (most significant byte first)     the doc does not specify it.... you must test both
    #  < : Little-endian (least significant byte first)
    #same for:
    #H : Unsigned Short (unsigned integer, 2 bytes)   and
    #   h : Short (signed integer, 2 bytes) A 2-byte signed integer, with a value range from -32768 to 32767. 

    decoded_data = {
        'V_bat': v_bat/1000, 
        'rain_rate': rain_rate if rain_rate != 0x7FFF else None, 
        'pulses': pulses,  
        #'temperature': self.handle_absence(temperature, 10.0,"temperature"), 
        #'humidity': self.handle_absence(humidity, 10.0),  
    }
    return decoded_data[identifier]


# Example payload for the UI decoding test (prefills the payload field).
EXAMPLE_PAYLOAD = "0e0a000000000002ffffffff"
