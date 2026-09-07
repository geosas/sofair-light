"""CoverageJSON serialisation for the '/sta' proxy '$resultFormat=covjson'.
turn STA metadata + a time series into a CoverageJSON 'PointSeries' document.
"""


def extract_lonlat(locations):
    """Get [lon, lat] from a list of STA Locations (GeoJSON).
    """
    for loc in locations or []:
        geo = loc.get("location") or {}
        geom = geo.get("geometry", geo)  # accepts a Feature or a raw geometry
        if isinstance(geom, dict) and geom.get("type") == "Point":
            coords = geom.get("coordinates")
            if coords and len(coords) >= 2:
                return [coords[0], coords[1]]
    return [None, None]


def _qc_parameter(qc_table):
    """Build the CovJSON "QC" parameter (quality flags) from Config.STALT_OBSP_QF.

    Each flag becomes a category; 'categoryEncoding' maps the category id to the
    stored integer value. See: 
    https://covjson.gitbooks.io/cookbook/content/parameter-quality-flags.html
    """
    base = qc_table.get("definition") or "quality-flag"
    categories = []
    encoding = {}
    for flag, meta in qc_table.get("properties", {}).items():
        # meta is {description, uri, color, ...}; tolerate a bare string too.
        if isinstance(meta, dict):
            label = meta.get("description", str(flag))
            cat_id = meta.get("uri") or f"{base}/_{flag}"
        else:
            label, cat_id = meta, f"{base}/_{flag}"
        categories.append({"id": cat_id, "label": {"en": label}})
        encoding[cat_id] = int(flag)
    return {
        "type": "Parameter",
        "observedProperty": {
            "id": base,
            "label": {"en": qc_table.get("name", "Quality Flag")},
            "categories": categories,
        },
        "categoryEncoding": encoding,
    }


def _value_parameter(description, unit_symbol, observed_property):
    """CovJSON parameter for a series of numeric values."""
    return {
        "type": "Parameter",
        "description": {"en": description},
        "unit": {"symbol": unit_symbol} if unit_symbol else {},
        "observedProperty": observed_property,
    }


def _ndarray(values, data_type="float"):
    """CovJSON range (NdArray) along the t axis."""
    return {
        "type": "NdArray",
        "dataType": data_type,
        "axisNames": ["t"],
        "shape": [len(values)],
        "values": values,
    }


def build_covjson(param_key, obsprop_def, obsprop_label, unit_symbol,
                  lon, lat, times, values, references=None,
                  qc_values=None, qc_table=None, raw_values=None):
    """Build a CoverageJSON document (domainType PointSeries).

    - 'param_key'     : parameter key = name of the (Multi)Datastream.
    - 'obsprop_def'   : thesaurus link (ObservedProperty definition) -> observedProperty.id
    - 'obsprop_label' : ObservedProperty name -> observedProperty.label.en
    - 'unit_symbol'   : unit symbol (unitOfMeasurement).
    - 'lon'/'lat'     : point coordinates (x/y axes).
    - 'times'         : list of instants (t axis).
    - 'values'        : published/corrected values (None for missing ones).
    - 'references'    : link to the metadata record (custom dct:references field).
    - 'raw_values'    : if provided (archive), adds a "<param_key>_raw" parameter (raw value).
    - 'qc_values'/'qc_table' : if provided (archive), add a "QC" parameter.
    """
    observed_property = {}
    if obsprop_def:
        observed_property["id"] = obsprop_def
    observed_property["label"] = {"en": obsprop_label or param_key}

    parameters = {
        param_key: _value_parameter(param_key, unit_symbol, observed_property),
    }
    ranges = {
        param_key: _ndarray(values),
    }

    # Archive: raw value (in addition to the corrected one) under "<param_key>_raw"
    if raw_values is not None:
        raw_key = f"{param_key}_raw"
        parameters[raw_key] = _value_parameter(
            f"{param_key} (raw data)", unit_symbol, observed_property)
        ranges[raw_key] = _ndarray(raw_values)

    if qc_values is not None and qc_table is not None:
        parameters["QC"] = _qc_parameter(qc_table)
        ranges["QC"] = _ndarray(qc_values, data_type="integer")

    return {
        "type": "Coverage",
        # Custom (prefixed) field: link to the GeoNetwork metadata record
        **({"dct:references": references} if references else {}),
        "domain": {
            "type": "Domain",
            "domainType": "PointSeries",
            "axes": {
                "x": {"values": [lon]},
                "y": {"values": [lat]},
                "t": {"values": times},
            },
            "referencing": [
                {"coordinates": ["x", "y"],
                 "system": {"type": "GeographicCRS",
                            "id": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}},
                {"coordinates": ["t"],
                 "system": {"type": "TemporalRS", "calendar": "Gregorian"}},
            ],
        },
        "parameters": parameters,
        "ranges": ranges,
    }
