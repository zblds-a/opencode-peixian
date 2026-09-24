"""Deterministic theft suspicion scoring from already-verified records. Rule theft-score-v1."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

VERSION = 'theft-score-v1'
MAX_POINTS = {'d1': 25, 'd2': 20, 'd3': 15, 'd4': 20, 'd5': 12, 'd6': 8}
LABELS = {
    'd1': 'D1 抓拍频次',
    'd2': 'D2 夜间活动',
    'd3': 'D3 跨区域流动',
    'd4': 'D4 预警关联',
    'd5': 'D5 时空耦合度',
    'd6': 'D6 行为标签',
}
THEFT_TAG = re.compile(r'盗|窃|偷|前科|侵财|两抢|扒窃|入室|盗窃')
PARTIAL_TAG = re.compile(r'夜间|预警|异常|重点|关注|流动|跨')
DISCLAIMER = '排序为辅助研判，需人工核验。'


def _bucket(value, rules, default=0):
    for lo, hi, score in rules:
        if lo <= value <= hi:
            return score
    return default


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
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _parse_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace('Z', '+00:00')
    for fmt in (None, '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            if fmt is None:
                return datetime.fromisoformat(text)
            return datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _module_records(records, module):
    return [r for r in records if r.get('module') == module]


def _dim(key, status, score=None, evidence='', source_ids=None, limitation=''):
    return {
        'id': key,
        'label': LABELS[key],
        'max': MAX_POINTS[key],
        'status': status,
        'score': score if status == 'available' else None,
        'evidence': evidence,
        'source_ids': list(source_ids or []),
        'limitation': limitation,
    }


def subject_of(record, snapshot=None):
    """Return person_ref for a verified record, or None when not person-bound."""
    if not isinstance(record, dict):
        return None
    module = record.get('module')
    fields = record.get('fields') or {}
    if module == 'captures':
        value = fields.get('target_id_card')
        return value if isinstance(value, str) and value else None
    if module == 'profile':
        person = fields.get('person')
        if isinstance(person, dict):
            value = person.get('sfz')
            return value if isinstance(value, str) and value else None
    if module in ('night', 'community', 'warning_detail', 'warnings', 'warning_logs', 'tracks'):
        call_id = record.get('call_id')
        if snapshot and call_id:
            plan = (snapshot.get('native_calls') or {}).get(call_id, {}).get('frozen') or {}
            ref = (plan.get('query') or {}).get('person_ref')
            if isinstance(ref, str) and ref:
                return ref
        for key in ('targetIdCard', 'idCard', 'target_id_card'):
            value = fields.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def group_by_person(records, snapshot=None):
    """Partition records by person_ref. Incidents without a person stay under None."""
    groups = {}
    for record in records or []:
        key = subject_of(record, snapshot)
        groups.setdefault(key, []).append(record)
    return groups


def score_d1(records):
    rows = _module_records(records, 'captures')
    if not rows:
        return _dim('d1', 'unavailable', evidence='未取得周边抓拍汇总', limitation='缺失不计 0')
    total = 0
    sources = []
    for r in rows:
        count = r.get('fields', {}).get('capture_count')
        if type(count) is int and count >= 0:
            total += count
            sources.append(r['record_id'])
    if not sources:
        return _dim('d1', 'unavailable', evidence='抓拍记录缺少抓拍次数', limitation='缺失不计 0')
    score = _bucket(total, ((0, 0, 0), (1, 2, 5), (3, 5, 10), (6, 10, 18), (11, 10**9, 25)))
    return _dim('d1', 'available', score, f'抓拍次数={total}', sources, '抓拍次数不等于到访次数')


def score_d2(records):
    rows = _module_records(records, 'night')
    if not rows:
        return _dim('d2', 'unavailable', evidence='未取得夜间来源记录', limitation='缺失不计 0')
    sources = [r['record_id'] for r in rows]
    n = len(rows)
    score = _bucket(n, ((0, 0, 0), (1, 3, 8), (4, 10, 14), (11, 10**9, 20)))
    return _dim('d2', 'available', score, f'夜间记录数={n}', sources, '来源夜间规则为23:00至次日05:00')


def score_d3(records):
    rows = _module_records(records, 'community')
    if not rows:
        return _dim('d3', 'unavailable', evidence='未取得跨小区来源记录', limitation='缺失不计 0')
    best = 0
    sources = []
    for r in rows:
        count = r.get('fields', {}).get('communityCount')
        if type(count) is int and count >= 0:
            best = max(best, count)
            sources.append(r['record_id'])
    if not sources:
        sources = [r['record_id'] for r in rows]
        best = 0
    score = 0 if best < 4 else _bucket(best, ((4, 6, 8), (7, 10, 12), (11, 10**9, 15)))
    return _dim('d3', 'available', score, f'跨小区数={best}', sources, '来源规则为7至19小时窗口跨4个及以上小区')


def score_d4(records):
    rows = _module_records(records, 'warning_detail') or _module_records(records, 'warnings')
    if not rows:
        return _dim('d4', 'unavailable', evidence='未取得预警概况', limitation='缺失不计 0')
    total = 0
    sources = []
    for r in rows:
        count = r.get('fields', {}).get('warningCount')
        if type(count) is int and count >= 0:
            total = max(total, count)
            sources.append(r['record_id'])
    if not sources:
        return _dim('d4', 'unavailable', evidence='预警记录缺少预警类型数量', limitation='缺失不计 0')
    score = _bucket(total, ((0, 0, 0), (1, 2, 8), (3, 5, 14), (6, 10**9, 20)))
    return _dim('d4', 'available', score, f'预警类型数量={total}', sources, '预警类型数量不是事件次数；未使用来源扣分')


def score_d5(records):
    tracks = _module_records(records, 'tracks')
    incidents = _module_records(records, 'incidents')
    if not tracks or not incidents:
        missing = []
        if not tracks:
            missing.append('轨迹')
        if not incidents:
            missing.append('警情')
        return _dim('d5', 'unavailable', evidence='缺少' + '与'.join(missing), limitation='坐标未兼容确认，仅作参考')
    best_space = None
    best_time = None
    sources = []
    for tr in tracks:
        f = tr.get('fields', {})
        lon, lat = f.get('lon'), f.get('lat')
        t_time = _parse_time(f.get('captureTime'))
        for inc in incidents:
            g = inc.get('fields', {})
            dist = _haversine_m(lon, lat, g.get('gisX'), g.get('gisY'))
            if dist is not None and (best_space is None or dist < best_space[0]):
                best_space = (dist, tr['record_id'], inc['record_id'])
            i_time = _parse_time(g.get('cjsj'))
            if t_time and i_time:
                delta = abs((t_time - i_time).total_seconds())
                if best_time is None or delta < best_time[0]:
                    best_time = (delta, tr['record_id'], inc['record_id'])
    if best_space is None and best_time is None:
        return _dim('d5', 'unavailable', evidence='轨迹或警情缺少可比较的坐标/时间', limitation='坐标未兼容确认，仅作参考')
    space_score = None
    time_score = None
    parts = []
    if best_space is not None:
        dist_m = best_space[0]
        sources.extend(best_space[1:])
        if dist_m > 5000:
            space_score = 0
        elif dist_m > 1000:
            space_score = 3
        elif dist_m >= 500:
            space_score = 5
        else:
            space_score = 8
        parts.append(f'最近直线距离约{int(dist_m)}米→空间{space_score}分')
    if best_time is not None:
        delta = best_time[0]
        sources.extend(best_time[1:])
        hours = delta / 3600.0
        if hours > 24 * 7:
            time_score = 0
        elif hours > 24:
            time_score = 1
        elif hours >= 1:
            time_score = 2
        else:
            time_score = 4
        parts.append(f'最近时间差约{hours:.1f}小时→时间{time_score}分')
    if space_score is None or time_score is None:
        return _dim('d5', 'unavailable', evidence='；'.join(parts) or '时空子维度不完整',
                    source_ids=sorted(set(sources)), limitation='空间与时间子维度均需可计算；坐标未兼容确认')
    score = space_score + time_score
    return _dim('d5', 'available', score, '；'.join(parts), sorted(set(sources)),
                '基于直线距离的粗略估算，非路网距离；不表示到达现场')


def score_d6(records):
    captures = _module_records(records, 'captures')
    profiles = _module_records(records, 'profile')
    if not captures and not profiles:
        return _dim('d6', 'unavailable', evidence='未取得抓拍标签或档案', limitation='缺失不计 0')
    tags = []
    sources = []
    for r in captures:
        value = r.get('fields', {}).get('tags')
        if isinstance(value, str) and value.strip():
            tags.append(value)
            sources.append(r['record_id'])
        elif isinstance(value, list):
            tags.extend(str(x) for x in value if x)
            sources.append(r['record_id'])
    for r in profiles:
        sources.append(r['record_id'])
        for cap in r.get('fields', {}).get('captures') or []:
            if isinstance(cap, dict):
                value = cap.get('tags') or cap.get('xwbq')
                if isinstance(value, str) and value.strip():
                    tags.append(value)
                elif isinstance(value, list):
                    tags.extend(str(x) for x in value if x)
    if not tags:
        return _dim('d6', 'available', 0, '无标签或标签为空', sorted(set(sources)) or [r['record_id'] for r in captures + profiles],
                    '标签是来源行为描述，非已确认前科；未使用来源扣分')
    text = '、'.join(tags)
    if THEFT_TAG.search(text):
        score, note = 8, '标签与侵财/盗窃类表述高度关联'
    elif PARTIAL_TAG.search(text):
        score, note = 5, '标签与警情类别存在部分关联'
    else:
        score, note = 2, '标签与警情类别无明显关联'
    return _dim('d6', 'available', score, f'{note}；标签={text[:120]}', sorted(set(sources)),
                '标签是来源行为描述，非已确认前科；未使用来源扣分')


def band(rate):
    if rate < 20:
        return '关联度较低'
    if rate < 40:
        return '存在一定关联'
    if rate < 60:
        return '关联度中等'
    if rate < 80:
        return '关联度较高'
    return '关联度很高'


_DIM_PLAIN = {
    'd1': '抓拍频次',
    'd2': '夜间活动',
    'd3': '跨小区',
    'd4': '预警',
    'd5': '时空耦合',
    'd6': '行为标签',
}


def _plain_reason(dim):
    """One short plain-language line from a scored dimension."""
    if not dim or dim.get('status') != 'available':
        return None
    evidence = (dim.get('evidence') or '').strip()
    label = dim.get('label') or _DIM_PLAIN.get(dim.get('id'), '')
    if dim.get('id') == 'd1' and '抓拍次数=' in evidence:
        try:
            n = int(evidence.split('抓拍次数=', 1)[1].split('；', 1)[0])
            return f'周边抓拍约{n}次'
        except (ValueError, IndexError):
            pass
    if dim.get('id') == 'd2' and '夜间记录数=' in evidence:
        try:
            n = int(evidence.split('夜间记录数=', 1)[1].split('；', 1)[0])
            return f'有{n}条夜间活动记录'
        except (ValueError, IndexError):
            pass
    if dim.get('id') == 'd3' and '跨小区数=' in evidence:
        try:
            n = int(evidence.split('跨小区数=', 1)[1].split('；', 1)[0])
            return f'跨{n}个小区活动'
        except (ValueError, IndexError):
            pass
    if dim.get('id') == 'd4' and '预警类型数量=' in evidence:
        try:
            n = int(evidence.split('预警类型数量=', 1)[1].split('；', 1)[0])
            return f'预警概况计数{n}'
        except (ValueError, IndexError):
            pass
    if dim.get('id') == 'd6':
        if '高度关联' in evidence:
            return '标签与侵财类表述高度关联'
        if '部分关联' in evidence:
            return '标签与警情类别部分关联'
        if '无明显关联' in evidence or '无标签' in evidence:
            return '标签无明显侵财关联'
    if evidence:
        short = evidence.split('；', 1)[0]
        if len(short) > 40:
            short = short[:40] + '…'
        return f'{label}：{short}' if label else short
    return label or None


def reasons_and_checks(view, records=None, stage='六维'):
    """Top contributing reasons and suggested human checks. Never a crime conclusion."""
    dims = list((view or {}).get('dimensions') or [])
    available = [d for d in dims if d.get('status') == 'available' and isinstance(d.get('score'), (int, float))]
    available.sort(key=lambda d: (-(d.get('score') or 0), d.get('id') or ''))
    reasons = []
    for dim in available[:2]:
        line = _plain_reason(dim)
        if line and line not in reasons:
            reasons.append(line)
    if not reasons and stage == '初排':
        reasons.append('仅依据抓拍频次与标签的初步排序')
    next_checks = []
    gaps = [d for d in dims if d.get('status') != 'available' and d.get('id') != 'd5']
    if stage == '初排':
        next_checks.append('确认核验人数后补查夜间、跨小区、预警与档案')
    else:
        for dim in gaps[:2]:
            label = dim.get('label') or _DIM_PLAIN.get(dim.get('id'), '缺项')
            next_checks.append(f'补齐{label}资料后再比较')
        # Prefer a concrete source-based check when capture rows exist
        for r in records or []:
            if r.get('module') != 'captures':
                continue
            fields = r.get('fields') or {}
            point = fields.get('device_name') or fields.get('capture_address') or fields.get('address')
            when = fields.get('latestTime') or fields.get('timeRangeStart') or fields.get('captureTime')
            parts = []
            if isinstance(point, str) and point.strip():
                parts.append(point.strip()[:30])
            if isinstance(when, str) and when.strip():
                parts.append(when.strip()[:19])
            if parts:
                next_checks.insert(0, '调取' + ' '.join(parts) + '录像核对衣着与同行人')
                break
        if not next_checks:
            next_checks.append('人工核验来源记录与缺口维度')
    # Cap length for table cells
    return reasons[:2], next_checks[:2]


def compute(records, include_d5=True):
    """Score one person's records only. Do not mix subjects."""
    dims = [score_d1(records), score_d2(records), score_d3(records), score_d4(records)]
    if include_d5:
        dims.append(score_d5(records))
    else:
        dims.append(_dim('d5', 'unavailable', evidence='初排阶段不计时空耦合', limitation='仅由人到案深度核验时计算'))
    dims.append(score_d6(records))
    available = [d for d in dims if d['status'] == 'available']
    if len(available) < 3:
        return {
            'version': VERSION,
            'status': 'insufficient',
            'dimensions': dims,
            'available_count': len(available),
            'earned': None,
            'available_max': None,
            'rate': None,
            'band': None,
            'disclaimer': '数据覆盖不足，分值参考意义有限。' + DISCLAIMER,
        }
    earned = sum(d['score'] for d in available)
    available_max = sum(d['max'] for d in available)
    rate = round(earned / available_max * 100, 1) if available_max else 0.0
    return {
        'version': VERSION,
        'status': 'ready',
        'dimensions': dims,
        'available_count': len(available),
        'earned': earned,
        'available_max': available_max,
        'rate': rate,
        'band': band(rate),
        'disclaimer': DISCLAIMER,
    }


