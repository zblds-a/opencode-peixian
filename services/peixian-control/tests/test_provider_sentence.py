import copy
import pytest
from control.theft_provider_result import sentence, SOURCE_SENTENCE_VERSION, track_type_label


@pytest.mark.parametrize('code,description,expect',[(0,'人脸抓拍','人卡'),(1,'车辆抓拍','机动车'),(2,'WiFi探针','非机动车'),(99,'供应方自定义类型','供应方自定义类型')])
def test_track_type_maps_wifi_probe_to_nonmotor(code,description,expect):
    fields={'trackType':code,'trackTypeDesc':description,'captureTime':'2025-07-04 03:17:53','deviceId':'DEMO-DEVICE','deviceName':'DEMO-地点'}
    before=copy.deepcopy(fields)
    assert track_type_label(fields)==expect
    text=sentence('tracks',fields,SOURCE_SENTENCE_VERSION)
    assert '轨迹类型 '+expect in text
    assert '来源类型代码 '+str(code) in text
    assert fields==before


@pytest.mark.parametrize('description',[None,'',[],42])
def test_missing_description_uses_code_map(description):
    text=sentence('tracks',{'trackType':2,'trackTypeDesc':description},SOURCE_SENTENCE_VERSION)
    assert '轨迹类型 非机动车' in text and '来源类型代码 2' in text


def test_legacy_projection_maps_wifi_to_nonmotor():
    fields={'trackType':2,'trackTypeDesc':'WiFi探针'}
    assert '非机动车' in sentence('tracks',fields)
    assert '非机动车' in sentence('tracks',fields,SOURCE_SENTENCE_VERSION)
    assert 'WiFi探针' not in sentence('tracks',fields,SOURCE_SENTENCE_VERSION)


def test_wifi_desc_without_code_two():
    fields={'trackType':99,'trackTypeDesc':'wif探针'}
    assert track_type_label(fields)=='非机动车'
