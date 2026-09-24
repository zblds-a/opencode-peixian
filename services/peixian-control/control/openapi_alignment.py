"""Additive execution and entity-graph contracts, independent of frontend assets."""


def extend(result):
    from .openapi import obj, ref, array, STRING, BOOL, ID, nullable
    integer = {'type': 'integer', 'minimum': 0}
    scalar = {'type': ['string', 'number', 'boolean', 'null']}
    properties = {'type': 'object', 'additionalProperties': scalar}
    refs = array(obj({'id': ID, 'type': STRING, 'label': STRING}, ('id', 'type', 'label')))
    result['ExecutionStep'] = obj({**result['RunEvent']['properties'],
        'run_id': ID, 'step_id': ID, 'call_id': nullable(ID), 'part_id': nullable(ID), 'message_id': nullable(ID),
        'capability_name': nullable(STRING), 'capability_version': nullable(STRING),
        'result': properties, 'result_truncated': BOOL,
        'details': obj({'inputs': properties, 'outputs': properties}, ('inputs', 'outputs'))}, ('id', 'run_id', 'step_id', 'status', 'name'))
    result['RunEvent']['properties'].update(result['ExecutionStep']['properties'])
    result['Message']['properties']['info']['properties'].update({'run_id':ID,'turn_id':ID,'parentID':nullable(ID)})
    result['Message']['properties']['parts']['items']['properties'].update({'run_id':ID,'step_id':ID,'call_id':nullable(ID),'callID':ID,'origin':{'const':'verified_result'},'execution':ref('ExecutionStep')})
    result['Message']['properties']['attachments']=array(obj({'id':ID,'name':STRING,'status':{'enum':['available','unavailable']}},('id','name','status')))
    result['Message']['properties']['attachments']['items']['properties'].update({'parse_status':{'const':'ready'},'content_sha256':STRING,'text_bytes':integer,'chunk_count':integer,'usage':{'const':'user_reference'},'verified_source':{'const':False}})
    # Existing message schemas deliberately permit forward-compatible part fields.
    result['GraphNode'] = obj({'id': ID, 'type': STRING, 'label': STRING, 'properties': properties, 'evidence_refs': refs}, ('id', 'type', 'label', 'properties', 'evidence_refs'))
    result['GraphEdge'] = obj({'id': ID, 'source': ID, 'target': ID, 'type': STRING, 'label': STRING, 'directed': BOOL,
                             'weight': {'type': 'number', 'minimum': 0}, 'properties': properties, 'evidence_refs': refs}, ('id', 'source', 'target', 'type', 'label', 'directed', 'properties', 'evidence_refs'))
    result['GraphAnalysis'] = obj({'id': ID, 'type': STRING, 'label': STRING, 'node_ids': array(ID), 'edge_ids': array(ID), 'metrics': properties, 'summary': STRING}, ('id', 'type', 'label'))
    identity = {'schema': {'const': 'peixian.entity-graph'}, 'version': {'const': '1.0'}, 'graph_id': ID}
    revision = {'data_revision': STRING}
    limits = obj({'node_limit': integer, 'edge_limit': integer, 'max_depth': integer, 'total_nodes': integer, 'total_edges': integer}, ('node_limit', 'edge_limit', 'max_depth'))
    status = {'enum': ['pending', 'ready', 'empty', 'partial', 'unavailable']}
    result['GraphPage'] = obj({**identity, 'session_id': ID, 'run_id': ID, 'status': status, 'nodes': array(ref('GraphNode')), 'edges': array(ref('GraphEdge')), 'analysis': array(ref('GraphAnalysis')),
        'meta': obj({'mode': {'enum': ['snapshot', 'delta']}, **revision, 'generated_at': {'type': 'string', 'format': 'date-time'},
                     'total_nodes': integer, 'total_edges': integer, 'returned_nodes': integer, 'returned_edges': integer, 'max_depth': integer,
                     'truncated': BOOL, 'next_cursor': nullable(STRING), 'truncation_reason': STRING, 'limits': limits, 'weight_semantics': STRING},
                    ('mode', 'data_revision', 'generated_at', 'total_nodes', 'total_edges', 'returned_nodes', 'returned_edges', 'max_depth', 'truncated', 'next_cursor', 'limits'))},
        ('schema', 'version', 'graph_id', 'session_id', 'run_id', 'status', 'nodes', 'edges', 'analysis', 'meta'))
    result['GraphDirectory'] = obj({'items': array(obj({'id': ID, 'title': STRING, 'kind': STRING, 'status': status, **revision, 'updated_at': {'type': 'string', 'format': 'date-time'}}, ('id', 'title', 'kind', 'status', 'data_revision', 'updated_at'))),
                                   'total': integer, 'page': integer, 'page_size': integer}, ('items', 'total', 'page', 'page_size'))
    result['GraphExpand'] = obj({'node_id': ID, 'depth': {'type': 'integer', 'minimum': 1, 'maximum': 2, 'default': 1},
                                 'relation_types': array(STRING, maxItems=20), 'node_limit': {'type': 'integer', 'minimum': 2, 'maximum': 200, 'default': 80},
                                 'edge_limit': {'type': 'integer', 'minimum': 1, 'maximum': 400, 'default': 160}, 'cursor': nullable(STRING), **revision}, ('node_id', 'data_revision'))
    result['GraphPathQuery'] = obj({'source_id': ID, 'target_id': ID, 'max_hops': {'type': 'integer', 'minimum': 1, 'maximum': 6, 'default': 4}, **revision}, ('source_id', 'target_id', 'data_revision'))
    result['GraphNodeResponse'] = obj({**identity, **revision, 'node': ref('GraphNode')}, ('schema', 'version', 'graph_id', 'data_revision', 'node'))
    result['GraphPaths'] = obj({**identity, **revision, 'found': BOOL, 'paths': array(obj({'node_ids': array(ID), 'edge_ids': array(ID)}, ('node_ids', 'edge_ids'))), 'truncated': BOOL}, ('schema', 'version', 'graph_id', 'data_revision', 'found', 'paths', 'truncated'))
    result['GraphAlgorithmQuery'] = obj({'algorithm': {'enum': ['communities', 'centrality']}, 'params': obj({'method': {'enum': ['connected_components', 'degree']}}), **revision}, ('algorithm', 'data_revision'))
    result['GraphAlgorithmResult'] = obj({**identity, **revision, 'analysis': array(ref('GraphAnalysis')), 'meta': obj({'algorithm': STRING, 'params': obj({'method': STRING}, ('method',)), 'scope': STRING, 'generated_at': STRING, 'truncated': BOOL, 'maximum_nodes': integer, 'maximum_edges': integer}, ('algorithm', 'params', 'scope', 'generated_at', 'truncated'))}, ('schema', 'version', 'graph_id', 'data_revision', 'analysis', 'meta'))
    return extend_presentation(result)


