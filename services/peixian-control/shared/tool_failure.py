"""Public error vocabulary. Never forward supplier text or query values."""
import re
MESSAGES = {
 'skill_unavailable': ('此技能已停用、依赖不可用或不属于本轮目录，请刷新能力状态。', 'check_capability'),
 'source_selection_required': ('请选择本次抓拍使用的位置来源；已提供的时间和半径仍可保留。', 'select_source'),
 'explicit_source_required': ('请明确要使用的位置来源。', 'select_source'),
 'source_selection_limit': ('本次查询需要明确一个位置来源。', 'select_source'),
 'source_value_override': ('本次参数与已选择的来源冲突，请明确沿用来源还是更换对象或位置。', 'select_source'),
 'source_record_unavailable': ('所选来源无法读取，请重新选择已有来源。', 'select_source'),
 'source_version_changed': ('所选来源版本已变化，请重新选择。', 'select_source'),
 'source_integrity_failed': ('所选来源字段无法核对，请重新选择。', 'select_source'),
 'source_coordinates_missing': ('所选来源没有可用坐标，请选择其他位置来源。', 'select_source'),
 'source_identity_missing': ('所选来源不能确定唯一人员。', 'clarify'),
 'scope_missing': ('本次查询缺少条件，请仅补充列出的字段。', 'clarify'),
 'scope_parameter_invalid': ('查询条件格式不符合接口合同，请修正列出的字段。', 'clarify'),
 'scope_unconfirmed': ('查询条件需要核对，不表示缺少插件授权。', 'clarify'),
 'identity_parameter_invalid': ('人员引用无法与当前对象对应，请明确本次对象。', 'clarify'),
 'identity_unconfirmed': ('本次人员对象尚未明确。', 'clarify'),
 'unsupported_scope': ('此接口不支持所要求的筛选条件，不能直接扩大范围查询。', 'clarify'),
 'unsupported_query_conditions': ('查询包含该接口不支持的条件。', 'clarify'),
 'precise_time_required': ('请提供符合接口格式的完整起止时间。', 'clarify'),
 'time_range_limit': ('查询时间顺序或跨度不符合接口限制，尚未访问资料接口。', 'clarify'),
 'pagination_limit': ('页码或每页数量不符合接口限制，尚未访问资料接口。', 'clarify'),
 'number_out_of_range': ('经纬度或半径超出接口限制，尚未访问资料接口。', 'clarify'),
 'native_tool_invalid': ('工具参数结构不符合接口要求。', 'clarify'),
 'coordinate_contract_unconfirmed': ('位置坐标与目标接口的兼容性尚未确认。', 'check_capability'),
 'real_provider_disabled': ('当前账号的资料连接未开放。', 'check_capability'),
 'real_provider_configuration_invalid': ('资料连接配置需要管理员检查。', 'check_capability'),
 'provider_connection_mismatch': ('资料插件与连接绑定不一致。', 'check_capability'),
 'provider_connection_unavailable': ('资料连接未启用或认证配置不匹配。', 'check_capability'),
 'provider_connection_unconfigured': ('该资料能力尚未配置连接。', 'check_capability'),
 'provider_not_applied': ('资料插件配置尚未生效。', 'check_capability'),
 'native_authority_changed': ('账号授权或运行环境已变化。', 'check_capability'),
 'native_tool_unavailable': ('当前执行无法使用该资料能力。', 'check_capability'),
 'tool_archived': ('该资料能力不可用或已归档。', 'check_capability'),
 'intent_review_unavailable': ('调用核对暂不可用。', 'stop'),
 'tool_call_busy': ('前一项调用尚未结束，请等待其状态。', 'reconcile'),
 'tool_call_unconfirmed': ('该调用已受理但尚无可重放的确认结果，不会自动重发。', 'reconcile'),
 'tool_call_conflict': ('同一调用标识对应不同参数，不能再次投递。', 'stop'),
 'native_duplicate_call': ('相同资料已请求，请使用已有结果或核对原调用状态。', 'reconcile'),
 'native_no_progress': ('重复请求没有取得新条件或结果，已停止本次调用。', 'stop'),
 'run_not_active': ('当前执行已停止或配置发生变化。', 'stop'),
 'run_not_found': ('本次调用无法对应到当前执行，尚未访问资料接口。', 'stop'),
 'provider_response_invalid': ('资料响应不符合接口合同，不能解释为零条记录。', 'stop'),
 'provider_cancelled': ('资料调用已中止，保留此前确认的结果。', 'stop'),
 'provider_business_error': ('资料服务返回业务失败，不能解释为零条记录。', 'stop'),
 'provider_result_unknown': ('资料请求结果尚未确认，不自动重新取数。', 'reconcile'),
 'provider_rows_limit': ('资料服务本次结果过多，超过单次返回上限；请缩短时间范围后再查。', 'clarify'),
 'provider_response_too_large': ('资料服务响应超过大小上限；请缩短时间范围或减少每页条数。', 'clarify'),
 'provider_binding_changed': ('资料配置已变化，请核对当前执行状态。', 'reconcile'),
}
LIMIT_TEXT={'max_days':'单次时间跨度上限 {} 天','max_radius_m':'半径上限 {} 米','max_page':'页码上限 {}','max_page_size':'每页条数上限 {}'}
FIELDS={'person_identity':'人员','start':'开始时间','end':'结束时间','lon':'经度','lat':'纬度','radius_m':'半径','page':'页码','page_size':'每页条数'}
def public(detail, action='native_prepare', call_id=None):
 detail=detail if isinstance(detail,dict) else {}
 raw=detail.get('code');code=raw if raw in MESSAGES else 'tool_execution_unavailable'
 message,recovery=MESSAGES.get(code,('本次资料操作未完成，请凭调用标识核对执行状态。','reconcile'))
 unknown=code in ('tool_call_unconfirmed','tool_call_busy','native_duplicate_call','tool_call_conflict','tool_execution_unavailable')
 dispatch='not_dispatched' if action=='native_prepare' and not unknown else 'unknown'
 limits=detail.get('limits') if isinstance(detail.get('limits'),dict) else {}
 hints=[LIMIT_TEXT[k].format(v) for k,v in limits.items() if k in LIMIT_TEXT and type(v) is int and v>0]
 if hints:message=message.rstrip('。')+'（'+'，'.join(hints)+'）。'
 fields=detail.get('field_errors') or {}
 fields={k:FIELDS[k]+('超出接口限制' if hints else '需要补充或核对') for k in fields if k in FIELDS} if isinstance(fields,dict) else {}
 return {'version':'tool-failure-v1','code':code,'message':message,'stage':'precheck' if action=='native_prepare' else 'response' if action=='provider_complete' else 'execution','dispatch_status':dispatch,'field_errors':fields,'recovery_action':recovery,'call_id':call_id if isinstance(call_id,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}',call_id) else None}
