"""Turn clarifiable native-tool precheck failures into structured question specs.

Confirmed conditions still come only from validated user answers. The model must
raise the question as given; the reply proxy merges selected values into the
frozen native_tool_context before forwarding to the agent.
"""
import copy
import re
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException

from .backend_contract import error
from .native_tool_scope import FIELD_NAMES, canonical_field
from .theft_planner import slots

CLARIFIABLE = frozenset({
    'scope_missing', 'scope_unconfirmed', 'scope_parameter_invalid',
    'capture_scope_unconfirmed',
    'source_selection_required', 'explicit_source_required', 'source_selection_limit',
    'unsupported_scope',
    'page_unconfirmed',
    'identity_unconfirmed', 'identity_parameter_invalid',
})

FIELD_HEADERS = {
    'person_identity': '核对对象',
    'lon': '查询位置',
    'lat': '查询位置',
    'radius_m': '查询范围',
    'start': '开始时间',
    'end': '结束时间',
    'page': '页码',
    'page_size': '每页数量',
    'source': '来源记录',
    'supported_scope': '查询范围限制',
}

FIELD_QUESTIONS = {
    'person_identity': '请提供本次要核对的一名人员身份号码。',
    'lon': '请提供已确认位置的经度。',
    'lat': '请提供已确认位置的纬度。',
    'radius_m': '请提供查询半径，单位为米。',
    'start': '请提供开始时间，格式为 YYYY-MM-DD HH:mm:ss。',
    'end': '请提供结束时间，格式为 YYYY-MM-DD HH:mm:ss。',
    'page': '请说明要查询第几页；不会自动翻页。',
    'page_size': '请说明每页查询多少条。',
    'source': '请选择一条已取得的位置来源记录。不会自动选择第一条。',
    'supported_scope': '当前警情接口不能按“近期”或“仅盗窃”筛选。是否同意改用上游默认覆盖范围？',
}

RADIUS_OPTIONS = [
    ('半径 300 米', 300),
    ('半径 500 米', 500),
    ('半径 1000 米', 1000),
]
PAGE_SIZE_OPTIONS = [
    ('每页 10 条', 10),
    ('每页 20 条', 20),
]
CAPTURE_WINDOWS = (1, 2, 6)


def is_clarifiable(code):
    return code in CLARIFIABLE


def detail_of(exc):
    detail = getattr(exc, 'detail', None)
    if isinstance(detail, dict) and isinstance(detail.get('code'), str):
        return detail
    return None


def _token():
    return uuid.uuid4().hex[:24]


def _label_options(pairs):
    return [{'label': label, 'description': ''} for label, _ in pairs], {label: value for label, value in pairs}


def _parse_cjsj(value):
    if not isinstance(value, str):
        return None
    text = value.strip().replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(text[:19] if fmt.endswith('%S') else text[:16], fmt)
        except ValueError:
            continue
    return None


def list_spatial_sources(store, uid, sid, limit=5, task_id=None):
    """Incidents/tracks already obtained in this session, newest first."""
    from . import trusted_results
    found = []
    for row in store.rows(
        "SELECT id,status FROM business_runs WHERE uid=? AND session_id=? ORDER BY rowid DESC LIMIT 50",
        (uid, sid),
    ):
        try:
            from .live_sources import projection, reference
            result = projection(store, uid, sid, row['id'])
        except HTTPException:
            continue
        if result.get('data_environment') != 'acceptance_real':
            continue
        if task_id and result.get('versions', {}).get('task_id') != task_id:
            continue
        digest = trusted_results.digest(result)
        for index, record in enumerate(result.get('records') or [], 1):
            if record.get('module') not in ('incidents', 'tracks'):
                continue
            fields = record.get('fields') or {}
            if record['module'] == 'incidents':
                when = fields.get('cjsj') or '时间未提供'
                where = fields.get('cjxz') or fields.get('bzdzmc') or fields.get('cjmlph') or '地址未提供'
                title = f"警情位置{len(found)+1} · {where} · {when}"
            else:
                when = fields.get('captureTime') or fields.get('time') or '时间未提供'
                where = f"{fields.get('lon', '?')},{fields.get('lat', '?')}"
                title = f"来源{index} · 轨迹点 {where} · {when}"
            ref = reference(result,record) if record.get('call_id') else {
                'run_id':row['id'],'result_digest':digest,
                'record_id':record['record_id'],'snapshot_id':record['snapshot_id']}
            found.append({
                'label': title,
                'ref': ref,
                'cjsj': fields.get('cjsj') or fields.get('captureTime'),
                'module': record['module'],
            })
            if len(found) >= limit:
                return found
    return found


