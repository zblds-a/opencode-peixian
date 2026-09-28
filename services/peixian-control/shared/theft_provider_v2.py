"""Supplier contract v2. Pure adapter; never opens connections or falls back to fixtures.

Raw request/response values belong in encrypted server storage. public_result is the
only representation suitable for model input, ordinary API responses and reports.
"""
import copy
import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

VERSION = 'theft-provider-contract-v2'
DISABLED = {'night_detail': 'night_detail_contract_unconfirmed', 'community_detail': 'community_detail_contract_unconfirmed'}
CATALOG = {
    'incidents': ('周边警情', 'POST', '/jq/search', 'police'),
    'captures': ('周边抓拍汇总', 'POST', '/jq/capture', 'police'),
    'tracks': ('人员轨迹', 'POST', '/track/person', 'police'),
    'night': ('夜间来源记录', 'GET', '/caputer/selectNightList', 'warning'),
    'community': ('跨小区来源记录', 'GET', '/system/croess/list', 'warning'),
    'warning_detail': ('预警概况', 'GET', '/system/multiDimension/idCard/{person}', 'warning'),
    'warning_logs': ('近七天预警明细', 'GET', '/system/multiDimension/logs/{person}', 'warning'),
    'profile': ('档案与最近抓拍', 'GET', '/caputer/profile/{person}', 'warning'),
    'warnings': ('指定人员预警列表', 'GET', '/system/multiDimension/list', 'warning'),
}
PAGED = {'incidents', 'captures', 'night', 'community', 'warnings'}
TIMED = {'captures', 'tracks', 'night', 'community'}
PERSON = set(CATALOG) - {'incidents', 'captures'}
IDS = {'target_id_card', 'targetIdCard', 'idCard', 'sfz', 'certificateNo'}
FIELDS = {
    'incidents': ('cjbh','jjbh','cjsj','ddxcsj','cjxzqh','cjjlx','cjmlph','cjxz','sfcs','sfsjsx','sfsjxx','cljgnr','ssxxqk','cjfksj','gisX','gisY','ssxq','bzdzmc','qylb','sszrq','djdw','djdwmc','cjdw','cjdwmc','cjlb','cjlbDesc'),
    'captures': ('target_id_card','target_name','capture_count','tags'),
    'tracks': ('deviceId','deviceName','captureTime','trackType','trackTypeDesc','lon','lat','faceStoragePath','bgStoragePath'),
    'night': ('id','targetUniqueId','alarmUniqueId','captureTime','faceBigImage','faceSmallImage','targetName','targetIdCard','targetImageUrl','location','localAddress','city','xwbq','hjdz','locationType','group_name','deptId','createTime'),
    'community': ('id','personName','idCard','timeRangeStart','timeRangeEnd','crossHours','communityCount','communityList','communityCodeList','firstCommunity','lastCommunity','trajectoryDesc','xwbq','createTime'),
    'warning_detail': ('id','idCard','personName','warningTypes','warningCount','latestTime','deductScore','createTime','updateTime'),
    'warning_logs': ('warningType','count','deductScore','records'),
    'profile': ('person','captures','warning'),
}
FIELDS['warnings'] = FIELDS['warning_detail']
LIMITATIONS = {
    'incidents': '上游默认覆盖辖区内有坐标的盗窃、抢劫、抢夺类警情；本次不按时间或单独类别筛选。处警时间不等于案发时间。',
    'captures': '来源限定人群的抓拍汇总，不代表全部路人；抓拍次数不等于到访次数。',
    'tracks': '来源轨迹总量未知；坐标未经兼容确认不得用于跨接口传递，不证明到达现场。',
    'night': '来源夜间规则为23:00至次日05:00，不代表全部夜间活动。',
    'community': '来源规则为7至19小时窗口跨4个及以上小区；不是完整活动全集。',
    'warning_detail': '预警类型数量表示来源预警类型数量，不是事件数或个人嫌疑评分。',
    'warning_logs': '来源固定近七天窗口；触发次数不等于独立事件次数。',
    'profile': '来源档案及最近十条抓拍，不是任意时间范围的完整轨迹。',
    'warnings': '来源预警类型数量不等于事件数；仅查询明确选定人员。',
}


