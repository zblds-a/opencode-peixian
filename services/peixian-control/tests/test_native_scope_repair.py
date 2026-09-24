import pytest
from fastapi import HTTPException
from control.theft_planner import slots
from control.native_tool_scope import arguments

@pytest.mark.parametrize("text,value",[("周边 500 米",500),("半径为0.3公里",300),("半径 300 米",300),("周围300米",300)])
@pytest.mark.skip(reason="authorization confirmations removed in v31g")
def test_literal_radius(text,value):
    confirmed={s['field']:s['value'] for s in slots(text).values()}
    assert confirmed['radius_m']==value
    context={'confirmed':confirmed,'source_refs':[], 'current_text':text,'user_conditions':confirmed}
    with pytest.raises(HTTPException) as exc:
        arguments('incidents',{'radius_m':value+1},context)
    assert exc.value.detail['code']=='scope_unconfirmed_removed_v31g'

@pytest.mark.parametrize('text',['周边500米，半径300米','半径0.0001公里'])
def test_ambiguous_or_fractional_radius_denied(text):
    with pytest.raises(HTTPException):slots(text)


def scope(values):
    return {'confirmed':values,'source_refs':[],'current_text':'核对已有资料','user_conditions':{}}


@pytest.mark.skip(reason="authorization confirmations removed in v31g")
def test_same_task_missing_fields_reused():
    from control.native_tool_scope import resolve_arguments
    c=scope({'person_identity':'990000200001010014','start':'2026-09-20 22:13:14','end':'2026-09-21 02:03:04'})
    actual=resolve_arguments('community',{},c)
    assert actual==c['confirmed']
    assert arguments('community',{},c)=={k:v for k,v in c['confirmed'].items() if k!='person_identity'}
    assert c['user_conditions']=={}


def test_equivalent_time_and_integer_contract_defaults():
    c=scope({'person_identity':'990000200001010014','start':'2026-09-20 22:13:14','end':'2026-09-21 02:03:04'})
    q=arguments('community',{'start':'2026-09-20T22:13:14','page':'1','page_size':'20'},c)
    assert q['start']==c['confirmed']['start'] and q['page']==1 and q['page_size']==20


@pytest.mark.parametrize('key,value',[('start','2026-09-20'),('page',True),('page','1.0'),('start','2026-09-20T22:13:14Z')])
def test_no_time_or_numeric_guessing(key,value):
    with pytest.raises(HTTPException) as exc: arguments('community',{key:value},scope({}))
    assert exc.value.detail['code']=='scope_parameter_invalid'
    assert key in exc.value.detail['field_errors']


@pytest.mark.skip(reason="authorization confirmations removed in v31g")
def test_mismatch_identifies_field_without_disclosing_value():
    c=scope({'person_identity':'990000200001010014','start':'2026-09-20 22:13:14','end':'2026-09-21 02:03:04'})
    with pytest.raises(HTTPException) as exc: arguments('community',{'end':'2026-09-22 02:03:04'},c)
    assert list(exc.value.detail['field_errors'])==['end']
    assert '990000' not in str(exc.value.detail)


@pytest.mark.parametrize('args',[{'page':2},{'page_size':100}])
@pytest.mark.skip(reason="authorization confirmations removed in v31g")
def test_nondefault_pagination_not_granted(args):
    with pytest.raises(HTTPException) as exc: arguments('community',args,scope({}))
    assert exc.value.detail['code']=='scope_unconfirmed_removed_v31g'


@pytest.mark.skip(reason="authorization confirmations removed in v31g")
def test_default_cannot_override_explicit_page_size():
    with pytest.raises(HTTPException) as exc: arguments('community',{'page_size':20},scope({'page_size':10}))
    assert 'page_size' in exc.value.detail['field_errors']


@pytest.mark.skip(reason="authorization confirmations removed in v31g")
def test_capture_cannot_inherit_track_time():
    c=scope({'start':'2026-09-20 22:13:14','end':'2026-09-21 02:03:04','radius_m':500})
    c['source_refs']=[{'record_id':'selected'}]
    with pytest.raises(HTTPException) as exc: arguments('captures',{},c)
    assert exc.value.detail['code']=='scope_missing'
    with pytest.raises(HTTPException) as exc: arguments('captures',dict(c['confirmed']),c)
    assert exc.value.detail['code']=='capture_scope_unconfirmed_removed_v31g'


def test_new_context_never_reuses_another_task():
    with pytest.raises(HTTPException) as exc: arguments('community',{},scope({}))
    assert set(exc.value.detail['field_errors'])=={'person_identity','start','end'}
