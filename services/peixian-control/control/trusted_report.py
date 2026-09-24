"""Reports project the stored Result V2; no model or data queries."""
import html
import json
from .trusted_results import digest

USAGE = {
    'not_started': '尚未发起资料查询', 'in_flight': '资料查询处理中',
    'confirmed': '本轮已取得资料', 'partial': '本轮仅取得部分资料',
    'reused_current_run': '复用本轮已取得资料',
    'historical_evidence': '使用历史可信结果，未重新查询',
    'unknown': '请求可能已发出，但结果未确认，不会自动重试',
    'rejected': '资料暂不可采用', 'cancelled': '查询已取消或未发起',
}
NARRATIVE = {'verified': '已通过冲突检查', 'unverified': '尚未通过核验，仅作辅助说明',
             'conflicted': '存在冲突，未作为可信结论', 'not_generated': '尚未生成'}


def sections(result, events, reviews=()):
    legacy = result.get('version') == 'legacy'
    agent, task = result.get('agent', {}), result.get('task', {})
    meta = [
        '报告编号：' + result['run_id'],
        '结果结构：' + ('Legacy 历史结果；未转换为可信 Claim' if legacy else 'Result V2'),
        '生成时间：' + (result.get('generated_at') or '历史结果未提供'),
        '结果摘要 SHA256：' + digest(result),
    ]
    if not legacy:
        meta += ['Agent：' + agent.get('id', '未提供'), 'Agent 版本：' + agent.get('version', '未提供'),
                 '任务：' + json.dumps(task, ensure_ascii=False, sort_keys=True),
                 '数据环境：' + result.get('data_environment', '未知'),
                 '数据使用：' + USAGE.get(result.get('data_usage', {}).get('status'), '状态无法确认'),
                 ('资料性质：已取得的来源资料。')]
    claims = result.get('claims', [])
    groups = [('报告信息', meta)]
    for title, kind in [('已核验事实', 'fact'), ('确定性计算', 'computed'), ('资料缺口', 'gap')]:
        values = [c['statement'] + '【Claim：' + c['claim_id'] + '；来源：' + ('、'.join(c['source_ids']) or '资料缺口') + '】'
                  for c in claims if c['type'] == kind and c['verification_status'] == 'approved']
        if kind == 'gap': values = list(dict.fromkeys(values + result.get('missing', [])))
        groups.append((title, values or ['当前结果未提供；不能解释为没有发生。']))
    groups.append(('待核验来源记录', [json.dumps(x, ensure_ascii=False, sort_keys=True) for x in result.get('records', [])] or ['未提供来源记录。']))
    narrative = result.get('narrative', {})
    if 'answer' in result:
        answer=result['answer']
        if answer.get('version')=='controlled-zh-v1':
            groups.append(('中文事实说明', [answer['summary']]+[x['text']+'【Claim：'+x['claim_id']+'；来源：'+('、'.join(x['source_ids']) or '本次查询统计')+'】' for x in answer['items']]))
            groups.append(('可以继续',answer['next_steps']))
        else:groups.append(('中文事实说明',['当前说明版本暂不受支持，请查看已核验事实。']))
    else:
        groups.append(('模型辅助说明', [NARRATIVE.get(narrative.get('status'), '旧结构，未执行可信说明核验'), narrative.get('text') or '未提供模型说明。'] + [x['message'] for x in narrative.get('conflicts', [])]))
    groups.append(('来源与执行过程', [json.dumps(result.get('versions', {}), ensure_ascii=False, sort_keys=True)] + [e['name'] + '：' + {'completed':'已完成','failed':'失败','rejected':'已拒绝','cancelled':'已取消','running':'执行中','pending':'等待处理'}.get(e['status'], '状态待确认') for e in events]))
    if reviews:
        groups.append(('人工复核意见（不修改原事实）', [r['created_at']+'；'+r['reviewer']+'；'+r['status_label']+'；'+r['note']+'；引用：'+(', '.join(r['claim_ids']+[x['record_id']+'@'+x['snapshot_id'] for x in r.get('record_refs',[])]) or '历史整轮意见')+'；更正记录：'+(r.get('supersedes') or '无') for r in reviews]))
    return groups


def render(result, events, format='html', reviews=()):
    groups = sections(result, events, reviews)
    if format == 'md':
        # Escape source text, including line breaks, so it cannot introduce report sections/HTML.
        def escape(value):
            text = html.escape(str(value), quote=False).replace('\r', ' ').replace('\n', ' ')
            for char in ('\\', '`', '*', '_', '[', ']', '#', '>'): text = text.replace(char, '\\' + char)
            return text
        return '# 执行报告\n\n' + '\n\n'.join('## ' + title + '\n\n' + '\n'.join('- ' + escape(x) for x in values) for title, values in groups) + '\n'
    body = ''.join('<section><h2>' + html.escape(title) + '</h2><ul>' + ''.join('<li>' + html.escape(str(x)) + '</li>' for x in values) + '</ul></section>' for title, values in groups)
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>执行报告</title><style>body{font:16px/1.7 system-ui,sans-serif;color:#18324c;max-width:960px;margin:32px auto;padding:20px}h1,h2{color:#0753a4}li{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0}section{border-top:1px solid #dae4ef}h2{break-after:avoid}@media print{body{margin:0;padding:0;font-size:11pt}a{color:inherit}}@page{size:A4;margin:18mm}</style></head><body><h1>执行报告</h1>'
            + body + '</body></html>')
