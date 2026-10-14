"""Gauging list (/tarage/list): history of the salt-dilution gaugings of a site.

For a site (Thing with conductivity MultiDatastreams): the reference water-level
station, the discharge time series, the stage-discharge relation (+ fitted
rating curve) and, per gauging, its conductivity plot, discharges,
qualification, uncertainty, water level and the rainfall of the day.

Stored on the archive STA (see common.py):
- Thing.properties.height_ref = {"Thing": {"@iot.id"}, "MultiDatastream": {"@iot.id"}}
  or {"unavailable": true};
- Thing.properties.precipitation_ref = {"url": "<Datastream URL of a public STA>"}
  (rainfall station of the site, chosen on the page: it depends on the area);
- conductivity MultiDatastream properties: "<Streamflow>" {value, units,
  qualityFlag: [bool, ...]}, "tracer" {name, weights, units}, "height" {value, units}.
"""
import csv
import hashlib
import io
from datetime import date
import math
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from flask import Response, jsonify, render_template, request  # noqa: E402
from flask_babel import gettext as _  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from app import config_tarage as cfg  # noqa: E402
from app.routes.tarage import tarage_bp  # noqa: E402
from app.routes.tarage.common import (PLOTS_SUBDIR, SERVER, fetch_observations,  # noqa: E402
                                      find_id, get_all, main_property, parse_pt,
                                      plot_name, plots_dir, things_with_property)
from app.routes.private.softsensor import set_producer  # noqa: E402
from app.services.security import jwt_required_or_redirect  # noqa: E402
from app.sta_tools import sta_client  # noqa: E402

GOOD, UNQUALIFIED, REJECTED = '#48c774', '#aaaaaa', '#f14668'


# ── Utilities ────────────────────────────────────────────────────────────────

def _format_pt(pt):
    if not pt or pt == '/':
        return ''
    try:
        if '/' in pt:
            start_str, end_str = pt.split('/', 1)
            start = pd.to_datetime(start_str).strftime('%d/%m/%Y %H:%M')
            end = pd.to_datetime(end_str).strftime('%d/%m/%Y %H:%M')
            return f'{start} → {end}'
        return pd.to_datetime(pt).strftime('%d/%m/%Y %H:%M')
    except Exception:
        return pt


def _compute_uncertainty(debits):
    """GUM §4.3.7 uncertainty: {'abs' (L/s), 'rel_pct' (%)}, None if < 2 values."""
    if not debits or len(debits) < 2:
        return None
    arr = [float(d) for d in debits]
    mean = sum(arr) / len(arr)
    if mean == 0:
        return None
    if len(arr) < 6:
        u_abs = (max(arr) - min(arr)) / (2 * math.sqrt(3))   # uniform distribution
    else:
        u_abs = math.sqrt(sum((x - mean) ** 2 for x in arr) / len(arr))
    return {'abs': round(u_abs, 3), 'rel_pct': round(u_abs / mean * 100, 2)}


def _uncertainty_color(uncertainty_pct):
    """(hex colour, rgba band colour) for an uncertainty threshold."""
    if uncertainty_pct < 5:
        return '#48c774', 'rgba(72,199,116,0.18)'    # green
    if uncertainty_pct <= 10:
        return '#ffb70f', 'rgba(255,183,15,0.22)'    # orange
    return '#f14668', 'rgba(241,70,104,0.18)'        # red


def _good_debits(ds):
    """Discharges qualified as good, or None when the gauging is not qualified."""
    debits, flags = ds.get('debits') or [], ds.get('quality_flags')
    if not debits or not flags or len(flags) != len(debits):
        return None
    return [d for d, f in zip(debits, flags) if f is True]


def _status(ds):
    """'good' | 'unqualified' | 'rejected' and the matching mean discharge."""
    debits = ds['debits']
    good = _good_debits(ds)
    if good is None:
        return 'unqualified', round(sum(debits) / len(debits), 2)
    if good:
        return 'good', round(sum(good) / len(good), 2)
    return 'rejected', round(sum(debits) / len(debits), 2)


