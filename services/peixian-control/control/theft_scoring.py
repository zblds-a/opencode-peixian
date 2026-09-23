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
    item = {
        'id': key,
        'label': LABELS[key],
        'max': MAX_POINTS[key],
        'status': status,
        'score': score if status == 'available' else None,
        'evidence': evidence,
        'source_ids': list(source_ids or []),
        'limitation': limitation,
    }
    return item


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
        return _dim('d1', 'unavailable', evidence='抓拍记录缺少 capture_count', limitation='缺失不计 0')
    score = _bucket(total, ((0, 0, 0), (1, 2, 5), (3, 5, 10), (6, 10, 18), (11, 10**9, 25)))
    return _dim('d1', 'available', score, f'capture_count={total}', sources, '抓拍次数不等于到访次数')


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
        # list presence without communityCount still counts as available with 0
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
        return _dim('d4', 'unavailable', evidence='预警记录缺少 warningCount', limitation='缺失不计 0')
    score = _bucket(total, ((0, 0, 0), (1, 2, 8), (3, 5, 14), (6, 10**9, 20)))
    return _dim('d4', 'available', score, f'warningCount={total}', sources, '预警类型数量不是事件次数；未使用 deductScore')


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
    # If one sub-dimension missing, mark whole D5 unavailable per "无法计算标记不可用"
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
        # profile/captures present but empty tags → available 0
        return _dim('d6', 'available', 0, '无标签或标签为空', sorted(set(sources)) or [r['record_id'] for r in captures + profiles],
                    '标签是来源行为描述，非已确认前科；未使用 deductScore')
    text = '、'.join(tags)
    if THEFT_TAG.search(text):
        score, note = 8, '标签与侵财/盗窃类表述高度关联'
    elif PARTIAL_TAG.search(text):
        score, note = 5, '标签与警情类别存在部分关联'
    else:
        score, note = 2, '标签与警情类别无明显关联'
    return _dim('d6', 'available', score, f'{note}；tags={text[:120]}', sorted(set(sources)),
                '标签是来源行为描述，非已确认前科；未使用 deductScore')


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


def compute(records):
    """Return a scoring view from already-filtered person records. Pure function."""
    dimensions = [score_d1(records), score_d2(records), score_d3(records),
                  score_d4(records), score_d5(records), score_d6(records)]
    available = [d for d in dimensions if d['status'] == 'available']
    if len(available) < 3:
        return {
            'version': VERSION,
            'status': 'insufficient',
            'dimensions': dimensions,
            'available_count': len(available),
            'earned': None,
            'available_max': None,
            'rate': None,
            'band': None,
            'disclaimer': '数据覆盖不足，分值参考意义有限。不构成犯罪认定，可由民警人工修正。',
        }
    earned = sum(d['score'] for d in available)
    available_max = sum(d['max'] for d in available)
    rate = round(earned / available_max * 100, 1) if available_max else 0.0
    return {
        'version': VERSION,
        'status': 'ready',
        'dimensions': dimensions,
        'available_count': len(available),
        'earned': earned,
        'available_max': available_max,
        'rate': rate,
        'band': band(rate),
        'disclaimer': '本评估为辅助参考，不构成犯罪认定，可由民警人工修正。',
    }
