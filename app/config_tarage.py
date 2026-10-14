"""Configuration of the gauging tools (/tarage): salt-dilution discharge,
gauging list and rating curve.

They write to the archive STA (MultiDatastreams [property, QF, property]).
The rainfall station of a gauging site is NOT configured here: it is chosen on
the /tarage/list page and stored in the site Thing (properties.precipitation_ref).
"""

# Date formats of the imported conductivity CSV and of the measurement ranges
CSV_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"    # e.g. 2025-01-27 14:02:00
RANGE_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"  # e.g. 2025-01-27T14:02:00

# STA names the tools look up (must exist on the STA, except the discharge
# Sensor which is created on first publication)
CONDUCTIVITY_NAME = "Surface water conductivity"  # ObservedProperty
CONDUCTIMETER_NAME = "Conductimeter"               # Sensor
STREAMFLOW_NAME = "Streamflow"                     # ObservedProperty
HEIGHT_NAME = "Stream stage"                       # ObservedProperty (water level)

CONDUCTIVITY_UNIT = {
    "name": "MicroSiemens per centimeter",
    "symbol": "µS/cm",
    "definition": "https://data.geoscience.fr/ncl/uom/_69",
}
STREAMFLOW_UNIT = {
    "name": "litre per second",
    "symbol": "L/s",
    "definition": "https://qudt.org/vocab/unit/L-PER-SEC",
}

# Sensor of the tracing discharges (created on first publication)
DISCHARGE_SENSOR = {
    "name": "Mass conservation discharge",
    "description": "Discharge computed by mass conservation (salt dilution gauging)",
    "encodingType": "application/pdf",
    "metadata": "https://www.uvm.edu/~bwrl/lab_docs/protocols/2005_Hudson_and_Fraser_Simple_slug_salt_dilution_gauging_method_Streamline.pdf",
}
