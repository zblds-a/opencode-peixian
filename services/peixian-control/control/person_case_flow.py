"""Person-to-case full-coverage plan: person tools then stay centers then location tools."""
from __future__ import annotations

import copy
import math
from datetime import datetime

from . import theft_scoring
from shared import theft_provider_v2 as adapter

VERSION = 'person-case-flow-v1'
PERSON_KINDS = ('profile', 'tracks', 'warning_detail', 'warning_logs', 'night', 'community')
LOCATION_KINDS = ('incidents', 'captures')
ALL_KINDS = PERSON_KINDS + LOCATION_KINDS
MAX_CENTERS = 3
CLUSTER_RADIUS_M = 120
DEFAULT_RADIUS_M = 500
KIND_LABELS = {
    'profile': '档案',
    'tracks': '轨迹',
    'warning_detail': '预警概况',
    'warning_logs': '近七天预警明细',
    'night': '夜间',
    'community': '跨小区',
    'incidents': '周边警情',
    'captures': '周边抓拍',
}


def _haversine_m(lon1, lat1, lon2, lat2):
    try:
        lon1, lat1, lon2, lat2 = map(float, (lon1, lat1, lon2, lat2))
    except (TypeError, ValueError):
        return None
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace('T', ' ')[:19]
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(text[: len(fmt.replace('%', '0'))], fmt)
        except ValueError:
            continue
    try:
        return datetime.strptime(text, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


def task_completed_kinds(store, uid, sid, task_id):
    """Set of completed tool kinds for this native task (any person/location)."""
    rows = store.rows(
        "SELECT request_ciphertext FROM business_runs WHERE uid=? AND session_id=? "
        "ORDER BY rowid DESC LIMIT 50",
        (uid, sid),
    )
    kinds = set()
    failed = set()
    for row in rows:
        snapshot = store.decrypt(row['request_ciphertext'])
        context = snapshot.get('native_tool_context') or {}
        if context.get('task_id') != task_id:
            continue
        for call in (snapshot.get('native_calls') or {}).values():
            if not isinstance(call, dict):
                continue
            plan = call.get('frozen') or {}
            kind = plan.get('kind')
            if not kind:
                continue
            status = call.get('status')
            if status == 'completed':
                kinds.add(kind)
                if kind == 'warnings':
                    kinds.add('warning_detail')
            elif status in ('rejected', 'failed', 'unknown'):
                failed.add(kind)
    return kinds, failed


def task_track_records(store, uid, sid, task_id):
    from .trusted_results import checked_result, digest as result_digest

    rows = store.rows(
        "SELECT b.request_ciphertext, r.* FROM business_runs b "
        "JOIN run_results r ON r.run_id=b.id WHERE b.uid=? AND b.session_id=? "
        "ORDER BY b.rowid DESC LIMIT 50",
        (uid, sid),
    )
    records = []
    for row in rows:
        snapshot = store.decrypt(row['request_ciphertext'])
        context = snapshot.get('native_tool_context') or {}
        if context.get('task_id') != task_id:
            continue
        result = checked_result(store, row)
        for record in result.get('records') or []:
            call = (snapshot.get('native_calls') or {}).get(record.get('call_id'), {})
            plan = call.get('frozen') or {}
            if call.get('status') != 'completed' or plan.get('kind') != 'tracks':
                continue
            if record.get('module') != 'tracks':
                continue
            item = copy.deepcopy(record)
            item['result_digest'] = result_digest(result)
            item['source_run_id'] = result.get('run_id')
            item['_snapshot'] = snapshot
            records.append(item)
    return records


def task_profile_address(store, uid, sid, task_id):
    from .trusted_results import checked_result

    rows = store.rows(
        "SELECT b.request_ciphertext, r.* FROM business_runs b "
        "JOIN run_results r ON r.run_id=b.id WHERE b.uid=? AND b.session_id=? "
        "ORDER BY b.rowid DESC LIMIT 50",
        (uid, sid),
    )
    for row in rows:
        snapshot = store.decrypt(row['request_ciphertext'])
        context = snapshot.get('native_tool_context') or {}
        if context.get('task_id') != task_id:
            continue
        result = checked_result(store, row)
        for record in result.get('records') or []:
            if record.get('module') != 'profile':
                continue
            person = (record.get('fields') or {}).get('person') or {}
            if isinstance(person, dict):
                for key in ('hjdz', 'address', 'xxdz', 'hjd'):
                    value = person.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
    return None


def _night_bonus(when):
    if not when:
        return 0
    hour = when.hour
    return 1 if hour >= 23 or hour < 5 else 0


def _address_overlap(place, domicile):
    if not isinstance(place, str) or not isinstance(domicile, str):
        return False
    a, b = place.strip(), domicile.strip()
    if len(a) < 4 or len(b) < 4:
        return False
    # Shared contiguous chunk of length >= 4
    for size in range(min(8, len(a), len(b)), 3, -1):
        for i in range(len(a) - size + 1):
            if a[i : i + size] in b:
                return True
    return False


def stay_points_from_tracks(track_records, domicile=None, max_centers=MAX_CENTERS):
    """Cluster track points; return ranked stay centers with source refs."""
    points = []
    for record in track_records or []:
        fields = record.get('fields') or {}
        lon, lat = fields.get('lon'), fields.get('lat')
        try:
            lon_f, lat_f = float(lon), float(lat)
        except (TypeError, ValueError):
            continue
        when = _parse_time(fields.get('captureTime'))
        place = fields.get('deviceName') or fields.get('localAddress') or fields.get('location') or ''
        points.append({
            'lon': lon_f,
            'lat': lat_f,
            'when': when,
            'place': place if isinstance(place, str) else '',
            'record': record,
            'night': _night_bonus(when),
        })
    if not points:
        return []

    clusters = []
    for point in points:
        assigned = None
        for cluster in clusters:
            dist = _haversine_m(point['lon'], point['lat'], cluster['lon'], cluster['lat'])
            if dist is not None and dist <= CLUSTER_RADIUS_M:
                assigned = cluster
                break
        if assigned is None:
            clusters.append({
                'lon': point['lon'],
                'lat': point['lat'],
                'points': [point],
                'place': point['place'],
            })
        else:
            assigned['points'].append(point)
            # Re-average center
            n = len(assigned['points'])
            assigned['lon'] = sum(p['lon'] for p in assigned['points']) / n
            assigned['lat'] = sum(p['lat'] for p in assigned['points']) / n
            if not assigned['place'] and point['place']:
                assigned['place'] = point['place']

    centers = []
    for index, cluster in enumerate(clusters, 1):
        pts = cluster['points']
        primary = max(pts, key=lambda p: (p['night'], p['when'] or datetime.min))
        record = primary['record']
        count = len(pts)
        nights = sum(p['night'] for p in pts)
        score = count + nights * 0.5
        place = cluster['place'] or (record.get('fields') or {}).get('deviceName') or ''
        domicile_like = _address_overlap(place, domicile) if domicile else False
        if domicile_like:
            score *= 0.35
        times = [p['when'] for p in pts if p['when']]
        centers.append({
            'version': VERSION,
            'rank': index,
            'lon': round(cluster['lon'], 6),
            'lat': round(cluster['lat'], 6),
            'place': place or f"停留点{index}",
            'visit_count': count,
            'night_count': nights,
            'score': round(score, 2),
            'domicile_like': domicile_like,
            'label': ('疑似常住地·' if domicile_like else '') + (place or f'停留点{index}'),
            'time_span': {
                'start': min(times).strftime('%Y-%m-%d %H:%M:%S') if times else None,
                'end': max(times).strftime('%Y-%m-%d %H:%M:%S') if times else None,
            },
            'run_id': record.get('source_run_id'),
            'record_id': record.get('record_id'),
            'snapshot_id': record.get('snapshot_id'),
            'result_digest': record.get('result_digest'),
            'source_ids': [record.get('record_id')],
            'coordinate_reusable': True,
        })

    centers.sort(key=lambda c: (-c['score'], -c['visit_count'], c['record_id'] or ''))
    for index, item in enumerate(centers[:max_centers], 1):
        item['rank'] = index
    return centers[:max_centers]


def authorize_centers(centers, n=MAX_CENTERS, radius_m=DEFAULT_RADIUS_M):
    selected = list(centers or [])[: max(1, min(int(n), MAX_CENTERS))]
    out = []
    for item in selected:
        if not item.get('record_id') or not item.get('run_id') or not item.get('snapshot_id'):
            continue
        out.append({
            'version': VERSION,
            'rank': item['rank'],
            'label': item.get('label') or item.get('place'),
            'lon': item['lon'],
            'lat': item['lat'],
            'radius_m': radius_m,
            'domicile_like': bool(item.get('domicile_like')),
            'visit_count': item.get('visit_count'),
            'run_id': item['run_id'],
            'record_id': item['record_id'],
            'snapshot_id': item['snapshot_id'],
            'result_digest': item.get('result_digest'),
            'source_ref': {
                'run_id': item['run_id'],
                'result_digest': item.get('result_digest'),
                'record_id': item['record_id'],
                'snapshot_id': item['snapshot_id'],
            },
            'coordinate_reusable': True,
        })
    return out


def _location_done(completed_kinds, center, kind, calls_by_center=None):
    """Whether this center+kind was completed. Prefer per-center tracking when given."""
    if calls_by_center and center.get('record_id'):
        key = center['record_id'] + ':' + kind
        if key in calls_by_center:
            return True
    # Fallback: kind completed at least once (coarse)
    return kind in completed_kinds


def location_calls_by_center(store, uid, sid, task_id):
    """Set of record_id:kind for completed location queries sourced from a track center."""
    rows = store.rows(
        "SELECT request_ciphertext FROM business_runs WHERE uid=? AND session_id=? "
        "ORDER BY rowid DESC LIMIT 50",
        (uid, sid),
    )
    done = set()
    for row in rows:
        snapshot = store.decrypt(row['request_ciphertext'])
        context = snapshot.get('native_tool_context') or {}
        if context.get('task_id') != task_id:
            continue
        for call in (snapshot.get('native_calls') or {}).values():
            if not isinstance(call, dict) or call.get('status') != 'completed':
                continue
            plan = call.get('frozen') or {}
            kind = plan.get('kind')
            if kind not in LOCATION_KINDS:
                continue
            for ref in call.get('source_refs') or context.get('source_refs') or []:
                if isinstance(ref, dict) and ref.get('record_id'):
                    done.add(ref['record_id'] + ':' + kind)
    return done


def build_person_case_plan(store, uid, sid, context, allowed_tools=None, radius_m=DEFAULT_RADIUS_M):
    """Build/refresh the full-coverage plan for person_to_case."""
    confirmed = context.get('confirmed') or {}
    if 'person_identity' not in confirmed or 'start' not in confirmed or 'end' not in confirmed:
        return None
    task_id = context.get('task_id')
    if not task_id:
        return None
    allowed = set(allowed_tools) if allowed_tools is not None else None

    def kind_ok(kind):
        if allowed is None:
            return True
        return 'peixian_query_' + kind in allowed

    completed, failed = task_completed_kinds(store, uid, sid, task_id)
    items = []
    # Phase 1: person tools
    for kind in PERSON_KINDS:
        if not kind_ok(kind):
            continue
        status = 'done' if kind in completed else ('failed' if kind in failed else 'pending')
        items.append({
            'phase': 'person',
            'kind': kind,
            'label': KIND_LABELS.get(kind, kind),
            'status': status,
        })

    person_pending = [i for i in items if i['phase'] == 'person' and i['status'] == 'pending']
    tracks_ready = 'tracks' in completed

    stay_points = []
    center_set = list(context.get('center_set') or [])
    if tracks_ready:
        tracks = task_track_records(store, uid, sid, task_id)
        domicile = task_profile_address(store, uid, sid, task_id)
        stay_points = stay_points_from_tracks(tracks, domicile=domicile)
        if not center_set and stay_points:
            center_set = authorize_centers(stay_points, n=MAX_CENTERS, radius_m=radius_m)
        elif center_set:
            # refresh radius
            for c in center_set:
                c['radius_m'] = radius_m

    loc_done = location_calls_by_center(store, uid, sid, task_id) if center_set else set()
    # Phase 2: location tools per center (only after person phase has no pending, or tracks at least done)
    if tracks_ready and not person_pending:
        for center in center_set:
            for kind in LOCATION_KINDS:
                if not kind_ok(kind):
                    continue
                key = (center.get('record_id') or '') + ':' + kind
                if key in loc_done:
                    status = 'done'
                elif kind in failed:
                    status = 'failed'
                else:
                    status = 'pending'
                items.append({
                    'phase': 'location',
                    'kind': kind,
                    'label': KIND_LABELS.get(kind, kind) + '·' + (center.get('label') or ''),
                    'status': status,
                    'center_rank': center.get('rank'),
                    'center_record_id': center.get('record_id'),
                    'source_ref': center.get('source_ref'),
                    'radius_m': center.get('radius_m') or radius_m,
                })

    pending = [i for i in items if i['status'] == 'pending']
    done = [i for i in items if i['status'] == 'done']
    failed_items = [i for i in items if i['status'] == 'failed']
    coverage = {kind: ('done' if kind in completed else ('failed' if kind in failed else 'pending')) for kind in ALL_KINDS if kind_ok(kind)}
    # Location kinds may be pending per-center even if kind appears in completed
    for kind in LOCATION_KINDS:
        if any(i['kind'] == kind and i['status'] == 'pending' for i in items):
            coverage[kind] = 'pending'

    return {
        'version': VERSION,
        'items': items,
        'pending': len(pending),
        'done': len(done),
        'failed': len(failed_items),
        'total': len(items),
        'complete': len(pending) == 0 and len(items) > 0,
        'phase': 'location' if tracks_ready and not person_pending else 'person',
        'stay_points': stay_points,
        'center_set': center_set,
        'coverage': coverage,
        'next': pending[0] if pending else None,
    }


def coverage_appendix(plan):
    """Rows for markdown: 接口覆盖清单."""
    rows = []
    coverage = (plan or {}).get('coverage') or {}
    for kind in ALL_KINDS:
        status = coverage.get(kind, 'pending')
        label = {'done': '已查', 'failed': '失败', 'pending': '未查'}.get(status, status)
        rows.append((KIND_LABELS.get(kind, kind), label))
    return rows


def next_center_source(context, kind):
    """Pick the next pending location center source_ref for incidents/captures."""
    plan = context.get('person_case_plan') or {}
    for item in plan.get('items') or []:
        if item.get('phase') != 'location' or item.get('kind') != kind:
            continue
        if item.get('status') != 'pending':
            continue
        ref = item.get('source_ref')
        if isinstance(ref, dict) and ref.get('record_id'):
            return copy.deepcopy(ref), item
    # Fall back to first center
    for center in context.get('center_set') or []:
        ref = center.get('source_ref')
        if isinstance(ref, dict) and ref.get('record_id'):
            return copy.deepcopy(ref), None
    return None, None