def _strip_svg(debits, u_abs, u_rel_pct, units='L/s', quality_flags=None):
    """SVG strip chart coloured by uncertainty. Discharges flagged False are
    red and left out of the mean / band (computed on the True ones, or all)."""
    if not debits or len(debits) < 2:
        return None

    color, band_color = _uncertainty_color(u_rel_pct)
    debits = [round(float(d), 2) for d in debits]

    if quality_flags and len(quality_flags) == len(debits):
        dot_colors = ['#f14668' if f is False else color for f in quality_flags]
        true_debits = [d for d, f in zip(debits, quality_flags) if f is True]
        debits_ref = true_debits if true_debits else debits
    else:
        dot_colors = [color] * len(debits)
        debits_ref = debits

    mean = sum(debits_ref) / len(debits_ref)
    bh = u_abs    # half width = absolute uncertainty (GUM)

    W, H = 600, 100
    mL, mR, mT, mB = 70, 20, 30, 30
    plot_w = W - mL - mR
    mid_y = mT + (H - mT - mB) / 2

    x_min = min(min(debits), mean - bh) * 0.92
    x_max = max(max(debits), mean + bh) * 1.08
    if x_max == x_min:
        x_max = x_min + 1

    def xs(v):
        return mL + (v - x_min) / (x_max - x_min) * plot_w

    bx1, bx2 = xs(mean - bh), xs(mean + bh)
    mx = xs(mean)

    ticks = ''
    for val in [mean - bh, mean, mean + bh]:
        tx = xs(val)
        ticks += (
            f'<line x1="{tx:.1f}" y1="{mid_y+11:.1f}" x2="{tx:.1f}" y2="{mid_y+18:.1f}" '
            f'stroke="#bbb" stroke-width="1"/>'
            f'<text x="{tx:.1f}" y="{H-4}" text-anchor="middle" font-size="12" fill="#888">'
            f'{round(val, 1)}</text>'
        )

    dots = ''.join(
        f'<circle cx="{xs(d):.1f}" cy="{mid_y:.1f}" r="8" '
        f'fill="{c}" opacity="0.8" stroke="white" stroke-width="2"/>'
        for d, c in zip(debits, dot_colors)
    )

    return (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;display:block;overflow:visible;">'
        f'<line x1="{mL}" y1="{mid_y:.1f}" x2="{mL+plot_w}" y2="{mid_y:.1f}" stroke="#ddd" stroke-width="1.5"/>'
        f'<rect x="{bx1:.1f}" y="{mT}" width="{bx2-bx1:.1f}" height="{H-mT-mB}" '
        f'fill="{band_color}" rx="3"/>'
        f'{ticks}'
        f'<line x1="{mx:.1f}" y1="{mT}" x2="{mx:.1f}" y2="{H-mB}" '
        f'stroke="{color}" stroke-width="2.5"/>'
        f'{dots}'
        f'<text x="{mx:.1f}" y="{mT-8}" text-anchor="middle" font-size="14" '
        f'fill="{color}" font-weight="bold">{mean:.2f} {units}</text>'
        f'<text x="{W-2}" y="{mT+16}" text-anchor="end" font-size="12" '
        f'fill="{color}" font-weight="bold">±{u_abs} {units}  (±{u_rel_pct} %)</text>'
        f'</svg>'
    )


def _save(fig, filename):
    """Save a figure in the plots directory, return its static/ path."""
    fig.savefig(os.path.join(plots_dir(), filename), dpi=96, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return f'{PLOTS_SUBDIR}/{filename}'


def _style(ax, grid='y'):
    ax.tick_params(labelsize=8)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis=grid, linestyle='--', alpha=0.35)


# ── Plots ────────────────────────────────────────────────────────────────────

