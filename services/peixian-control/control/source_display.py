"""Readable source labels and bounded, code-owned follow-up suggestions."""
from datetime import datetime

LABELS = {'funds': '资金流水记录', 'trajectory': '夜间观测记录', 'companion': '明确同行记录',
          'vehicle': '车辆记录', 'place': '地点来源记录', 'relation': '已有关系记录'}


def source(kind, record, synthetic=True):
    at = record.get('occurred_at'); shown = '时间未提供'
    if isinstance(at, str):
        try:
            value = datetime.fromisoformat(at.replace('Z', '+00:00'))
            if value.tzinfo is not None:
                from datetime import timezone, timedelta
                shown = value.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
            else:
                at = None
        except ValueError:
            at = None
    title = LABELS.get(kind, '来源记录')
    description = '本轮已取得的' + title + '，仅说明该条资料中的记录。'
    if kind == 'funds' and type(record.get('amount_minor')) is int:
        amount = record['amount_minor']; sign = '-' if amount < 0 else ''; amount = abs(amount)
        direction = {'in': '收入', 'out': '支出', 'income': '收入', 'expense': '支出', 'credit': '收入', 'debit': '支出'}.get(record.get('direction'), '收支方向未明确')
        description = f'原始流水：{direction}，{sign}{amount // 100}.{amount % 100:02d}元；不合并双边记录，不据此推断资金用途。'
    return {'type': kind, 'label': title + ' · ' + shown, 'content': description,
            'record_id': record['record_id'], 'source_ids': [record['record_id']],
            'occurred_at': at, 'synthetic': synthetic, 'verification_status': 'source_verified'}


def complete(view):
    """Only invoked on a newly built, trusted view, never on assistant prose."""
    gaps = view.get('missing_details', [])
    recommendations = []
    for category in ('source_missing', 'verification_pending', 'scope_limit'):
        related = [g for g in gaps if g['category'] == category]
        if not related:
            continue
        text = {'source_missing': '先补齐未取得的资料，再核对相关问题。',
                'verification_pending': '请先核对未完成步骤和对应来源，暂不采用未核对内容形成结论。',
                'scope_limit': '如需扩大时间或对象范围，请先确认资料接口支持；当前结论仅适用于已注明范围。'}[category]
        recommendations.append({'id': 'next-' + category, 'type': 'manual_review' if category == 'verification_pending' else 'request_information',
                                'text': text, 'gap_refs': [g['id'] for g in related], 'source_ids': [], 'actionable': False})
    view['recommendations'] = recommendations
    view['next_steps_status'] = 'available' if recommendations else 'no_verified_suggestion'
    view['next_steps'] = '\n'.join('- ' + r['text'] for r in recommendations)
    lines = []
    if view.get('conclusions'):
        lines += ['### 已核对结果'] + ['- ' + c['text'] for c in view['conclusions'][:5]]
    if view.get('clues'):
        lines += ['', '### 来源依据']
        for clue in view['clues']:
            for item in clue.get('evidence', [])[:3]:
                lines.append('- ' + item['label'] + '：' + item['content'])
    if gaps:
        lines += ['', '### 资料范围与待核对项'] + ['- ' + g['text'] for g in gaps]
    if recommendations:
        lines += ['', '### 下一步建议', view['next_steps']]
    view['public_markdown'] = '\n'.join(lines).strip()
    return view


def describe(kind, title, headline, rows, window, limitations):
    """Bounded statistics over this projection's verified rows only."""
    from datetime import timezone, timedelta
    refs=list(dict.fromkeys(row['record_id'] for row in rows))
    details=[]
    def add(text, sources, category='metric'):
        details.append({'text':text,'source_ids':list(dict.fromkeys(sources)),'category':category})
    add(f'本次取得 {len(rows)} 条原始记录，保留各条来源，不按时间接近或金额相似合并。',refs)
    times=[]
    for row in rows:
        try:
            raw=row.get('occurred_at')
            if not isinstance(raw,str):continue
            at=datetime.fromisoformat(raw.replace('Z','+00:00'))
            if at.tzinfo is not None:times.append((at.astimezone(timezone(timedelta(hours=8))),row['record_id']))
        except (TypeError,ValueError):pass
    if times:
        dates={at.date() for at,_ in times}
        start=min(at for at,_ in times).strftime('%Y-%m-%d %H:%M')
        end=max(at for at,_ in times).strftime('%Y-%m-%d %H:%M')
        add(f'有明确时间的记录涉及 {len(dates)} 个北京时间自然日；记录时间从 {start} 至 {end}。',[ref for _,ref in times])
    if kind=='funds':
        labels={'in':'收入','income':'收入','out':'支出','expense':'支出','credit':'收入','debit':'支出'}
        incoming=[x['record_id'] for x in rows if labels.get(x.get('direction'))=='收入']
        outgoing=[x['record_id'] for x in rows if labels.get(x.get('direction'))=='支出']
        add(f'按原始收支字段：收入 {len(incoming)} 条、支出 {len(outgoing)} 条；方向未明确 {len(rows)-len(incoming)-len(outgoing)} 条。',refs)
    elif kind=='companion':
        add(f'此处仅列明确同行记录；同框、同乘不自动并入同行统计。',refs,'limitation')
    elif kind=='vehicle':
        vehicles={x['group_ref'] for x in rows if isinstance(x.get('group_ref'),str)}
        add(f'原始记录涉及 {len(vehicles)} 个去重车辆标识；记录关联不表示同乘。',refs)
    elif kind=='trajectory' and times:
        nights=[ref for at,ref in times if at.hour>=22 or at.hour<6]
        add(f'北京时间22:00至次日06:00口径内有 {len(nights)} 条记录。',[ref for _,ref in times])
    for text in limitations[:1]:add(text,[],'limitation')
    details=details[:4]
    summary='观察范围：'+window+'。'+headline
    if times:summary+=f'有明确时间的资料覆盖 {len({at.date() for at,_ in times})} 个自然日。'
    if len(times)!=len(rows):summary+=f'其中 {len(rows)-len(times)} 条记录未提供可核对的带时区时间。'
    return {'headline':headline,'summary':summary,'discoveries':[x['text'] for x in details],'discovery_details':details}
