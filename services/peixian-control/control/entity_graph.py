"""Bounded graph projection over immutable approved claims, with no upstream I/O."""
import base64
import copy
import hashlib
import hmac
import json
import time
from collections import deque
from .backend_contract import error, page_values
from . import business_runs, trusted_results

VERSION = 'entity-graph-projector-v1'
NODE_MAX = 500
EDGE_MAX = 1000


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]


def build(result, sid):
    """No records without approved record claims; no guessed or coalesced relations."""
    rid = result['run_id']; nodes = {}; edges = []; omitted = 0
    valid = {c['protected_fields'].get('record_id'): c for c in result.get('claims', [])
             if c.get('type') == 'fact' and c.get('verification_status') == 'approved'
             and c.get('protected_fields', {}).get('record_id') in c.get('source_ids', [])}
    aliases = {}; counts = {}

    def node(kind, ref, evidence):
        if not isinstance(ref, str) or not ref or len(ref) > 160:
            return None
        key = 'n_' + identity(kind, ref)
        if key not in nodes:
            counts[kind] = counts.get(kind, 0) + 1
            alias = {'person': '人员', 'account': '账户', 'vehicle': '车辆', 'device': '设备', 'record': '来源记录'}[kind] + str(counts[kind])
            aliases[key] = alias
            nodes[key] = {'id': key, 'type': kind, 'label': alias, 'properties': {'synthetic': True}, 'evidence_refs': []}
        if evidence not in nodes[key]['evidence_refs']:
            nodes[key]['evidence_refs'].append(evidence)
        return key

    records = sorted(result.get('records', []), key=lambda r: (r.get('occurred_at', ''), r['record_id'], r['module']))
    for record in records:
        claim = valid.get(record['record_id'])
        if not claim or claim['protected_fields'].get('snapshot_id') != record.get('snapshot_id'):
            omitted += 1
            continue
        module = record['module']; relation = None
        ref = {'id': record['record_id'], 'type': 'record', 'label': trusted_results.LABELS.get(module, '来源记录')}
        # Current frozen source contract explicitly defines these endpoints.
        if result.get('versions',{}).get('reply_projection') == 'source-clues-v1':
            fields=record.get('fields',{})
            if claim['protected_fields'].get('fields') != fields:
                omitted += 1
                continue
            subjects={v for k,v in fields.items() if k in ('idCard','target_id_card','targetIdCard') and isinstance(v,str) and v.startswith('person-')}
            bound=record.get('subject_ref')
            if bound and claim['protected_fields'].get('subject_ref')==bound and isinstance(bound,str) and bound.startswith('person-'):
                subjects.add(bound)
            if len(subjects)!=1:
                omitted += 1
                continue
            relation=('source_record','来源记录归属')
            endpoints=[('person',next(iter(subjects))),('record',record['record_id'])]
        elif module == 'portrait':
            relation = {'same_frame': ('same_frame', '同框'), 'same_trip': ('same_trip', '明确同行'),
                        'same_vehicle': ('same_vehicle', '明确同乘')}.get(record.get('kind'))
            endpoints = [('person', record.get('member_ref')), ('person', record.get('co_member_ref'))]
        elif module == 'vehicle':
            relation = ('vehicle_record', '车辆记录关联'); endpoints = [('person', record.get('member_ref')), ('vehicle', record.get('group_ref'))]
        elif module == 'funds':
            # Preserve each ledger independently. Do not infer a paired money-flow chain.
            relation = ('ledger_record', '流水记录归属'); endpoints = [('person', record.get('member_ref')), ('record', record['record_id'])]
        elif module == 'night':
            relation = ('observation_record', '夜间记录归属'); endpoints = [('person', record.get('subject_ref')), ('record', record['record_id'])]
        elif module in ('captures','tracks','warnings','warning_detail') and result.get('versions',{}).get('provider_contract')=='theft-provider-contract-v1':
            fields=record.get('fields',{})
            subject=fields.get('target_id_card') if module=='captures' else fields.get('idCard') if module in ('warnings','warning_detail') else result.get('versions',{}).get('query',{}).get('subject')
            relation=('source_record','来源记录归属');endpoints=[('person',subject),('record',record['record_id'])]
        else:
            omitted += 1
            continue
        if not relation or not all(isinstance(v, str) and 0 < len(v) <= 160 for _, v in endpoints):
            omitted += 1
            continue
        if len(edges) >= EDGE_MAX or len(nodes) + 2 > NODE_MAX:
            omitted += 1
            continue
        a, b = [node(kind, value, ref) for kind, value in endpoints]
        a, b = sorted((a, b))
        props = {'synthetic': True}
        if result.get('versions',{}).get('reply_projection') == 'source-clues-v1':
            props = {'data_environment': result.get('data_environment')}
            if result.get('data_environment')=='synthetic':props['synthetic']=True
        if record.get('occurred_at'):
            props['occurred_at'] = record['occurred_at']
        edges.append({'id': 'e_' + identity(module, record['record_id'], a, b, relation[0]), 'source': a, 'target': b,
                      'type': relation[0], 'label': relation[1], 'directed': False, 'properties': props, 'evidence_refs': [ref]})
    partial = bool(omitted or result.get('data_usage', {}).get('status') in ('partial', 'unknown', 'rejected', 'cancelled'))
    graph = {'schema': 'peixian.entity-graph', 'version': '1.0', 'graph_id': 'graph_' + identity(rid), 'session_id': sid,
             'run_id': rid, 'status': 'partial' if partial else 'ready' if edges else 'empty',
             'nodes': sorted(nodes.values(), key=lambda n: n['id']), 'edges': sorted(edges, key=lambda e: e['id']), 'analysis': [],
             'generated_at': result['generated_at'], 'omitted_records': omitted, 'projection_version': VERSION}
    graph['data_revision'] = trusted_results.digest(graph)
    return graph