def _discharge_plot(datastreams, thing_id):
    """Discharge time series: one point per gauging, coloured by qualification.
    Always regenerated (depends on the quality flags)."""
    points = []
    for ds in datastreams:
        if not ds['debits']:
            continue
        start_dt, _end = parse_pt(ds.get('raw_pt', ''))
        if start_dt is None:
            continue
        status, mean_val = _status(ds)
        color = {'good': GOOD, 'unqualified': UNQUALIFIED, 'rejected': REJECTED}[status]
        points.append({'dt': start_dt.to_pydatetime(), 'mean': mean_val, 'color': color})

    if not points:
        return None
    points.sort(key=lambda p: p['dt'])

    legend = {
        GOOD: _('Good (mean of the validated discharges)'),
        UNQUALIFIED: _('Not qualified'),
        REJECTED: _('All rejected'),
    }
    colors_present = {p['color'] for p in points}

    try:
        fig, ax = plt.subplots(figsize=(10, 3.5))
        for p in points:
            ax.scatter(p['dt'], p['mean'], color=p['color'], s=80, zorder=3,
                       edgecolors='white', linewidths=0.8)
        # Legend: only the colours actually present
        handles = [
            Line2D([0], [0], marker='o', color='w', markerfacecolor=c,
                   markeredgecolor='#cccccc', markersize=9, label=legend[c])
            for c in [GOOD, UNQUALIFIED, REJECTED] if c in colors_present
        ]
        if handles:
            ax.legend(handles=handles, fontsize=8, framealpha=0.7)
        ax.set_ylabel('L/s', fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%Y'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate(rotation=30, ha='right')
        _style(ax)
        ax.grid(axis='x', linestyle='--', alpha=0.15)
        fig.tight_layout(pad=0.6)
        return _save(fig, plot_name('streamflow', thing_id))
    except Exception as e:
        print(e)
        plt.close('all')
        return None


def _rating_points(datastreams):
    """(heights, mean good discharges) of the gaugings with a height and at
    least one discharge qualified True."""
    h_list, q_list = [], []
    for ds in datastreams:
        if ds.get('height') is None:
            continue
        good = _good_debits(ds)
        if not good:
            continue
        h_list.append(float(ds['height']))
        q_list.append(round(sum(good) / len(good), 2))
    return h_list, q_list


def _rating_curve_fit_plot(datastreams, thing_id):
    """Fitted rating curve Q = a·(h−h0)^b (scipy curve_fit), on the same data as
    the CSV export. Always regenerated. Returns (plot path, fit dict) or (None, None)."""
    try:
        from scipy.optimize import curve_fit
    except ImportError:
        print('[TARAGE FIT] scipy not available')
        return None, None

    h_list, q_list = _rating_points(datastreams)
    if len(h_list) < 3:   # 3 parameters -> at least 3 points
        return None, None
    h, Q = np.array(h_list), np.array(q_list)

    def rating_curve(h_val, a, b, h0):
        return a * (h_val - h0) ** b

    try:
        params, cov = curve_fit(rating_curve, h, Q, p0=[1, 2, 0],
                                bounds=([0, 0, -0.01], [np.inf, 5, min(h) - 1e-4]),
                                maxfev=10000)
    except Exception as e:
        print(f'[TARAGE FIT] curve_fit failed: {e}')
        return None, None

    a, b, h0 = params
    sigma_a, sigma_b, sigma_h0 = np.sqrt(np.diag(cov))
    h_fit = np.linspace(0, max(h) * 1.1, 300)
    Q_fit = rating_curve(h_fit, a, b, h0)
    Q_pred = rating_curve(h, a, b, h0)
    rmse = np.sqrt(np.mean((Q - Q_pred) ** 2))
    ss_res = np.sum((Q - Q_pred) ** 2)
    ss_tot = np.sum((Q - np.mean(Q)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float('nan')

    try:
        fig, ax = plt.subplots(figsize=(5, 5))
        ax.scatter(h, Q, color='#3273dc', s=80, zorder=3, edgecolors='white',
                   linewidths=0.8, label=_('Discharges (tracing)'))
        sign = '−' if h0 >= 0 else '+'
        ax.plot(h_fit, Q_fit, color='#f14668', linewidth=2,
                label=f'Q = {a:.3f}·(h {sign} {abs(h0):.3f})^{b:.3f}')
        ax.set_xlabel(_('Height (m)'), fontsize=9)
        ax.set_ylabel(_('Discharge (L/s)'), fontsize=9)
        ax.set_xlim(0, max(h) * 1.1)
        ax.set_ylim(0, max(Q) * 1.1)
        ax.legend(fontsize=8, loc='upper left')
        _style(ax, grid='both')
        ax.text(0.97, 0.05, f'RMSE = {rmse:.3f} L/s\nR² = {r2:.3f}',
                transform=ax.transAxes, ha='right', va='bottom', fontsize=8, color='#444',
                bbox=dict(boxstyle='round,pad=0.4', fc='white', ec='#ddd', alpha=0.85))
        fig.tight_layout(pad=0.6)
        url = _save(fig, plot_name('rating_curve_fit', thing_id))
    except Exception as e:
        print(f'[TARAGE FIT] plot failed: {e}')
        plt.close('all')
        url = None

    # Gauging period of the fitted points
    starts = [parse_pt(ds.get('raw_pt', ''))[0] for ds in datastreams
              if ds.get('height') is not None and _good_debits(ds)]
    starts = [s for s in starts if s is not None]

    def r(v, n=6):
        return round(float(v), n)

    fit = {'a': r(a), 'b': r(b), 'h0': r(h0), 'sigma_a': r(sigma_a), 'sigma_b': r(sigma_b),
           'sigma_h0': r(sigma_h0), 'r2': r(r2, 4), 'rmse': r(rmse, 3),
           'h_max': r(max(h), 4), 'n_points': len(h),
           'period': f"{min(starts):%Y-%m-%d}/{max(starts):%Y-%m-%d}" if starts else ''}
    return url, fit


def _conductivity_plot(ds_id, observations):
    """Conductivity series of a gauging (cached)."""
    if not observations:
        return None
    try:
        dates = pd.to_datetime([o['phenomenonTime'] for o in observations], utc=True)
        values = [o['result'] for o in observations]
        fig, ax = plt.subplots(figsize=(9, 2.8))
        ax.plot(dates, values, color='#5b9cf6', linewidth=1.2)
        ymin = min(values)
        ax.fill_between(dates, values, ymin, alpha=0.10, color='#5b9cf6')
        ax.set_ylim(bottom=ymin)
        ax.set_ylabel(cfg.CONDUCTIVITY_UNIT['symbol'], fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m %H:%M'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate(rotation=30, ha='right')
        _style(ax)
        fig.tight_layout(pad=0.6)
        return _save(fig, plot_name('conductivity', ds_id))
    except Exception:
        plt.close('all')
        return None


def _height_plot(ref_ds_id, cond_ds_id, pt_str):
    """Water level of the reference station over [start-1h, end+1h] of the
    gauging (cached, named after the conductivity MultiDatastream)."""
    start_dt, end_dt = parse_pt(pt_str)
    if start_dt is None:
        return None
    win_start = start_dt - pd.Timedelta(hours=1)
    win_end = end_dt + pd.Timedelta(hours=1)

    obs = fetch_observations(ref_ds_id, win_start, win_end)
    if not obs:
        return None
    df = pd.DataFrame(obs)
    df['phenomenonTime'] = pd.to_datetime(df['phenomenonTime'], utc=True)
    df = df.sort_values('phenomenonTime')

    try:
        fig, ax = plt.subplots(figsize=(5, 2.6))
        ax.plot(df['phenomenonTime'].values, df['result'].values,
                color='#3273dc', linewidth=1.2, zorder=2)
        ax.scatter(df['phenomenonTime'].values, df['result'].values,
                   color='#3273dc', s=16, zorder=3, linewidths=0)
        # Vertical lines: start (red) and end (orange) of the gauging
        ax.axvline(start_dt.to_pydatetime(), color='#f14668', linewidth=1.5,
                   linestyle='--', label=_('Start'), zorder=5)
        if end_dt != start_dt:
            ax.axvline(end_dt.to_pydatetime(), color='#ffb70f', linewidth=1.5,
                       linestyle='--', label=_('End'), zorder=5)
        ax.set_ylabel('m', fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.set_xlim(win_start.to_pydatetime(), win_end.to_pydatetime())
        _style(ax)
        ax.legend(fontsize=7, loc='best', framealpha=0.7)
        fig.tight_layout(pad=0.6)
        return _save(fig, plot_name('height', cond_ds_id))
    except Exception as e:
        print(f'[HEIGHT] cond_ds={cond_ds_id}: {e}')
        plt.close('all')
        return None


def _precip_key(ds_id, url):
    """Cache key of a rainfall plot: the gauging + the rainfall station."""
    return f"{ds_id}_{hashlib.sha1(url.encode()).hexdigest()[:8]}"


def _precip_plot(ds_id, pt_str, station_url):
    """Hourly rainfall of the gauging day (red line = start of the gauging),
    from the site's rainfall Datastream `station_url` (cached)."""
    start_dt, _end = parse_pt(pt_str)
    if start_dt is None or not station_url:
        return None

    day_start = start_dt.normalize()                           # 00:00:00 UTC
    day_end = day_start + pd.Timedelta(hours=23, minutes=59, seconds=59)
    fmt = '%Y-%m-%dT%H:%M:%SZ'

    obs = []
    url = station_url.rstrip('/') + '/Observations'
    params = {
        '$filter': f"phenomenonTime ge {day_start.strftime(fmt)} and phenomenonTime le {day_end.strftime(fmt)}",
        '$select': 'result,phenomenonTime',
        '$orderby': 'phenomenonTime asc',
        '$top': 1000,
    }
    while url:
        try:
            r = sta_client.raw_get(url, params=params, timeout=10)
        except Exception as e:
            print(f'[PRECIP] DS id={ds_id} | network error: {e}')
            break
        if not r.ok:
            break
        body = r.json()
        obs.extend(body.get('value', []))
        url = body.get('@iot.nextLink')
        params = None
    if not obs:
        return None

    df = pd.DataFrame(obs)
    df['phenomenonTime'] = pd.to_datetime(df['phenomenonTime'], utc=True)
    df['hour'] = df['phenomenonTime'].dt.floor('h')
    hourly = df.groupby('hour')['result'].sum().reset_index()

    try:
        fig, ax = plt.subplots(figsize=(5, 2.6))
        ax.bar(hourly['hour'].values, hourly['result'].values, width=1 / 24,
               align='edge', color='#5b9cf6', alpha=0.75, linewidth=0)
        ax.axvline(start_dt.to_pydatetime(), color='#f14668', linewidth=1.5,
                   linestyle='--', label=_('Gauging'), zorder=5)
        ax.set_ylabel('mm/h', fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Hh'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
        ax.set_xlim(day_start.to_pydatetime(), day_end.to_pydatetime())
        ax.set_ylim(bottom=0)
        _style(ax)
        ax.legend(fontsize=7, loc='upper right', framealpha=0.7)
        fig.tight_layout(pad=0.6)
        return _save(fig, plot_name('precip', _precip_key(ds_id, station_url)))
    except Exception as e:
        print(f'Precip plot {ds_id}: {e}')
        plt.close('all')
        return None


def _cached(prefix, key, build):
    """Static path of a cached plot, building it with `build()` when missing."""
    filename = plot_name(prefix, key)
    if os.path.exists(os.path.join(plots_dir(), filename)):
        return f'{PLOTS_SUBDIR}/{filename}'
    return build()


# ── Data ─────────────────────────────────────────────────────────────────────

def _conductivity_datastreams():
    """All the conductivity MultiDatastreams, with their Thing."""
    op_id = find_id('ObservedProperties', cfg.CONDUCTIVITY_NAME)
    if op_id is None:
        return None
    datastreams, _error = get_all(f'/ObservedProperties({op_id})/MultiDatastreams',
                                  params={'$select': 'id,name,properties,phenomenonTime',
                                          '$expand': 'Thing($select=id,name)'})
    return datastreams


def _softsensor_targets():
    """[{id, name}] of the derived discharge MultiDatastreams
    (observationProcedure SoftSensor, main property = streamflow)."""
    datastreams, _error = get_all('/MultiDatastreams',
                                  params={'$filter': "properties/observationProcedure eq 'SoftSensor'",
                                          '$select': 'id,name',
                                          '$expand': 'ObservedProperties($select=name)'})
    return sorted(({'id': ds['@iot.id'], 'name': ds['name']}
                   for ds in datastreams if main_property(ds) == cfg.STREAMFLOW_NAME),
                  key=lambda t: t['name'])


def _site_refs(thing_id):
    """(Thing location {lng, lat} or None, reference water-level station or None,
    rainfall Datastream URL or None) of a gauging site."""
    location, height_ref = None, None
    r = sta_client.get(SERVER, f'/Things({thing_id})',
                       params={'$select': 'properties',
                               '$expand': 'Locations($select=location;$top=1)'})
    if not r.ok:
        return location, height_ref, None
    thing = r.json()
    precipitation_url = ((thing.get('properties') or {}).get('precipitation_ref') or {}).get('url')

    locs = thing.get('Locations') or []
    if locs:
        geom = locs[0].get('location') or {}
        if geom.get('type') == 'Feature':
            geom = geom.get('geometry') or {}
        coords = geom.get('coordinates') or []
        if geom.get('type') == 'Point' and len(coords) >= 2:
            location = {'lng': float(coords[0]), 'lat': float(coords[1])}

    href = (thing.get('properties') or {}).get('height_ref')
    if href:
        if href.get('unavailable'):
            height_ref = {'unavailable': True}
        else:
            ref_thing_id = (href.get('Thing') or {}).get('@iot.id')
            ref_ds_id = (href.get('MultiDatastream') or {}).get('@iot.id')
            if ref_thing_id and ref_ds_id:
                r_rt = sta_client.get(SERVER, f'/Things({ref_thing_id})', params={'$select': 'name'})
                r_rds = sta_client.get(SERVER, f'/MultiDatastreams({ref_ds_id})', params={'$select': 'name'})
                height_ref = {
                    'thing_id': ref_thing_id,
                    'thing_name': r_rt.json().get('name', f'Thing {ref_thing_id}') if r_rt.ok else f'Thing {ref_thing_id}',
                    'ds_id': ref_ds_id,
                    'ds_name': r_rds.json().get('name', f'DS {ref_ds_id}') if r_rds.ok else f'DS {ref_ds_id}',
                }
    return location, height_ref, precipitation_url


def _gauging(ds, height_ref, precipitation_url):
    """Template data of one conductivity MultiDatastream (= one gauging)."""
    ds_id = ds['@iot.id']
    props = ds.get('properties') or {}
    tracer = props.get('tracer') or {}
    sf_info = props.get(cfg.STREAMFLOW_NAME) or {}

    masses_raw = tracer.get('weights')
    masses = [int(m) for m in masses_raw] if isinstance(masses_raw, list) else []

    debits = [round(float(d), 2) for d in sf_info.get('value', [])]
    units = sf_info.get('units', 'L/s')
    quality_flags = sf_info.get('qualityFlag')   # None or [true, false, ...]
    height = (props.get('height') or {}).get('value')

    # Uncertainty on the True-qualified discharges only (when flagged)
    good = [d for d, f in zip(debits, quality_flags) if f is True] \
        if quality_flags and len(quality_flags) == len(debits) else []
    uncertainty = _compute_uncertainty(good if len(good) >= 2 else debits)
    strip = _strip_svg(debits, uncertainty['abs'], uncertainty['rel_pct'], units,
                       quality_flags=quality_flags) if uncertainty else None

    raw_pt = ds.get('phenomenonTime') or ''
    n_obs = None

    def build_conductivity():
        nonlocal n_obs
        obs = fetch_observations(ds_id)
        n_obs = len(obs)
        return _conductivity_plot(ds_id, obs)

    height_url = None
    if height_ref and not height_ref.get('unavailable'):
        height_url = _cached('height', ds_id,
                             lambda: _height_plot(height_ref['ds_id'], ds_id, raw_pt))

    return {
        'id': ds_id,
        'name': ds.get('name', f'DS {ds_id}'),
        'pt': _format_pt(raw_pt),
        'raw_pt': raw_pt,
        'masses': masses,
        'debits': debits,
        'debit_mean': round(sum(debits) / len(debits), 2) if debits else None,
        'units': units,
        'incert_abs': uncertainty['abs'] if uncertainty else None,
        'incert_rel': uncertainty['rel_pct'] if uncertainty else None,
        'strip_svg': strip,
        'quality_flags': quality_flags,
        'height': height,
        'plot_url': _cached('conductivity', ds_id, build_conductivity),
        'precip_url': _cached('precip', _precip_key(ds_id, precipitation_url),
                              lambda: _precip_plot(ds_id, raw_pt, precipitation_url))
        if precipitation_url else None,
        'height_url': height_url,
        'n_obs': n_obs,
    }


# ── Routes ───────────────────────────────────────────────────────────────────

@tarage_bp.get('/list')
@jwt_required_or_redirect()
def gauging_list():
    all_ds = _conductivity_datastreams()
    if all_ds is None:
        return render_template(
            'private/tarage/list.html',
            error=_("ObservedProperty '%(name)s' not found", name=cfg.CONDUCTIVITY_NAME),
            things=[], thing_id=None, thing_name='', datastreams=[], sf_plot_url=None)

    # Distinct Things for the selector
    things_dict = {}
    for ds in all_ds:
        t = ds.get('Thing') or {}
        if t.get('@iot.id') is not None:
            things_dict.setdefault(t['@iot.id'], t.get('name', f"Thing {t['@iot.id']}"))
    things = [{'id': t_id, 'name': name}
              for t_id, name in sorted(things_dict.items(), key=lambda x: x[1])]

    thing_id = request.args.get('thing_id', type=int)
    thing_name = things_dict.get(thing_id, '') if thing_id is not None else ''

    if thing_id is None:
        return render_template('private/tarage/list.html', things=things, thing_id=None,
                               thing_name='', datastreams=[], sf_plot_url=None, error=None)

    # Gaugings of the selected Thing, most recent first
    def sort_key(ds):
        pt = ds.get('phenomenonTime') or ''
        if not pt or pt == '/':
            return ''
        return pt.split('/')[-1]

    filtered = sorted((ds for ds in all_ds if (ds.get('Thing') or {}).get('@iot.id') == thing_id),
                      key=sort_key, reverse=True)

    thing_location, height_ref, precipitation_url = _site_refs(thing_id)
    datastreams = [_gauging(ds, height_ref, precipitation_url) for ds in filtered]

    # Discharge time series + stage-discharge relation + fitted curve
    sf_plot_url = _discharge_plot(datastreams, thing_id)
    rating_curve_fit_url, rating_fit = _rating_curve_fit_plot(datastreams, thing_id)

    rating_curve_data = []
    for ds in datastreams:
        if ds.get('height') is None or not ds.get('debits'):
            continue
        status, mean_val = _status(ds)
        start_dt, end_dt = parse_pt(ds.get('raw_pt', ''))
        rating_curve_data.append({
            'name': ds['name'],
            'height': float(ds['height']),
            'debit_moyen': mean_val,
            'status': status,
            'date_debut': start_dt.strftime('%Y-%m-%dT%H:%M:%SZ') if start_dt else '',
            'date_fin': end_dt.strftime('%Y-%m-%dT%H:%M:%SZ') if end_dt else '',
        })

    # Qualification counts
    ds_counts = {'total': 0, 'good': 0, 'unqualified': 0, 'rejected': 0}
    for ds in datastreams:
        if not ds['debits']:
            continue
        ds_counts['total'] += 1
        ds_counts[_status(ds)[0]] += 1

    return render_template(
        'private/tarage/list.html',
        things=things,
        thing_id=thing_id,
        thing_name=thing_name,
        thing_location=thing_location,
        height_ref=height_ref,
        precipitation_url=precipitation_url,
        ds_counts=ds_counts,
        datastreams=datastreams,
        sf_plot_url=sf_plot_url,
        rating_curve_data=rating_curve_data,
        rating_curve_fit_url=rating_curve_fit_url,
        rating_fit=rating_fit,
        softsensor_targets=_softsensor_targets() if rating_fit else [],
        error=None,
    )


@tarage_bp.get('/list/api/ref-things')
@jwt_required_or_redirect()
def api_ref_things():
    """Things having a water-level MultiDatastream (config_tarage.HEIGHT_NAME)."""
    return jsonify(things_with_property(cfg.HEIGHT_NAME))


@tarage_bp.get('/list/api/ref-things/<int:ref_thing_id>/datastreams')
@jwt_required_or_redirect()
def api_ref_thing_datastreams(ref_thing_id):
    """Water-level MultiDatastreams of a reference Thing."""
    datastreams, _error = get_all(f'/Things({ref_thing_id})/MultiDatastreams',
                                  params={'$select': 'id,name',
                                          '$expand': 'ObservedProperties($select=name)'})
    return jsonify([{'id': ds['@iot.id'], 'name': ds.get('name', f"DS {ds['@iot.id']}")}
                    for ds in datastreams if main_property(ds) == cfg.HEIGHT_NAME])


def _patch_properties(path, update):
    """GET the entity properties, apply `update(props)` (may return an error
    message), PATCH them back. Returns a Flask response."""
    r = sta_client.get(SERVER, path, params={'$select': 'properties'})
    if not r.ok:
        return jsonify({'error': _('%(entity)s not found (%(code)s)', entity=path.strip('/'),
                                   code=r.status_code)}), 502
    props = r.json().get('properties') or {}
    error = update(props)
    if error:
        return jsonify({'error': error}), 400
    r_patch = sta_client.patch(SERVER, path, json={'properties': props})
    if not r_patch.ok:
        return jsonify({'error': r_patch.text}), 502
    return jsonify({'ok': True})


@tarage_bp.patch('/list/api/thing/<int:thing_id>/height-ref')
@jwt_required_or_redirect()
def save_height_ref(thing_id):
    """Store the reference water-level station in the Thing properties."""
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({'error': _('Missing JSON body')}), 400

    def update(props):
        if body.get('unavailable'):
            props['height_ref'] = {'unavailable': True}
            return None
        ref_thing_id, ref_ds_id = body.get('thing_id'), body.get('ds_id')
        if not ref_thing_id or not ref_ds_id:
            return _('thing_id and ds_id are required')
        props['height_ref'] = {'Thing': {'@iot.id': int(ref_thing_id)},
                               'MultiDatastream': {'@iot.id': int(ref_ds_id)}}
        return None

    return _patch_properties(f'/Things({thing_id})', update)


@tarage_bp.patch('/list/api/thing/<int:thing_id>/precipitation-ref')
@jwt_required_or_redirect()
def save_precipitation_ref(thing_id):
    """Store the rainfall station (a Datastream URL) in the Thing properties;
    an empty url removes it."""
    url = ((request.get_json(silent=True) or {}).get('url') or '').strip()
    if url and not url.startswith(('http://', 'https://')):
        return jsonify({'error': _('Invalid URL')}), 400

    def update(props):
        if url:
            props['precipitation_ref'] = {'url': url}
        else:
            props.pop('precipitation_ref', None)

    return _patch_properties(f'/Things({thing_id})', update)


@tarage_bp.patch('/list/api/height/<int:ds_id>')
@jwt_required_or_redirect()
def save_height(ds_id):
    """Store the water level measured during a gauging in its properties."""
    body = request.get_json(silent=True) or {}
    try:
        value = float(body['value'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': _('Invalid value')}), 400

    def update(props):
        props['height'] = {'units': 'm', 'value': value}

    return _patch_properties(f'/MultiDatastreams({ds_id})', update)


@tarage_bp.patch('/list/api/qualify/<int:ds_id>')
@jwt_required_or_redirect()
def qualify_gauging(ds_id):
    """Store the quality flags [bool, ...] of the discharges of a gauging."""
    body = request.get_json(silent=True) or {}
    flags = body.get('qualityFlag')
    if not isinstance(flags, list) or not all(isinstance(f, bool) for f in flags):
        return jsonify({'error': _('Missing qualityFlag')}), 400

    def update(props):
        sf = props.get(cfg.STREAMFLOW_NAME) or {}
        sf['qualityFlag'] = flags
        props[cfg.STREAMFLOW_NAME] = sf

    return _patch_properties(f'/MultiDatastreams({ds_id})', update)


@tarage_bp.get('/list/api/export-rating-curve/<int:thing_id>')
@jwt_required_or_redirect()
def export_rating_curve(thing_id):
    """CSV height (m), mean discharge (L/s), u, start, end: only the gaugings
    with a height AND discharges qualified True."""
    datastreams, _error = get_all(f'/Things({thing_id})/MultiDatastreams',
                                  params={'$select': 'id,properties,phenomenonTime',
                                          '$expand': 'ObservedProperties($select=name)'})
    rows = []
    for ds in datastreams:
        if main_property(ds) != cfg.CONDUCTIVITY_NAME:
            continue
        props = ds.get('properties') or {}
        sf_info = props.get(cfg.STREAMFLOW_NAME) or {}
        height = (props.get('height') or {}).get('value')
        good = _good_debits({'debits': sf_info.get('value') or [],
                             'quality_flags': sf_info.get('qualityFlag')})
        if height is None or not good:
            continue
        good = [float(d) for d in good]
        uncertainty = _compute_uncertainty(good)
        start_dt, end_dt = parse_pt(ds.get('phenomenonTime') or '')
        rows.append({
            'height': float(height),
            'mean_discharge': round(sum(good) / len(good), 2),
            'q_sigma': uncertainty['abs'] if uncertainty else '',
            'start': start_dt.strftime('%Y-%m-%dT%H:%M:%SZ') if start_dt else '',
            'end': end_dt.strftime('%Y-%m-%dT%H:%M:%SZ') if end_dt else '',
        })
    rows.sort(key=lambda r: r['start'])

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['height', 'mean_discharge', 'q_sigma', 'start', 'end'])
    writer.writeheader()
    writer.writerows(rows)
    return Response(output.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition': f'attachment; filename="stage_discharge_{thing_id}.csv"'})


@tarage_bp.post('/list/api/apply-rating-curve')
@jwt_required_or_redirect()
def apply_rating_curve():
    """Apply the fitted curve: SoftSensor association `rating_curve` (a, b, h0,
    h_max) on the reference water-level MultiDatastream + fit metadata
    (properties.ratingCurve) on the derived discharge MultiDatastream."""
    data = request.get_json(silent=True) or {}
    try:
        source_id = int(data['source_id'])
        target_id = int(data['target_id'])
        fit = {k: float(data[k]) for k in ('a', 'b', 'h0', 'h_max', 'sigma_a', 'sigma_b',
                                           'sigma_h0', 'r2', 'rmse')}
        fit['n_points'] = int(data['n_points'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': _('Invalid parameters: %(error)s', error='a, b, h0, h_max…')}), 400

    r = sta_client.get(SERVER, f'/MultiDatastreams({target_id})', params={'$select': 'name'})
    if not r.ok:
        return jsonify({'error': _('SensorThings service not active or unreachable')}), 502

    result, error = set_producer(source_id, 'rating_curve', r.json()['name'],
                                 {k: fit[k] for k in ('a', 'b', 'h0', 'h_max')})
    if error:
        return jsonify({'error': error[0]}), error[1]

    # Which curve produced the derived discharges. Re-read the properties:
    # set_producer may have just updated the target's maxValue.
    r = sta_client.get(SERVER, f'/MultiDatastreams({target_id})', params={'$select': 'properties'})
    if not r.ok:
        return jsonify({'error': _('SensorThings service not active or unreachable')}), 502
    props = r.json().get('properties') or {}
    props['ratingCurve'] = dict(fit, model='Q = a·(h−h0)^b',
                                gaugingSite=data.get('gauging_site', ''),
                                period=data.get('period', ''),
                                computed=date.today().isoformat())
    r = sta_client.patch(SERVER, f'/MultiDatastreams({target_id})', json={'properties': props})
    if not r.ok:
        return jsonify({'error': r.text}), 502
    return jsonify(result)


@tarage_bp.post('/list/refresh')
@jwt_required_or_redirect()
def refresh_plots():
    """Delete the cached plots so they are rebuilt on the next load."""
    directory = plots_dir()
    for f in os.listdir(directory):
        if f.endswith('_plot.png'):
            os.remove(os.path.join(directory, f))
    return jsonify({'ok': True})