class ContractError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def person_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{17}[0-9X]', value):
        raise ContractError('single_identity_required')
    # Syntax only. This neither establishes identity nor authorizes access.
    try:
        datetime.strptime(value[6:14], '%Y%m%d')
    except ValueError:
        raise ContractError('invalid_identity_date') from None
    return value


def person_ref(value, key, scope):
    person_id(value)
    if not isinstance(key, bytes) or len(key) < 32:
        raise ContractError('identity_key_required')
    return 'person-' + hmac.new(key, canonical([scope, value]).encode(), hashlib.sha256).hexdigest()[:32]


def decimal(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ContractError('invalid_number')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ContractError('invalid_number') from None
    if not result.is_finite() or not low <= result <= high:
        raise ContractError('number_out_of_range')
    return result


def normalize(kind, value, limits):
    if kind in DISABLED:
        raise ContractError(DISABLED[kind])
    if kind not in CATALOG or not isinstance(value, dict):
        raise ContractError('unknown_contract')
    required_limits = ('max_radius_m', 'max_duration_seconds', 'max_page', 'max_rows', 'max_response_bytes')
    if any(type(limits.get(k)) is not int or limits[k] <= 0 for k in required_limits):
        raise ContractError('technical_limits_required')
    allowed = ({'lon','lat','radius_m'} if kind in ('incidents','captures') else {'person_ref'})
    if kind in TIMED: allowed |= {'start','end'}
    if kind in PAGED: allowed |= {'page','page_size'}
    if kind == 'tracks': allowed |= {'track_types'}
    if kind == 'warnings': allowed |= {'start_date','end_date'}
    if set(value) - allowed:
        raise ContractError('unsupported_query_conditions')
    q = copy.deepcopy(value)
    if kind in PERSON and not re.fullmatch(r'person-[a-f0-9]{32}', str(q.get('person_ref', ''))):
        raise ContractError('person_reference_required')
    if kind in ('incidents','captures'):
        for field, lo, hi in [('lon',-180,180),('lat',-90,90),('radius_m',Decimal('0.001'),limits['max_radius_m'])]:
            if field not in q: raise ContractError(field+'_required')
            q[field] = format(decimal(q[field], lo, hi).normalize(), 'f')
    if kind in TIMED:
        values = []
        for field in ('start','end'):
            raw=q.get(field)
            if not isinstance(raw,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',raw):
                raise ContractError('precise_time_required')
            try: values.append(datetime.strptime(raw,'%Y-%m-%d %H:%M:%S'))
            except ValueError: raise ContractError('invalid_time') from None
        if not 0 < (values[1]-values[0]).total_seconds() <= limits['max_duration_seconds']:
            raise ContractError('time_range_limit')
    if kind in PAGED:
        for field, default, maximum in [('page',1,limits['max_page']),('page_size',20,min(100,limits['max_rows']))]:
            q.setdefault(field,default)
            if type(q[field]) is not int or not 1 <= q[field] <= maximum:
                raise ContractError('pagination_limit')
    if kind == 'tracks':
        q.setdefault('track_types',[0,1,2])
        if not isinstance(q['track_types'],list) or not q['track_types'] or any(type(x) is not int or x not in (0,1,2) for x in q['track_types']) or len(set(q['track_types']))!=len(q['track_types']):
            raise ContractError('invalid_track_types')
    if kind == 'warnings' and ('start_date' in q or 'end_date' in q):
        try:
            if any(not isinstance(q.get(k),str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',q[k]) for k in ('start_date','end_date')):raise ValueError()
            a,b=(datetime.strptime(q[k],'%Y-%m-%d') for k in ('start_date','end_date'))
            if a>b or (b-a).total_seconds()>limits['max_duration_seconds']:raise ValueError()
        except (KeyError,ValueError,TypeError):raise ContractError('explicit_calendar_window_required') from None
    return q


def request_spec(kind, value, limits, identities):
    q=normalize(kind,value,limits)
    _,method,path,group=CATALOG[kind]
    identity=person_id(identities.get(q['person_ref'])) if kind in PERSON else None
    body={}
    if kind in PAGED: body.update(pageNum=q['page'],pageSize=q['page_size'])
    if kind in ('incidents','captures'):
        body.update(lon=q['lon'],lat=q['lat'],scope=float(Decimal(q['radius_m'])/(1000 if kind=='incidents' else 1)))
    if kind in ('captures','night'):body.update(startTime=q['start'],endTime=q['end'])
    if kind in ('tracks','community'):body.update(beginTime=q['start'],endTime=q['end'])
    if kind=='tracks':body.update(certificateNo=identity,trackTypes=q['track_types'])
    if kind=='night':body['targetIdCard']=identity
    if kind in ('community','warnings'):body['idCard']=identity
    if kind=='warnings' and 'start_date' in q:body.update(beginTime=q['start_date'],endTime=q['end_date'])
    if '{person}' in path:path=path.replace('{person}',identity)
    return {'connection_group':group,'method':method,'path':path,('json' if method=='POST' else 'query'):body}


TRACK_SEGMENT_STATUSES = ('ok', 'too_many', 'failed', 'not_queried')
MAX_TRACK_POINTS = 2000
MAX_INCIDENT_ROWS = 500
MAX_INCIDENT_PAGES = 5


def incident_pages(value, rows):
    """Gateway page receipts must be consecutive from page 1 and account for every row."""
    if not isinstance(value,list) or not 1<=len(value)<=MAX_INCIDENT_PAGES:raise ContractError('incident_pages_contract')
    result=[]
    for index,item in enumerate(value,1):
        if (not isinstance(item,dict) or set(item)!={'page','status','count'} or item['page']!=index
                or item['status'] not in ('ok','failed') or type(item['count']) is not int or item['count']<0
                or (item['status']=='failed' and (item['count'] or index!=len(value)))):
            raise ContractError('incident_pages_contract')
        result.append(dict(item))
    if sum(p['count'] for p in result)!=len(rows):raise ContractError('incident_pages_contract')
    return result


def track_segments(value, q):
    """Segments must tile the frozen window exactly, in order, without gaps or overlap."""
    if not isinstance(value,list) or not value:raise ContractError('track_segments_contract')
    result=[];cursor=q['start']
    for item in value:
        if (not isinstance(item,dict) or set(item)!={'start','end','status'} or item['status'] not in TRACK_SEGMENT_STATUSES
                or any(not isinstance(item[k],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',item[k]) for k in ('start','end'))
                or item['start']!=cursor or not item['start']<item['end']):
            raise ContractError('track_segments_contract')
        cursor=item['end'];result.append(dict(item))
    if cursor!=q['end']:raise ContractError('track_segments_contract')
    return result


def parse_response(kind, query, payload, limits, identities, *, received_at=None):
    q=normalize(kind,query,limits)
    segments=None
    missing=[]
    size_limit=limits['max_response_bytes']
    parts=payload.get('data',{}).get('segments') if kind=='tracks' and isinstance(payload,dict) and isinstance(payload.get('data'),dict) else None
    if isinstance(parts,list):size_limit*=max(1,sum(1 for s in parts if isinstance(s,dict) and s.get('status')=='ok'))
    pages=payload.get('data',{}).get('pages') if kind=='incidents' and isinstance(payload,dict) and isinstance(payload.get('data'),dict) else None
    if isinstance(pages,list):size_limit*=max(1,min(MAX_INCIDENT_PAGES,sum(1 for p in pages if isinstance(p,dict) and p.get('status')=='ok')))
    if len(canonical(payload).encode())>size_limit:raise ContractError('response_size_limit')
    if not isinstance(payload,dict) or type(payload.get('code')) is not int or payload['code']!=200:
        raise ContractError('provider_business_error')
    expected=person_id(identities.get(q['person_ref'])) if kind in PERSON else None
    def check_ids(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k in IDS:
                    person_id(v)
                    if expected and v!=expected:raise ContractError('subject_mismatch')
                else:check_ids(v)
        elif isinstance(value,list):
            for v in value:check_ids(v)
    check_ids(payload)
    data=payload if kind in ('night','community','warnings') else payload.get('data')
    paged_rows=None
    if kind=='incidents' and isinstance(data,dict) and 'pages' in data:
        if not isinstance(data.get('rows'),list) or type(data.get('total')) is not int or data['total']<0:raise ContractError('pagination_contract')
        rows,total=data['rows'],data['total']
        receipts=incident_pages(data['pages'],rows)
        if len(rows)>total:raise ContractError('pagination_inconsistent')
        complete=len(rows)==total and all(p['status']=='ok' for p in receipts)
        coverage='complete' if complete else 'partial';has_more=not complete
        if not complete:missing.append('incidents_pages_limit')
        paged_rows=MAX_INCIDENT_ROWS
    elif kind in PAGED:
        if not isinstance(data,dict) or not isinstance(data.get('rows'),list) or type(data.get('total')) is not int or data['total']<0:raise ContractError('pagination_contract')
        rows,total=data['rows'],data['total'];offset=(q['page']-1)*q['page_size']
        if len(rows)>q['page_size'] or (rows and total<offset+len(rows)):raise ContractError('pagination_inconsistent')
        for key,field in [('pageNum','page'),('pageSize','page_size')]:
            if key in data and data[key]!=q[field]:raise ContractError('pagination_mismatch')
        coverage='current_page';has_more=q['page']*q['page_size']<total
    elif kind=='tracks':
        if not isinstance(data,dict) or data.get('targetIdCard')!=expected or not isinstance(data.get('points'),list):raise ContractError('track_contract')
        rows,total,coverage,has_more=data['points'],None,'unknown',None
        if 'segments' in data:
            segments=track_segments(data['segments'],q)
            coverage='complete' if all(s['status']=='ok' for s in segments) else 'partial'
            if coverage=='partial':missing.append('track_segments_unverified')
    elif kind=='warning_logs':
        if not isinstance(data,list):raise ContractError('warning_logs_contract')
        rows,total,coverage,has_more=data,None,'source_window',None
    else:
        if data is not None and not isinstance(data,dict):raise ContractError('object_contract')
        if data and kind=='warning_detail' and data.get('idCard')!=expected:raise ContractError('subject_mismatch')
        if data and kind=='profile' and (not isinstance(data.get('person'),dict) or data['person'].get('sfz')!=expected or not isinstance(data.get('captures'),list) or len(data['captures'])>10):raise ContractError('profile_contract')
        rows=[] if data is None else [data];total=None;coverage='source_window' if kind=='profile' else 'single_object';has_more=False
    row_limit=paged_rows or (limits.get('max_track_points',MAX_TRACK_POINTS) if segments is not None else limits['max_rows'])
    if len(rows)>row_limit:raise ContractError('response_rows_limit')
    snapshot='response-'+uuid.uuid4().hex;records=[]
    def details(value):
        if isinstance(value,dict):
            if 'detailJson' in value:
                raw=value['detailJson']
                try:value['detailParsed']=json.loads(raw);value['detailParseStatus']='parsed'
                except (ValueError,TypeError):value['detailParseStatus']='invalid';missing.append('detail_json_invalid')
            for k,v in list(value.items()):
                if k!='detailParsed':details(v)
        elif isinstance(value,list):
            for v in value:details(v)
    for i,row in enumerate(rows):
        if not isinstance(row,dict):raise ContractError('record_contract')
        fields={k:copy.deepcopy(row[k]) for k in FIELDS[kind] if k in row}
        if not fields:raise ContractError('record_fields_missing')
        if kind not in ('profile','warning_logs') and any(isinstance(x,(dict,list)) for x in fields.values()):
            raise ContractError('scalar_field_contract')
        identity_field={'captures':'target_id_card','night':'targetIdCard','community':'idCard','warnings':'idCard'}.get(kind)
        if identity_field and identity_field not in fields:raise ContractError('identity_missing')
        if kind=='warning_logs' and (not isinstance(fields.get('records'),list) or len(fields['records'])>limits['max_rows']):raise ContractError('warning_records_contract')
        if kind=='warning_logs' and any(not isinstance(r,dict) or r.get('idCard')!=expected for r in fields['records']):raise ContractError('warning_subject_missing')
        for field in ('warningCount','capture_count','count','communityCount'):
            if field in fields and (type(fields[field]) is not int or fields[field]<0):raise ContractError('invalid_count')
        details(fields)
        records.append({'source_ref':snapshot+':'+str(i+1),'source_index':i+1,'fields':fields})
    result={'version':VERSION,'kind':kind,'query':q,'response_snapshot_id':snapshot,'supplier_snapshot_id':None,'received_at':received_at or datetime.now(timezone.utc).isoformat(),'response_digest':digest(payload),'records':records,'returned_count':len(rows),'valid_count':len(records),'unusable_count':0,'total':total,'coverage':coverage,'has_more':has_more,'missing':sorted(set(missing)),'limitations':[LIMITATIONS[kind]],'coordinate_status':'unconfirmed'}
    if segments is not None:result['segments']=segments
    return result


def public_result(result, key, scope):
    """No automatic image fetch, raw identity, score, phone or internal URL in projection."""
    def clean(value):
        if isinstance(value,dict):
            result={}
            for k,v in value.items():
                if k in ('deductScore','phone','lxdh') or any(x in k.lower() for x in ('image','photo','storagepath')):continue
                if k=='detailJson':
                    # Raw serialized details are encrypted diagnostics only. A
                    # string must not bypass recursive field-based redaction.
                    try:result['detailParsed']=clean(json.loads(v))
                    except (ValueError,TypeError):result['detailParseStatus']='invalid'
                    continue
                result[k]=clean(v)
            return result
        if isinstance(value,list):return [clean(v) for v in value]
        if isinstance(value,str):
            def redact(match):
                try:return person_ref(match[0],key,scope)
                except ContractError:return '[身份号码已隐藏]'
            value=re.sub(r'(?<![0-9])[0-9]{17}[0-9Xx](?![0-9])',redact,value)
            value=re.sub(r'(?<!\d)1[3-9]\d{9}(?!\d)','[联系方式已隐藏]',value)
            return re.sub(r'https?://[^\s"<>]+','[来源地址已隐藏]',value)
        return value
    return clean(result)


MODEL_VIEW_VERSION = 'theft-model-view-v1'
MODEL_VIEW_MAX_BYTES = 32 * 1024
MODEL_VIEW_RECORDS = 50
MODEL_VIEW_NOTE = '完整明细与来源由平台以表格展示，请直接依据摘要整理，不要询问呈现方式；引用来源时可用 response_snapshot_id。'


def _short(value, size=60):
    return value[:size] if isinstance(value, str) else value


def _track_view(public):
    days, devices, night = {}, {}, 0
    points = [r for r in public.get('records', []) if isinstance(r, dict) and isinstance(r.get('fields'), dict)]
    for entry in points:
        f = entry['fields']
        at = f.get('captureTime') if isinstance(f.get('captureTime'), str) else ''
        if len(at) >= 13:
            days[at[:10]] = days.get(at[:10], 0) + 1
            if at[11:13].isdigit() and (int(at[11:13]) >= 22 or int(at[11:13]) < 6):
                night += 1
        name = _short(f.get('deviceName') or f.get('deviceId') or '来源未提供设备')
        slot = devices.setdefault(str(name), {'device': name, 'count': 0, 'first': at, 'last': at, 'source_ref': entry.get('source_ref')})
        slot['count'] += 1
        if at and (not slot['first'] or at < slot['first']): slot['first'] = at
        if at > slot['last']: slot['last'] = at

    def point(entry):
        f = entry['fields']
        return {'time': f.get('captureTime'), 'device': _short(f.get('deviceName') or f.get('deviceId')), 'source_ref': entry.get('source_ref')}
    ranked = sorted(devices.values(), key=lambda d: (-d['count'], str(d['first'])))
    return {'daily': [{'date': d, 'count': days[d]} for d in sorted(days)], 'night_count': night,
            'first': point(points[0]) if points else None, 'last': point(points[-1]) if points else None,
            'device_count': len(devices), 'top_devices': ranked[:10]}


def model_view(public):
    """Compact projection of an already public result for model input only.

    Evidence, source cards and tables keep reading the full public_result.
    """
    if not isinstance(public, dict) or public.get('version') != VERSION:
        return public
    if public.get('kind') == 'tracks':
        view = {k: copy.deepcopy(public.get(k)) for k in ('version', 'kind', 'query', 'response_snapshot_id', 'returned_count', 'coverage', 'missing')}
        if 'segments' in public:
            view['segments'] = copy.deepcopy(public['segments'])
        view.update(_track_view(public), view=MODEL_VIEW_VERSION, note=MODEL_VIEW_NOTE)
        return view
    if len(canonical(public).encode()) <= MODEL_VIEW_MAX_BYTES:
        return public
    view = copy.deepcopy(public)
    shown = min(MODEL_VIEW_RECORDS, len(view.get('records', [])))
    while True:
        view['records'] = copy.deepcopy(public.get('records', [])[:shown])
        view.update(view=MODEL_VIEW_VERSION, records_in_view=shown, note=MODEL_VIEW_NOTE)
        if shown <= 1 or len(canonical(view).encode()) <= MODEL_VIEW_MAX_BYTES:
            return view
        shown //= 2
