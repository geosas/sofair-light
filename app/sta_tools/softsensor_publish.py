"""Publish a SoftSensor (derived) datastream from a qualified source.

Called by the qualification hook: when a source datastream carrying a
'softSensorProducer' property is qualified, the derived series is (re)computed
over the qualified range from the CORRECTED source values and published to the
target datastream.

- QF: inherited from the source (an invalid source point -> invalid derived point).
- Archive (target): delete the affected range, then COPY the valid computed
  points (RESULT_JSON = [value, QF, value]).
- Partage (target): 'apply_partage_qualification' on ALL rows (valid -> publish,
  invalid QF (bad / missing) -> null marker / delete), reusing the existing bulk logic.

Don't raise error on failure, so a SoftSensor problem never breaks the
 source qualification that triggered it.
"""
import pandas as pd

from app.sta_tools import sta_client
from app.sta_tools.observations_partage import apply_partage_qualification
from app.sta_tools.qualify_observations import worst_qf, qf_code
from app.sta_tools.archive_observations import write_archive_observations
from app.driver_softSensor.manager import ScriptManagerSoftSensor

PRODUCER_KEY = 'softSensorProducer'
_INVALID_QF = tuple(c for c in (qf_code('delete'),
                    qf_code('gap')) if c is not None)


def _archive_replace_range(target_id, foi, derived, tmin, tmax, DB_archive):
    """Build the derived observations (RESULT_JSON = [value, QF, value]) and
    replace the [tmin, tmax] range on the target archive MultiDatastream."""
    if len(derived) == 0:
        # Nothing to insert, but still clear the range (invalid source points).
        write_archive_observations(pd.DataFrame(columns=["PHENOMENON_TIME_START"]),
                                   target_id, DB_archive, delete_range=(tmin, tmax))
        return
    ins = pd.DataFrame({
        "PHENOMENON_TIME_START": derived["phenomenonTime"],
        "RESULT_JSON": [[float(v), int(q), float(v)]
                        for v, q in zip(derived["value"], derived["QF"])],
        "RESULT_TIME": derived["phenomenonTime"],
        "FEATURE_ID": foi,
        "RESULT_TYPE": 2,
        "PHENOMENON_TIME_END": derived["phenomenonTime"],
        "MULTI_DATASTREAM_ID": int(target_id),
    })
    write_archive_observations(
        ins, target_id, DB_archive, delete_range=(tmin, tmax))


def apply_softsensor(producer, source_thing, rows, DB_archive, DB_partage):
    """Compute + publish the derived datastream declared by `producer`.

    Args:
        producer: the source's `softSensorProducer` = {method, target, params}.
        source_thing: the source datastream's Thing (dict, for `elevation`).
        rows: qualified source rows [{phenomenonTime, QF, result_share, ...}].
    Returns:
        summary dict, or {"error": ...}. (Never raises.)
    """
    if not producer or not rows:
        return None
    try:
        method = producer['method']
        target_name = producer['target']
        params = dict(producer.get('params') or {})

        # elevation from the source's Thing, when the method requires it
        meta = next((m for m in ScriptManagerSoftSensor.get_metadata()
                     if m['id'] == method), {})
        if meta.get('elevationFromThing'):
            elev = ((source_thing or {}).get(
                'properties') or {}).get('elevation')
            if elev is None:
                return {"error": "elevation missing on the source Thing"}
            params['elevation'] = float(elev)

        # source rows -> DataFrame (value = corrected/qualified share, + QF)
        df = pd.DataFrame([{"phenomenonTime": r['phenomenonTime'],
                            "QF": int(r['QF']),
                            "value": r.get('result_share')} for r in rows])
        df["phenomenonTime"] = pd.to_datetime(df["phenomenonTime"], utc=True)
        valid = df[(~df["QF"].isin(_INVALID_QF)) & df["value"].notna()].copy()

        # compute derived values on the valid source points, inherit their QF
        if len(valid):
            derived = ScriptManagerSoftSensor.run_script(
                method, valid[["phenomenonTime", "value"]].copy(), params)
            derived["phenomenonTime"] = pd.to_datetime(
                derived["phenomenonTime"], utc=True)
            derived = derived.merge(valid[["phenomenonTime", "QF"]],
                                    on="phenomenonTime", how="left")
            # A method may assert its own QF (e.g. rating curve out of range ->
            # doubtful): combine it with the inherited QF, worst wins.
            if "qf" in derived.columns:
                derived["QF"] = [worst_qf(s, m)
                                 for s, m in zip(derived["QF"], derived["qf"])]
                derived = derived.drop(columns=["qf"])
        else:
            derived = pd.DataFrame(columns=["phenomenonTime", "value", "QF"])

        # resolve target (archive id + foi + partage counterpart)
        rt = sta_client.proxy_get("archive", "MultiDatastreams",
                                  params={"$select": "name,id,properties",
                                          "$filter": f"name eq '{target_name}'"})
        tv = rt.json().get('value', [])
        if not tv:
            return {"error": f"target datastream '{target_name}' not found"}
        target = tv[0]
        target_props = target.get('properties') or {}

        tmin = df["phenomenonTime"].min().to_pydatetime()
        tmax = df["phenomenonTime"].max().to_pydatetime()

        # archive: replace the range with the computed valid points
        _archive_replace_range(target['@iot.id'], target_props.get('foiId'),
                               derived, tmin, tmax, DB_archive)

        summary = {"target": target_name, "archive_points": int(len(derived))}

        # partage: bulk apply ALL rows (invalid -> marker/delete, valid -> publish)
        name_share = target_props.get('nameShare')
        if name_share:
            rp = sta_client.proxy_get("partage", "Datastreams",
                                      params={"$select": "name,id,properties",
                                              "$filter": f"name eq '{name_share}'"})
            pv = rp.json().get('value', [])
            if pv:
                ds_p = pv[0]
                foi_p = (ds_p.get('properties') or {}).get('foiId')
                # Rename derived columns (both frames have `value`) before merging.
                d = derived.rename(columns={"QF": "QF_d", "value": "value_d"})
                merged = df.merge(d[["phenomenonTime", "value_d", "QF_d"]],
                                  on="phenomenonTime", how="left")
                # Valid points -> derived value + derived (combined) QF ; invalid
                # source points (absent from `derived`) -> source QF + null.
                part_rows = [{"phenomenonTime": t.strftime('%Y-%m-%dT%H:%M:%SZ'),
                              "QF": int(qd) if pd.notna(qd) else int(qs),
                              "result_share": (None if pd.isna(v) else float(v))}
                             for t, qs, qd, v in zip(merged["phenomenonTime"],
                                                     merged["QF"], merged["QF_d"],
                                                     merged["value_d"])]
                summary["partage"] = apply_partage_qualification(
                    part_rows, ds_p['@iot.id'], foi_p, DB_partage)
        return summary
    except Exception as e:
        return {"error": str(e)}