def stage1_rank(capture_records):
    """First-pass ranking from capture rows only (D1+D6). Never mixes persons."""
    groups = group_by_person([r for r in capture_records or [] if r.get('module') == 'captures'])
    items = []
    for person_ref, rows in groups.items():
        if not person_ref:
            continue
        view = compute(rows, include_d5=False)
        # Stage-1 uses only D1/D6 even if status is insufficient for full six-dim
        d1 = next(d for d in view['dimensions'] if d['id'] == 'd1')
        d6 = next(d for d in view['dimensions'] if d['id'] == 'd6')
        earned = (d1['score'] or 0) + (d6['score'] or 0)
        available_max = (d1['max'] if d1['status'] == 'available' else 0) + (d6['max'] if d6['status'] == 'available' else 0)
        rate = round(earned / available_max * 100, 1) if available_max else 0.0
        name = None
        for r in rows:
            value = (r.get('fields') or {}).get('target_name')
            if isinstance(value, str) and value.strip():
                name = value
                break
        primary = rows[0]
        stage_view = {'dimensions': [d1, d6], 'status': 'ready'}
        reasons, next_checks = reasons_and_checks(stage_view, rows, stage='初排')
        items.append({
            'person_ref': person_ref,
            'name': name,
            'stage': '初排',
            'rate': rate,
            'earned': earned,
            'available_max': available_max,
            'band': band(rate),
            'available_count': sum(1 for d in (d1, d6) if d['status'] == 'available'),
            'role': '周边抓拍关联',
            'source_ids': [r['record_id'] for r in rows],
            'run_id': primary.get('source_run_id'),
            'record_id': primary.get('record_id'),
            'snapshot_id': primary.get('snapshot_id'),
            'result_digest': primary.get('result_digest'),
            'gaps': [],
            'follow_up': '可确认核验前N名后补查夜间、跨小区、预警与档案',
            'reasons': reasons,
            'next_checks': next_checks,
            'scoring': view,
        })
    items.sort(key=lambda x: (-(x['rate'] or 0), -(x['earned'] or 0), x['person_ref']))
    for index, item in enumerate(items, 1):
        item['rank'] = index
    return {
        'version': VERSION,
        'stage': 'stage1',
        'title': '初步关注排序（仅依据抓拍频次与标签）',
        'status': 'ready' if items else 'empty',
        'items': items,
        'disclaimer': DISCLAIMER,
    }