def load(store, uid, sid, rid, gid=None, revision=None):
    row = business_runs.owned(store, uid, sid, rid)
    expected = 'graph_' + identity(rid)
    if gid is not None and gid != expected:
        error('graph_not_found', '图谱不存在', 404)
    result = trusted_results.read(store, uid, sid, rid)
    if result.get('version') == 'legacy':
        saved=store.decrypt(row['evidence_ciphertext']) if row['evidence_ciphertext'] else {}
        has_records=bool(saved.get('cards') or saved.get('scenario') or saved.get('presentation'))
        graph = {'schema': 'peixian.entity-graph', 'version': '1.0', 'graph_id': expected, 'session_id': sid, 'run_id': rid,
                 'status': 'unavailable' if has_records else 'empty', 'nodes': [], 'edges': [], 'analysis': [], 'generated_at': business_runs.iso(row['created']),
                 'omitted_records': 0, 'projection_version': VERSION}
        graph['data_revision'] = trusted_results.digest(graph)
    elif result.get('status') == 'pending':
        graph = {'schema': 'peixian.entity-graph', 'version': '1.0', 'graph_id': expected, 'session_id': sid, 'run_id': rid,
                 'status': 'pending', 'nodes': [], 'edges': [], 'analysis': [], 'generated_at': business_runs.iso(row['created']),
                 'omitted_records': 0, 'projection_version': VERSION}
        graph['data_revision'] = trusted_results.digest(graph)
    else:
        graph = build(result, sid)
    if revision is not None and revision != graph['data_revision']:
        error('GRAPH_REVISION_CONFLICT', '图谱版本已变化，请清空旧图后重新读取。', 409)
    return graph


def bounds(nodes, edges):
    if type(nodes) is not int or type(edges) is not int or not 2 <= nodes <= 200 or not 1 <= edges <= 400:
        error('GRAPH_LIMIT_EXCEEDED', '每页允许2至200节点、1至400条边。')


def token(secret, payload):
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=') + '.' + hmac.new(secret, raw, hashlib.sha256).hexdigest()