def capture_time_presets(anchor):
    """Concrete windows around a source handling time."""
    center = _parse_cjsj(anchor)
    if not center:
        return [], {}
    pairs = []
    for hours in CAPTURE_WINDOWS:
        start = (center - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
        end = (center + timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
        label = f'处警前后各{hours}小时（{start} 至 {end}）'
        pairs.append((label, {'start': start, 'end': end}))
    return _label_options(pairs)


def _field_question(field, options=None, custom=True, question=None):
    return {
        'field': field,
        'header': FIELD_HEADERS.get(field, '补充信息'),
        'question': question or FIELD_QUESTIONS.get(field, '请补充本次查询所需的信息。'),
        'options': list(options or []),
        'custom': custom,
    }


def build(kind, code, field_errors, context, store, uid, sid):
    """Build a pending question spec for a clarifiable precheck failure."""
    if code not in CLARIFIABLE:
        return None
    questions = []
    values = {}
    fields = []

    if code == 'unsupported_scope':
        label = '同意使用上游默认覆盖范围'
        questions.append(_field_question(
            'supported_scope',
            options=[{'label': label, 'description': '仍按已确认的坐标、半径和页码查询；不附加近期或警情类别过滤。'},
                     {'label': '取消本次查询', 'description': '不发起资料调用。'}],
            custom=False,
        ))
        values[label] = {'supported_scope': True}
        values['取消本次查询'] = {'cancel': True}
        fields = ['supported_scope']
    elif code in ('source_selection_required', 'explicit_source_required', 'source_selection_limit'):
        sources = list_spatial_sources(store, uid, sid, task_id=context.get('task_id'))
        if not sources:
            questions.extend([_field_question('lon', question='当前没有可选的位置记录，请提供本次查询位置的经度。'),
                              _field_question('lat', question='请提供同一位置的纬度；不支持仅凭地名自动转换坐标。')])
            fields = ['lon','lat']
        else:
            options = [{'label': item['label'], 'description': '使用该记录坐标作为抓拍位置来源。'} for item in sources]
            questions.append(_field_question('source', options=options, custom=False))
            for item in sources:
                values[item['label']] = {'source_ref': item['ref']}
            fields = ['source']
    elif code == 'capture_scope_unconfirmed':
        refs = context.get('source_refs') or []
        anchor = None
        if len(refs) == 1:
            sources = list_spatial_sources(store, uid, sid, limit=20)
            match = next((s for s in sources if s['ref']['record_id'] == refs[0].get('record_id')), None)
            anchor = (match or {}).get('cjsj')
        time_options, time_values = capture_time_presets(anchor)
        values.update(time_values)
        questions.append(_field_question(
            'start',
            options=time_options,
            custom=True,
            question=('请确认本次抓拍时间窗口。可选择基于已选来源处警时间的预设，或自行填写开始与结束时间。'
                      if time_options else
                      '请确认本次抓拍时间窗口，格式为开始时间与结束时间，精确到秒。'),
        ))
        # Combine start+end into one question via presets; free text must include both.
        questions[-1]['field'] = 'time_window'
        questions[-1]['header'] = '抓拍时间'
        radius_options, radius_values = _label_options(RADIUS_OPTIONS)
        values.update(radius_values)
        questions.append(_field_question('radius_m', options=radius_options, custom=True))
        fields = ['start', 'end', 'radius_m']
    elif code == 'page_unconfirmed':
        questions.append(_field_question(
            'page',
            options=[{'label': '第2页', 'description': ''}, {'label': '第3页', 'description': ''}],
            custom=True,
        ))
        values['第2页'] = 2
        values['第3页'] = 3
        fields = ['page']
    elif code in ('identity_unconfirmed', 'identity_parameter_invalid'):
        questions.append(_field_question('person_identity', options=[], custom=True))
        fields = ['person_identity']
    else:
        # scope_missing / scope_unconfirmed / scope_parameter_invalid
        asked = [k for k in ('person_identity', 'lon', 'lat', 'radius_m', 'start', 'end', 'page', 'page_size')
                 if k in (field_errors or {})]
        if not asked:
            asked = ['start', 'end', 'radius_m'] if kind == 'captures' else ['person_identity']
        # Collapse start+end into one time question when both missing.
        if 'start' in asked and 'end' in asked:
            asked = [k for k in asked if k not in ('start', 'end')]
            questions.append(_field_question(
                'time_window',
                options=[],
                custom=True,
                question='请提供开始时间与结束时间，格式为 YYYY-MM-DD HH:mm:ss。',
            ))
            questions[-1]['header'] = '时间窗口'
            fields.extend(['start', 'end'])
        for field in asked:
            if field == 'radius_m':
                options, mapped = _label_options(RADIUS_OPTIONS)
                values.update(mapped)
                questions.append(_field_question(field, options=options, custom=True))
            elif field == 'page_size':
                options, mapped = _label_options(PAGE_SIZE_OPTIONS)
                values.update(mapped)
                questions.append(_field_question(field, options=options, custom=True))
            elif field == 'page':
                questions.append(_field_question(field, options=[{'label': '第1页', 'description': ''}], custom=True))
                values['第1页'] = 1
            else:
                questions.append(_field_question(field, options=[], custom=True))
            fields.append(field)

    if not questions:
        return None
    return {
        'token': _token(),
        'kind': kind,
        'code': code,
        'status': 'pending',
        'scope_version': context.get('scope_version'),
        'task_id': context.get('task_id'),
        'fields': list(dict.fromkeys(fields)),
        'questions': questions,
        'values': values,
    }


def public(spec):
    """Payload for the model / UI. No option values or source refs."""
    if not spec:
        return None
    return {
        'id': spec['token'],
        'kind': spec.get('kind'),
        'code': spec.get('code'),
        'questions': [{
            'header': q['header'],
            'question': q['question'],
            'options': [{'label': o['label'], **({'description': o['description']} if o.get('description') else {})}
                        for o in (q.get('options') or [])],
            'custom': q.get('custom', True),
            'multiple': False,
        } for q in spec.get('questions') or []],
    }


def match_public(spec, asked):
    """True when the live question card matches this pending public() form."""
    expected = public(spec)
    if not expected or not isinstance(asked, list):
        return False
    if len(expected['questions']) != len(asked):
        return False
    for left, right in zip(expected['questions'], asked):
        if not isinstance(right, dict):
            return False
        if left['header'] != right.get('header'):
            return False
        left_labels = [o['label'] for o in left.get('options') or []]
        right_labels = [o.get('label') for o in (right.get('options') or [])]
        if left_labels != right_labels:
            return False
        if bool(left.get('custom', True)) != bool(right.get('custom', True)):
            return False
    return True


def _resolve_answer(question, answer_labels, values):
    """Map one question's selected labels / free text into field updates."""
    if isinstance(answer_labels, list) and len(answer_labels)>1:
        error('too_many_answers', '此题只能选择一个答案。', 422)
    if not isinstance(answer_labels, list) or len(answer_labels) != 1:
        error('clarification_incomplete', '请回答全部问题。', 422)
    label = answer_labels[0]
    if not isinstance(label, str) or not label.strip():
        error('clarification_incomplete', '请回答全部问题。', 422)
    label = label.strip()
    field = question.get('field')
    option_labels = {o['label'] for o in (question.get('options') or [])}

    if label in option_labels and label in values:
        mapped = values[label]
        if isinstance(mapped, dict):
            return copy.deepcopy(mapped)
        if field == 'time_window':
            error('clarification_invalid', '时间选项无效。', 422)
        if field in ('radius_m', 'page', 'page_size', 'lon', 'lat', 'start', 'end'):
            return {field: canonical_field(field, mapped)}
        return {field: mapped}

    # Free text
    if question.get('custom') is False:
        error('clarification_invalid', '请选择给出的选项。', 422)
    if field == 'supported_scope':
        error('clarification_invalid', '请明确是否同意使用上游默认覆盖范围。', 422)
    if field == 'source':
        # Accept a raw record_id only when no options were offered.
        if option_labels:
            error('clarification_invalid', '请从列表中选择一条来源记录。', 422)
        error('clarification_invalid', '请先完成周边警情或轨迹查询后再选择来源。', 422)
    if field == 'time_window':
        parsed = {v['field']: v['value'] for v in slots(label).values()}
        if not {'start', 'end'} <= set(parsed):
            error('clarification_invalid', '请同时提供开始时间与结束时间，格式为 YYYY-MM-DD HH:mm:ss。', 422)
        return {'start': canonical_field('start', parsed['start']),
                'end': canonical_field('end', parsed['end'])}
    if field == 'page' and re.fullmatch(r'第?\s*\d+\s*页?', label):
        number = int(re.search(r'\d+', label).group())
        return {'page': canonical_field('page', number)}
    if field == 'page_size' and re.search(r'\d+', label):
        number = int(re.search(r'\d+', label).group())
        return {'page_size': canonical_field('page_size', number)}
    if field == 'radius_m' and re.search(r'\d+', label):
        number = int(re.search(r'\d+', label).group())
        unit = '公里' if '公里' in label or '千米' in label else '米'
        if unit != '米':
            number *= 1000
        return {'radius_m': canonical_field('radius_m', number)}
    if field == 'person_identity':
        parsed = {v['field']: v['value'] for v in slots(label).values()}
        if 'person_identity' not in parsed:
            error('clarification_invalid', '请填写一名人员的完整身份号码。', 422)
        return {'person_identity': parsed['person_identity']}
    if field in ('lon', 'lat', 'start', 'end'):
        parsed = {v['field']: v['value'] for v in slots(
            ({'lon': '经度', 'lat': '纬度', 'start': '开始时间', 'end': '结束时间'}[field] + ' ' + label)
        ).values()}
        if field not in parsed:
            # Try raw value for lon/lat/time
            try:
                return {field: canonical_field(field, label)}
            except HTTPException:
                error('clarification_invalid', FIELD_NAMES.get(field, field) + '格式不符合要求。', 422)
        return {field: canonical_field(field, parsed[field])}
    error('clarification_invalid', '无法识别本次回答，请按提示重新填写。', 422)


def apply_reply(spec, answers, context, store=None, uid=None, sid=None):
    """Validate answers and merge into a copy of native_tool_context."""
    if not spec or spec.get('status') not in (None, 'pending'):
        error('clarification_changed', '待补充信息已变化。', 409)
    if spec.get('scope_version') is not None and (spec['scope_version'] != context.get('scope_version') or spec.get('task_id') != context.get('task_id')):
        error('clarification_changed', '本次条件已变化，请回答最新问题。', 409)
    questions = spec.get('questions') or []
    if not isinstance(answers, list) or len(answers) != len(questions):
        error('clarification_incomplete', '请回答全部问题。', 422)
    updates = {}
    source_ref = None
    cancel = False
    literals = []
    for question, answer in zip(questions, answers):
        piece = _resolve_answer(question, answer, spec.get('values') or {})
        if piece.get('cancel'):
            cancel = True
            literals.append('取消本次查询')
            continue
        if piece.get('supported_scope'):
            updates['supported_scope'] = True
            literals.append('同意使用上游默认覆盖范围')
            continue
        if 'source_ref' in piece:
            source_ref = piece['source_ref']
            literals.append(answer[0].strip())
            continue
        for key, value in piece.items():
            updates[key] = value
            if key in ('start', 'end'):
                literals.append(('开始时间' if key == 'start' else '结束时间') + '：' + str(value))
            elif key == 'radius_m':
                literals.append('半径：' + str(value) + ' 米')
            elif key == 'page':
                literals.append('第' + str(value) + '页')
            elif key == 'page_size':
                literals.append('每页' + str(value) + '条')
            elif key == 'person_identity':
                literals.append('人员：' + str(value))
            else:
                literals.append(str(FIELD_NAMES.get(key, key)) + '：' + str(value))

    if cancel:
        # User declined — leave context unchanged but mark answered.
        next_context = copy.deepcopy(context)
        return next_context, '取消本次查询', True

    # Only fields this question asked for.
    allowed = set(spec.get('fields') or [])
    if updates.get('supported_scope'):
        allowed.add('supported_scope')
    unexpected = set(updates) - allowed - {'supported_scope'}
    if unexpected:
        error('clarification_invalid', '回答包含本次未询问的字段。', 422)

    next_context = copy.deepcopy(context)
    confirmed = next_context.setdefault('confirmed', {})
    user_conditions = next_context.setdefault('user_conditions', {})
    for key, value in updates.items():
        if key == 'supported_scope':
            continue
        confirmed[key] = value
        user_conditions[key] = value
    if spec.get('kind') == 'captures':
        next_context.setdefault('capture_conditions',{}).update({k:v for k,v in updates.items() if k in ('start','end','radius_m')})
    if spec.get('kind') == 'captures' and {'lon','lat'} <= updates.keys():
        next_context['capture_position_confirmed'] = True
        next_context['source_refs'] = []
    if updates.get('supported_scope'):
        next_context['constraints_text'] = ''
    if source_ref is not None:
        if store is not None:
            from .analysis_tasks import source
            source(store, uid, sid, source_ref, 'acceptance_real')
        next_context['source_refs'] = [copy.deepcopy(source_ref)]
    next_context['scope_version'] = int(next_context.get('scope_version') or 0) + 1
    text = '；'.join(literals)
    if text:
        next_context['current_text'] = ((next_context.get('current_text') or '') + ' ' + text).strip()[-12000:]
        if not updates.get('supported_scope'):
            next_context['constraints_text'] = ((next_context.get('constraints_text') or '') + ' ' + text).strip()[-12000:]
    return next_context, text or '已确认', False


def find_pending(snapshot, asked_questions):
    """Return the pending spec that matches the live question card, if any."""
    pending = snapshot.get('native_pending_questions') or {}
    for token, spec in pending.items():
        if not isinstance(spec, dict) or spec.get('status') != 'pending':
            continue
        if match_public(spec, asked_questions):
            return token, spec
    return None, None


def record_pending(snapshot, spec, max_keep=3):
    """Persist a new pending question; supersede older ones beyond the cap."""
    pending = snapshot.setdefault('native_pending_questions', {})
    active = [(t, s) for t, s in pending.items() if isinstance(s, dict) and s.get('status') == 'pending']
    while len(active) >= max_keep:
        old_token, old = active.pop(0)
        old['status'] = 'superseded'
    pending[spec['token']] = spec
    return spec['token']


def kind_question_count(snapshot, kind):
    pending = snapshot.get('native_pending_questions') or {}
    return sum(1 for s in pending.values()
               if isinstance(s, dict) and s.get('kind') == kind and s.get('status') in ('pending', 'answered'))
