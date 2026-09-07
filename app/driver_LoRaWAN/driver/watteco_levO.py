import struct


def get_identifier():

    identifier = {"hauteur": "hauteur eau",
                  }

    return identifier


def run(payload, identifier):
    """Driver for sensor watteco Lev'O

    This driver extracts from the payload the value observed by the sensor watteco Lev'O,
    it is a water-level sensor


    Args:
        payload (str): payload to decode
        identifier (str): if the payload has several values to extract, identifies the Datastream value

    Returns:
        decoded_value (float): decoded value
    """
    hex_string = payload[-8:]
    # Convert the hex string to bytes
    hex_bytes = bytes.fromhex(hex_string)
    # Interpret the bytes as a big-endian float
    decoded_value = struct.unpack('>f', hex_bytes)[0]

    return decoded_value


# Example payload for the UI decoding test (prefills the payload field).
EXAMPLE_PAYLOAD = "110a000c00553940802799"