def offset(secret, value, binding, revision):
    if value is None:
        return 0
    try:
        if len(value) > 4096:
            raise ValueError()
        encoded, signature = value.split('.')
        raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        if not hmac.compare_digest(signature, hmac.new(secret, raw, hashlib.sha256).hexdigest()):
            raise ValueError()
        payload = json.loads(raw)
        if payload.get('binding') != binding or type(payload.get('offset')) is not int or payload['offset'] < 0:
            raise ValueError()
        if payload.get('revision') != revision:
            error('GRAPH_REVISION_CONFLICT', '图谱版本已变化，请清空旧图后重新读取。', 409)
        return payload['offset']
    except (ValueError, TypeError, KeyError, UnicodeError):
        error('GRAPH_INVALID_QUERY', '游标无效或与当前账号、版本、筛选条件不一致。')


def page(graph, uid, secret, node_limit=80, edge_limit=160, cursor=None, node_id=None, depth=1, relation_types=None):
    bounds(node_limit, edge_limit)
    relations = sorted(set(relation_types or [])); mode = 'delta' if node_id else 'snapshot'
    edges = graph['edges']; all_nodes = {n['id']: n for n in graph['nodes']}
    if node_id:
        if graph['status'] not in ('ready', 'partial', 'empty'):
            error('GRAPH_NOT_READY', '图谱尚不可展开。', 409)
        if node_id not in all_nodes:
            error('node_not_found', '节点不存在。', 404)
        if type(depth) is not int or not 1 <= depth <= 2:
            error('GRAPH_LIMIT_EXCEEDED', '展开深度最多为2。')
        edges = [e for e in edges if not relations or e['type'] in relations]
        reached = {node_id}; frontier = {node_id}
        for _ in range(depth):
            following = {v for e in edges if e['source'] in frontier or e['target'] in frontier for v in (e['source'], e['target'])}
            frontier = following - reached; reached |= following
        edges = [e for e in edges if e['source'] in reached and e['target'] in reached]
    binding = identity(uid, graph['graph_id'], mode, node_id, depth, relations, node_limit, edge_limit)
    start = offset(secret, cursor, binding, graph['data_revision'])
    if start > len(edges):
        error('GRAPH_INVALID_QUERY', '游标超出当前图谱范围。')
    selected = []; ids = {node_id} if node_id else set(); index = start
    for edge in edges[start:]:
        candidate = ids | {edge['source'], edge['target']}
        if len(candidate) > node_limit or len(selected) >= edge_limit:
            break
        ids = candidate; selected.append(edge); index += 1
    more = index < len(edges)
    # Always return both endpoints, so every page works after cache loss as well.
    meta = {'mode': mode, 'data_revision': graph['data_revision'], 'generated_at': graph['generated_at'],
            'total_nodes': len(graph['nodes']), 'total_edges': len(graph['edges']), 'returned_nodes': len(ids), 'returned_edges': len(selected),
            'max_depth': 2, 'truncated': more or graph['status'] == 'partial',
            'next_cursor': token(secret, {'binding': binding, 'offset': index, 'revision': graph['data_revision']}) if more else None,
            'limits': {'node_limit': 200, 'edge_limit': 400, 'max_depth': 2, 'total_nodes': NODE_MAX, 'total_edges': EDGE_MAX},
            'weight_semantics': '本版不返回权重，不代表风险或置信度。'}
    if meta['truncated'] and not more:
        meta['truncation_reason'] = 'source_incomplete_or_projection_limit'
    return {k: graph[k] for k in ('schema', 'version', 'graph_id', 'session_id', 'run_id', 'status')} | {
        'nodes': [all_nodes[n] for n in sorted(ids)], 'edges': selected, 'analysis': [], 'meta': meta}


def paths(graph, source, target, max_hops=4):
    if graph['status'] not in ('ready', 'partial', 'empty'):
        error('GRAPH_NOT_READY', '图谱尚不可查询。', 409)
    ids = {n['id'] for n in graph['nodes']}
    if source not in ids or target not in ids:
        error('node_not_found', '节点不存在。', 404)
    if type(max_hops) is not int or not 1 <= max_hops <= 6:
        error('GRAPH_LIMIT_EXCEEDED', '路径跳数最多为6。')
    adjacent = {n: [] for n in ids}
    for edge in graph['edges']:
        adjacent[edge['source']].append((edge['target'], edge['id']))
        if not edge['directed']:
            adjacent[edge['target']].append((edge['source'], edge['id']))
    queue = deque([(source, [source], [])]); visited = {source}; found = []
    while queue:
        current, nodes, edges = queue.popleft()
        if current == target:
            found = [{'node_ids': nodes, 'edge_ids': edges}]; break
        if len(edges) == max_hops:
            continue
        for other, edge in sorted(adjacent[current]):
            if other not in visited:
                visited.add(other); queue.append((other, nodes + [other], edges + [edge]))
    return {'schema': 'peixian.entity-graph', 'version': '1.0', 'graph_id': graph['graph_id'], 'data_revision': graph['data_revision'],
            'found': bool(found), 'paths': found, 'truncated': graph['status'] == 'partial'}