def rank(records_by_person, include_d5=True):
    """Full six-dimension ranking for an authorized candidate set."""
    items = []
    insufficient = []
    for person_ref, rows in (records_by_person or {}).items():
        if not person_ref:
            continue
        view = compute(rows, include_d5=include_d5)
        name = None
        for r in rows:
            fields = r.get('fields') or {}
            if r.get('module') == 'captures' and isinstance(fields.get('target_name'), str):
                name = fields['target_name']
            person = fields.get('person') if r.get('module') == 'profile' else None
            if isinstance(person, dict) and isinstance(person.get('name'), str):
                name = person['name']
        reasons, next_checks = reasons_and_checks(view, rows, stage='六维')
        entry = {
            'person_ref': person_ref,
            'name': name,
            'stage': '六维',
            'rate': view.get('rate'),
            'earned': view.get('earned'),
            'available_max': view.get('available_max'),
            'band': view.get('band'),
            'available_count': view.get('available_count'),
            'role': '周边抓拍关联',
            'source_ids': [r['record_id'] for r in rows],
            'gaps': [d['label'] + '：' + (d.get('evidence') or '不可用') for d in view['dimensions'] if d['status'] != 'available'],
            'follow_up': '建议人工核验来源记录与缺口维度',
            'reasons': reasons,
            'next_checks': next_checks,
            'scoring': view,
            'status': view['status'],
        }
        if view['status'] == 'ready':
            items.append(entry)
        else:
            insufficient.append(entry)
    items.sort(key=lambda x: (-(x['rate'] or 0), -(x['earned'] or 0), x['person_ref']))
    for index, item in enumerate(items, 1):
        item['rank'] = index
    return {
        'version': VERSION,
        'stage': 'stage2',
        'title': '六维可疑度排序',
        'status': 'ready' if items or insufficient else 'empty',
        'items': items,
        'insufficient': insufficient,
        'disclaimer': DISCLAIMER,
    }


