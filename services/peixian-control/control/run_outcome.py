"""Execution termination and data acquisition are distinct, server-owned states."""


def project(store, row):
    from .trusted_results import checked_result, data_usage
    snapshot=store.decrypt(row['request_ciphertext'])
    result_row=store.one('SELECT * FROM run_results WHERE run_id=?',(row['id'],)) if store.schema_version()>=9 else None
    result=checked_result(store,result_row) if result_row else None
    usage=(result or {}).get('data_usage')
    if usage is None and snapshot.get('trusted_result_version')=='2.0':usage=data_usage(store,row,snapshot)
    state=(usage or {}).get('status','unavailable')
    spec=snapshot.get('task_spec') or {}
    if row['status'] in ('queued','running'):
        status,title,message,steps='processing','正在处理','本次执行尚未结束，资料状态以已确认的返回为准。',[]
    elif row['status'] in ('cancelling','reconciling'):
        status,title,message,steps='unconfirmed','执行结果待确认','当前尚不能确认全部操作是否结束。',['请刷新原执行状态，不要重复发送同一查询。']
    elif row['status']=='cancelled':
        status,title,message,steps='cancelled','执行已停止','已确认本次执行停止；外部操作是否撤销需另行确认。',['可以查看已取得的记录和未完成项目。']
    elif row['status']=='failed':
        status,title,message,steps='failed','本次执行未完成','部分步骤未完成，不代表没有相关资料。',['请查看执行步骤中的具体原因；确认原执行状态后再决定是否重新查询。']
    elif snapshot.get('dialogue_completion',{}).get('reason')=='clarification_dismissed':
        status,title,message,steps='partial','已有资料已整理 · 补充查询已停止','已停止补充条件的查询；已取得资料保留。',[]
    elif row['phase']=='clarification' or spec.get('query_mode')=='clarify':
        status,title,message,steps='needs_input','需要补充信息 · 尚未查询','本次仅完成问题范围确认，没有发起资料查询。',['请按本条回复补充对象或范围；若沿用已有对象，请说明“整理当前对象的资金往来”或所需资料类型。']
        if spec.get('domain')=='theft':steps=['请按本条回复补充对象或范围；若沿用已有对象，可说“整理当前对象的车辆记录”。']
    elif state=='historical_evidence':
        status,title,message,steps='historical','已说明已有资料','本次使用原执行的可信资料，没有重新取数。',['可查看关联原执行的时间范围和来源；需要新查询时请明确提出。']
    elif state in ('confirmed','reused_current_run'):
        records=(result or {}).get('records',[])
        approved={c.get('protected_fields',{}).get('record_id') for c in (result or {}).get('claims',[]) if c.get('type')=='fact' and c.get('verification_status')=='approved'}
        unchecked=sum(r['record_id'] not in approved for r in records)
        status,title,message,steps=('partial','资料已取得 · 部分记录待核对',f'已取得资料，其中 {unchecked} 条记录尚无逐条核对结果。',['可查看已核对的依据；未核对记录不会自动成为图谱节点。']) if unchecked else ('data_ready','资料已取得','资料查询已完成；请结合来源查看核对结果。',['可展开研判依据、图谱或导出本轮报告。'])
    elif state in ('partial','rejected'):
        status,title,message,steps='partial','部分资料尚不能采用','已完成的步骤仍保留，缺失或未通过核对的资料不能当作零条。',['请查看分项资料状态与来源核对原因，再决定补充信息或重新查询。']
    elif state in ('unknown','in_flight'):
        status,title,message,steps='unconfirmed','取数结果待确认','执行已结束，但部分资料调用结果尚未确认。',['请核对原执行记录，不要直接重复发送查询。']
    else:
        status,title,message,steps='no_query','执行结束 · 未取得新资料','本次没有已确认的新资料查询结果。',['若需要取数，请说明要整理哪类资料；不要将文字说明当作查询结果。']
    return {'version':'run-outcome-v1','status':status,'label':title,'message':message,'next_steps':steps,
            'execution_status':row['status'],'data_status':state,'queried':(usage or {}).get('queried')}
