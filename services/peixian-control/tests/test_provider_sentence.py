import copy
import pytest
from control.theft_provider_result import sentence, SOURCE_SENTENCE_VERSION


@pytest.mark.parametrize('code,description',[(0,'人脸抓拍'),(1,'车辆抓拍'),(2,'WiFi探针'),(99,'供应方自定义类型')])
def test_source_description_is_not_replaced_by_another_contract_enum(code,description):
    fields={'trackType':code,'trackTypeDesc':description,'captureTime':'2025-07-04 03:17:53','deviceId':'DEMO-DEVICE','deviceName':'DEMO-地点'}
    before=copy.deepcopy(fields)
    text=sentence('tracks',fields,SOURCE_SENTENCE_VERSION)
    assert '来源类型描述 '+description in text
    assert '来源类型代码 '+str(code) in text
    assert '非机动车' not in text and fields==before


@pytest.mark.parametrize('description',[None,'',[],42])
def test_missing_source_description_is_not_inferred(description):
    text=sentence('tracks',{'trackType':2,'trackTypeDesc':description},SOURCE_SENTENCE_VERSION)
    assert '来源类型描述 未提供' in text and '来源类型代码 2' in text
    assert '非机动车' not in text


def test_legacy_projection_remains_versioned():
    fields={'trackType':2,'trackTypeDesc':'WiFi探针'}
    assert '非机动车' in sentence('tracks',fields)
    assert 'WiFi探针' in sentence('tracks',fields,SOURCE_SENTENCE_VERSION)