def case_checks(track_records, incident_records):
    """Person-to-case: pairwise track vs incident rows, ranked by space-time coupling."""
    rows = []
    for inc in incident_records or []:
        fields = inc.get('fields') or {}
        cjbh = fields.get('cjbh') or fields.get('jjbh') or '未提供编号'
        cjsj = fields.get('cjsj') or '未提供处警时间'
        best_dist = None
        best_delta = None
        best_track = None
        sources = [inc['record_id']]
        for tr in track_records or []:
            tf = tr.get('fields') or {}
            dist = _haversine_m(tf.get('lon'), tf.get('lat'), fields.get('gisX'), fields.get('gisY'))
            t_time = _parse_time(tf.get('captureTime'))
            i_time = _parse_time(fields.get('cjsj')) or _parse_time(fields.get('sfsjsx'))
            delta = abs((t_time - i_time).total_seconds()) if t_time and i_time else None
            # Prefer joint space-time: distance within 1000m and time within 24h
            better = False
            if dist is not None and delta is not None:
                if best_dist is None or best_delta is None:
                    better = True
                else:
                    # lower combined rank score is better
                    cur = (dist / 100.0) + (delta / 3600.0)
                    prev = (best_dist / 100.0) + (best_delta / 3600.0)
                    better = cur < prev
            elif dist is not None and (best_dist is None or (best_delta is None and dist < best_dist)):
                better = best_delta is None
            if better:
                best_dist = dist if dist is not None else best_dist
                best_delta = delta if delta is not None else best_delta
                best_track = tr
                sources = [inc['record_id'], tr['record_id']]
            elif dist is not None and (best_dist is None or dist < best_dist) and best_delta is None:
                best_dist = dist
                best_track = tr
                sources.append(tr['record_id'])
            if delta is not None and (best_delta is None or delta < best_delta) and best_dist is None:
                best_delta = delta
                sources.append(tr['record_id'])
        hours = None if best_delta is None else round(best_delta / 3600.0, 1)
        dist_m = None if best_dist is None else int(best_dist)
        if dist_m is not None and hours is not None and dist_m <= 500 and hours <= 6:
            grade, relation = '时空同现较强', '轨迹与警情在较短时空窗口内接近'
        elif dist_m is not None and hours is not None and dist_m <= 1000 and hours <= 24:
            grade, relation = '时空接近', '轨迹与警情存在可计算的时空接近'
        elif dist_m is not None and dist_m <= 500 and hours is None:
            grade, relation = '仅地点接近', '仅有空间接近，缺少可对齐的时间'
        elif hours is not None and hours <= 6 and (dist_m is None or dist_m > 1000):
            grade, relation = '仅时间接近', '仅有时间接近，空间距离较大或不可算'
        elif dist_m is not None or hours is not None:
            grade, relation = '时空不吻合', '可计算但超出常用同现窗口，降权参考'
        else:
            grade, relation = '无可计算联系', '尚无可计算的时空联系'
        place = ''
        when = ''
        if best_track:
            tf = best_track.get('fields') or {}
            place = tf.get('deviceName') or tf.get('localAddress') or ''
            when = tf.get('captureTime') or ''
        next_checks = []
        if place or when:
            next_checks.append('调取' + ' '.join(x for x in (str(place)[:30], str(when)[:19]) if x) + '录像核对衣着与同行人')
        next_checks.append('核对处警记录原文与现场情况，不得直接认定为涉案')
        rows.append({
            'cjbh': str(cjbh),
            'cjsj': str(cjsj),
            'distance_m': dist_m,
            'time_delta_hours': hours,
            'grade': grade,
            'relation': relation,
            'status': '待核验',
            'follow_up': next_checks[0],
            'reasons': [relation] + ([f'最近约{dist_m}米'] if dist_m is not None else []) + ([f'时间差约{hours}小时'] if hours is not None else []),
            'next_checks': next_checks[:2],
            'source_ids': sorted(set(sources)),
        })
    # Rank: stronger grades first, then closer distance, then smaller time delta
    grade_rank = {'时空同现较强': 0, '时空接近': 1, '仅地点接近': 2, '仅时间接近': 3, '时空不吻合': 4, '无可计算联系': 5}
    rows.sort(key=lambda r: (
        grade_rank.get(r.get('grade'), 9),
        r['distance_m'] if r.get('distance_m') is not None else 10**9,
        r['time_delta_hours'] if r.get('time_delta_hours') is not None else 10**9,
        r.get('cjbh') or '',
    ))
    return {
        'version': VERSION,
        'status': 'ready' if rows else 'empty',
        'items': rows,
        'disclaimer': '候选案件状态为待核验；时空接近不等于涉案认定，需人工核验。',
    }
