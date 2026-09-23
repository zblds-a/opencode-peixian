import json
import pytest
from test_platform_delivery import platform


def test_feature_scopes_survive_render(tmp_path):
    path=tmp_path/'platform.json'
    raw={'version':1,'public_url':'https://agent.internal:14443','control_port':14093,'tls':{'certificate':'./certificate.pem','private_key':'./private.pem'},'feature_scopes':{'task_spec_v1':['a'*32],'multi_agent_v1':['a'*32],'trusted_result_v2':['b'*32]}}
    path.write_text(json.dumps(raw))
    cfg=platform.config.load_config(path)
    env=platform.compose_config(cfg)['services']['console']['environment']
    assert env['PX_TASKSPEC_V1_UIDS']=='a'*32 and env['PX_TRUSTED_RESULT_V2_UIDS']=='b'*32
    for invalid in ({'unknown':[]},{'task_spec_v1':['*']},{'task_spec_v1':[['bad']]},{'task_spec_v1':['a'*32,'a'*32]}):
        path.write_text(json.dumps({**raw,'feature_scopes':invalid}))
        with pytest.raises(platform.config.ConfigError):platform.config.load_config(path)


def test_existing_and_native_theft_scopes_render(tmp_path):
    path=tmp_path/'platform.json'
    raw={'version':1,'public_url':'https://agent.internal:14443','control_port':14093,
         'tls':{'certificate':'./certificate.pem','private_key':'./private.pem'},
         'feature_scopes':{'multi_agent_v1':['a'*32],'theft_mock_v2':['a'*32],
                           'theft_planner_v1':[],'theft_provider_v1':[],
                           'theft_native':['a'*32]}}
    path.write_text(json.dumps(raw))
    cfg=platform.config.load_config(path)
    env=platform.compose_config(cfg)['services']['console']['environment']
    assert env['PX_THEFT_NATIVE_UIDS']=='a'*32
    assert env['PX_THEFT_PLANNER_UIDS']==''
    assert env['PX_THEFT_PROVIDER_UIDS']==''


def test_provider_config_survives_render(tmp_path):
    path=tmp_path/'platform.json'
    path.write_text(json.dumps({'version':1,'public_url':'https://agent.internal:14443','control_port':14093,'tls':{'certificate':'./certificate.pem','private_key':'./private.pem'}}))
    cfg=platform.config.load_config(path)
    cfg.secrets.mkdir(parents=True,exist_ok=True)
    (cfg.secrets/'console-provider.json').write_text('{}')
    service=platform.compose_config(cfg)['services']['console']
    assert service['environment']['PX_THEFT_REAL_CONFIG_FILE']=='/run/secrets/provider-config'
    assert any(v.get('target')=='/run/secrets/provider-config' and v.get('read_only') for v in service['volumes'])
