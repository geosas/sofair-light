"""Automatic (threshold-based) pre-qualification of incoming observations.

Flags observations whose value falls outside the Datastream's declared
[minValue, maxValue] bounds as bad data.

The QF codes are derived from the single-source vocabulary
Config.STALT_OBSP_QF: out-of-range = the 'delete' (bad) flag, in-range =
'raw_default'. 
Change the vocabulary file in /data/qualification/qf_flags.json, not these constants.

Two entry points share the exact same rule:
- qualify_value     : a single observation (LoRaWAN ingestion).
- qualify_dataframe : a pandas column (driver / import-template ingestion).

"""
from app.config import Config
import pandas as pd


def _qf_role(action):
    """QF code whose vocabulary entry declares this UI action, or None."""
    for code, meta in (Config.STALT_OBSP_QF.get('properties') or {}).items():
        if isinstance(meta, dict) and meta.get('action') == action:
            return int(code)
    return None


class AutomaticQualification:
    """Threshold pre-qualification shared by the ingestion paths.

    Codes come from the QF vocabulary"""

    _RAW = Config.STALT_OBSP_QF.get('raw_default', 0)
    _BAD = _qf_role('delete')

    # value outside [minValue, maxValue]
    WRONG = _BAD if _BAD is not None else _RAW  # ceinture and bretelle

    IN_RANGE = _RAW
    UNCHECKED = _RAW   # no usable bound -> left as raw (to qualify)

    @staticmethod
    def _bound(properties, key):
        """Return a numeric bound, or None if absent / empty / non-numeric."""
        value = (properties or {}).get(key)
        if value is None or value == '':
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def qualify_value(cls, value, properties):
        """QF code for a single observation given its Datastream properties."""
        low = cls._bound(properties, 'minValue')
        high = cls._bound(properties, 'maxValue')
        if low is None and high is None:
            return cls.UNCHECKED
        try:
            v = float(value)
        except (TypeError, ValueError):
            return cls.UNCHECKED
        if (low is not None and v < low) or (high is not None and v > high):
            return cls.WRONG
        return cls.IN_RANGE

    @classmethod
    def qualify_dataframe(cls, df, properties, result_col='result',
                          qf_col='qualification'):
        """Set df[qf_col] from df[result_col]  with the configured bounds.

        Out-of-range rows -> WRONG, in-range rows -> IN_RANGE. Rows with a
        non-numeric result, or when no bound is configured, keep whatever the
        caller initialised the column to (UNCHECKED).
        """

        low = cls._bound(properties, 'minValue')
        high = cls._bound(properties, 'maxValue')
        if low is None and high is None:
            return df

        vals = pd.to_numeric(df[result_col], errors='coerce')
        out_of_range = pd.Series(False, index=df.index)
        in_range = pd.Series(True, index=df.index)
        if low is not None:
            out_of_range |= vals < low
            in_range &= vals >= low
        if high is not None:
            out_of_range |= vals > high
            in_range &= vals <= high
        # ignore rows whose result is not a number
        out_of_range &= vals.notna()
        in_range &= vals.notna()

        df.loc[out_of_range, qf_col] = cls.WRONG
        df.loc[in_range, qf_col] = cls.IN_RANGE
        return df