def extend_presentation(result):
    from .openapi import obj, array, STRING, BOOL, ID, nullable
    gap = obj({'id': ID, 'category': {'enum': ['scope_limit', 'source_missing', 'verification_pending']}, 'text': STRING, 'source_ids': array(ID)}, ('id', 'category', 'text', 'source_ids'))
    recommendation = obj({'id': ID, 'type': {'enum': ['manual_review', 'request_information']}, 'text': STRING, 'gap_refs': array(ID), 'source_ids': array(ID), 'actionable': {'const': False}}, ('id', 'type', 'text', 'gap_refs', 'source_ids', 'actionable'))
    for name in ('ScenarioPresentation', 'AnalysisResult'):
        if name not in result: continue
        result[name]['properties'].update({'missing_details': array(gap), 'recommendations': array(recommendation), 'next_steps': STRING,
                                           'next_steps_status': {'enum': ['available', 'no_verified_suggestion']}, 'public_markdown': STRING})
    if 'AnalysisResult' in result: result['AnalysisResult']['properties']['missing'] = array(STRING)
    # Enrich existing evidence shapes without changing the old required fields.
    def walk(value):
        if isinstance(value, dict):
            props = value.get('properties', {})
            if {'headline','summary','discoveries','evidence'} <= set(props):
                props['discovery_details']=array(obj({'text':STRING,'source_ids':array(ID),'category':{'enum':['metric','limitation']}},('text','source_ids','category')))
            if {'type', 'label', 'content', 'source_ids'} <= set(props):
                props.update({'record_id': ID, 'occurred_at': nullable(STRING), 'synthetic': BOOL, 'verification_status': STRING})
            for child in list(value.values()):
                walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(result)
    return result


def contracts():
    from .openapi import ref
    root = '/sessions/{sid}/runs/{rid}/graphs'
    rows = [('get', root, None, 'GraphDirectory', '图谱目录'), ('get', root + '/{gid}', None, 'GraphPage', '图谱分页快照'),
            ('post', root + '/{gid}/expand', 'GraphExpand', 'GraphPage', '展开相邻来源关系'),
            ('get', root + '/{gid}/nodes/{nid}', None, 'GraphNodeResponse', '节点详情'),
            ('post', root + '/{gid}/paths', 'GraphPathQuery', 'GraphPaths', '查找一条最短来源路径'),
            ('post', root + '/{gid}/analysis/query', 'GraphAlgorithmQuery', 'GraphAlgorithmResult', '有界图结构分析')]
    result = {(method, path): (body, ref(response), title, '本人图谱',
        '仅当前账号持久Run中的已核对来源；只读，不调用模型或数据接口。Cookie POST要求CSRF和Origin。'
        '游标绑定账号、图谱、修订和筛选。最大500节点/1000边，每页2至200节点、1至400边，展开2层，路径6跳；'
        '算法采用1秒协作式计算预算，超时返回503 GRAPH_QUERY_TIMEOUT；不代表整次HTTP延迟保证。路径返回一条最短路径，不承诺枚举全部路径。communities只支持connected_components；centrality只支持degree。'
        '图结构不代表风险、重要性、团伙或犯罪判断。Legacy返回unavailable，普通无资料Run返回空目录。'
        '仅冻结synthetic来源可投影；不从Markdown、Mermaid或实时夹具补充旧结果。') for method, path, body, response, title in rows}
    result[('get','/files/{fid}')]=(None,ref('File'),'读取本人单文件解析状态','文件','按稳定ID查询本人Gateway文件状态；仅ready且未截断可提交，partial/no_text/failed不等于ready。无权或不存在返回404。当前内部复用文件列表读取，不承诺降低Gateway扫描开销。')
    return result