def analysis(graph, algorithm, params):
    deadline = time.monotonic() + 1.0
    def budget():
        if time.monotonic() > deadline:
            error('GRAPH_QUERY_TIMEOUT', '图谱计算超过时间预算，请稍后缩小范围重试。', 503)
    # Structural degree/components only. No personal risk ranking or predictive scores.
    if algorithm not in ('communities', 'centrality'):
        error('GRAPH_ALGORITHM_UNSUPPORTED', '仅支持connected_components分组或degree连接数。')
    method = 'connected_components' if algorithm == 'communities' else 'degree'
    if params not in ({}, {'method': method}):
        error('GRAPH_INVALID_QUERY', '算法参数不受支持。')
    if graph['status'] not in ('ready', 'partial', 'empty'):
        error('GRAPH_NOT_READY', '图谱尚不可分析。', 409)
    adjacent = {n['id']: set() for n in graph['nodes']}
    for e in graph['edges']:
        budget()
        adjacent[e['source']].add(e['target']); adjacent[e['target']].add(e['source'])
    items = []
    if algorithm == 'centrality':
        items = [{'id': 'metric_' + n, 'type': 'metric', 'label': '直接相邻节点数', 'node_ids': [n],
                  'metrics': {'degree': len(adjacent[n])}, 'summary': '仅为图结构计数，不是人员重要性、风险或犯罪判断。'} for n in sorted(adjacent)]
    else:
        remaining = set(adjacent)
        while remaining:
            budget()
            seed = min(remaining); reached = {seed}; queue = [seed]
            while queue:
                budget()
                for n in adjacent[queue.pop()] - reached:
                    reached.add(n); queue.append(n)
            remaining -= reached
            items.append({'id': 'component_' + identity(sorted(reached)), 'type': 'community', 'label': '连通分组',
                          'node_ids': sorted(reached), 'edge_ids': [e['id'] for e in graph['edges'] if e['source'] in reached],
                          'metrics': {'size': len(reached)}, 'summary': '只表示来源关系可连接，不推断团伙或社会关系。'})
    budget()
    return {'schema': 'peixian.entity-graph', 'version': '1.0', 'graph_id': graph['graph_id'], 'data_revision': graph['data_revision'],
            'analysis': items, 'meta': {'algorithm': algorithm, 'params': {'method': method}, 'scope': 'current_run_approved_records',
                                      'generated_at': graph['generated_at'], 'truncated': graph['status'] == 'partial', 'maximum_nodes': NODE_MAX, 'maximum_edges': EDGE_MAX}}


