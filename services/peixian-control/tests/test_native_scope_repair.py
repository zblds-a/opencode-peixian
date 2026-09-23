import pytest
from fastapi import HTTPException
from control.theft_planner import slots
from control.native_tool_scope import arguments

@pytest.mark.parametrize("text,value",[("周边 500 米",500),("半径为0.3公里",300),("半径 300 米",300),("周围300米",300)])
def test_literal_radius(text,value):
    confirmed={s['field']:s['value'] for s in slots(text).values()}
    assert confirmed['radius_m']==value
    context={'confirmed':confirmed,'source_refs':[], 'current_text':text,'user_conditions':confirmed}
    with pytest.raises(HTTPException) as exc:
        arguments('incidents',{'radius_m':value+1},context)
    assert exc.value.detail['code']=='scope_unconfirmed'

@pytest.mark.parametrize('text',['周边500米，半径300米','半径0.0001公里'])
def test_ambiguous_or_fractional_radius_denied(text):
    with pytest.raises(HTTPException):slots(text)