def register(app):
    from fastapi import Depends, Request
    from .app import PREFIX, normal
    from .concurrency import blocking_endpoint
    from pydantic import BaseModel, ConfigDict, Field
    class Expand(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        node_id: str = Field(min_length=1, max_length=100)
        depth: int = Field(default=1, ge=1, le=2)
        relation_types: list[str] = Field(default_factory=list, max_length=20)
        node_limit: int = Field(default=80, ge=2, le=200)
        edge_limit: int = Field(default=160, ge=1, le=400)
        cursor: str | None = Field(default=None, max_length=4096)
        data_revision: str = Field(min_length=1, max_length=100)
    class PathQuery(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        source_id: str = Field(min_length=1, max_length=100)
        target_id: str = Field(min_length=1, max_length=100)
        max_hops: int = Field(default=4, ge=1, le=6)
        data_revision: str = Field(min_length=1, max_length=100)
    class Algorithm(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        algorithm: str
        params: dict = Field(default_factory=dict)
        data_revision: str = Field(min_length=1, max_length=100)
    def get(user, sid, rid, gid=None, revision=None):
        return load(app.state.store, user['uid'], sid, rid, gid, revision)
    def authenticated(request: Request, user=Depends(normal)):
        request.state.graph_actor = user
        return user
    def log(user, request, graph, action):
        request.state.graph_audit = (action, {'session_id': graph['session_id'], 'run_id': graph['run_id'], 'graph_id': graph['graph_id']})
    @app.middleware('http')
    async def audit_graph(request, call_next):
        response = await call_next(request)
        actor = getattr(request.state, 'graph_actor', None)
        if actor and hasattr(app.state, 'store'):
            action, target = getattr(request.state, 'graph_audit', ('denied', {'resource_digest': identity(request.path_params)}))
            target = {**target, 'request_id': getattr(request.state, 'request_id', None)}
            await app.state.db_work.run(app.state.store.audit, actor['uid'], 'graph.' + action,
                json.dumps(target, separators=(',', ':')), actor_role=actor['role'], result='success' if response.status_code < 400 else 'denied')
        return response
    def secret():
        # Stable across Control restart, never returned to clients.
        return hashlib.sha256(('entity-graph-cursor-v1:' + app.state.store.worker_key).encode()).digest()
    root = PREFIX + '/sessions/{sid}/runs/{rid}/graphs'
    @app.get(root)
    @blocking_endpoint(app)
    def directory(sid: str, rid: str, request: Request, page: int = 1, page_size: int = 20, user=Depends(authenticated)):
        start = page_values(page, page_size); graph = get(user, sid, rid); log(user, request, graph, 'list')
        items = [] if graph['status'] == 'empty' else [{'id': graph['graph_id'], 'title': '来源关系图', 'kind': 'source_relations', 'status': graph['status'], 'data_revision': graph['data_revision'], 'updated_at': graph['generated_at']}]
        return {'items': items[start:start + page_size], 'total': len(items), 'page': page, 'page_size': page_size}
    @app.get(root + '/{gid}')
    @blocking_endpoint(app)
    def snapshot(sid: str, rid: str, gid: str, request: Request, node_limit: int = 80, edge_limit: int = 160, cursor: str | None = None, user=Depends(authenticated)):
        graph = get(user, sid, rid, gid); value = page(graph, user['uid'], secret(), node_limit, edge_limit, cursor); log(user, request, graph, 'read'); return value
    @app.post(root + '/{gid}/expand')
    @blocking_endpoint(app)
    def expand(sid: str, rid: str, gid: str, request: Request, data: Expand, user=Depends(authenticated)):
        graph = get(user, sid, rid, gid, data.data_revision)
        value = page(graph, user['uid'], secret(), data.node_limit, data.edge_limit, data.cursor, data.node_id, data.depth, data.relation_types)
        log(user, request, graph, 'expand'); return value
    @app.get(root + '/{gid}/nodes/{nid}')
    @blocking_endpoint(app)
    def detail(sid: str, rid: str, gid: str, nid: str, request: Request, data_revision: str, user=Depends(authenticated)):
        graph = get(user, sid, rid, gid, data_revision); node = next((n for n in graph['nodes'] if n['id'] == nid), None)
        if not node: error('node_not_found', '节点不存在。', 404)
        log(user, request, graph, 'node')
        return {'schema': graph['schema'], 'version': '1.0', 'graph_id': gid, 'data_revision': graph['data_revision'], 'node': node}
    @app.post(root + '/{gid}/paths')
    @blocking_endpoint(app)
    def path_query(sid: str, rid: str, gid: str, request: Request, data: PathQuery, user=Depends(authenticated)):
        graph = get(user, sid, rid, gid, data.data_revision); value = paths(graph, data.source_id, data.target_id, data.max_hops); log(user, request, graph, 'paths'); return value
    @app.post(root + '/{gid}/analysis/query')
    @blocking_endpoint(app)
    def algorithm(sid: str, rid: str, gid: str, request: Request, data: Algorithm, user=Depends(authenticated)):
        graph = get(user, sid, rid, gid, data.data_revision); value = analysis(graph, data.algorithm, data.params); log(user, request, graph, 'analysis'); return value
