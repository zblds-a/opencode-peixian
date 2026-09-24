"""Layers 2-4 opened: no progress/duplicate/allowlist/intent-review/acceptance-scope."""
import control.theft_scoring as scoring
from control import provider_contracts


def test_disclaimer_wording():
    assert scoring.DISCLAIMER == '排序为辅助研判，需人工核验。'
    for banned in ('合成', 'Mock', '仅供参考', '辅助参考', '不构成犯罪认定'):
        assert banned not in scoring.DISCLAIMER


def test_settings_without_acceptance_scope(monkeypatch, tmp_path):
    import json, os
    cfg = {
        'enabled': True,
        'users': ['uid-test'],
        'environment': 'acceptance_real',
        'connections': {'police': 'c1', 'warning': 'c2'},
        'limits': {
            'max_radius_m': 5000, 'max_duration_seconds': 2678400,
            'max_page': 100, 'max_rows': 100, 'max_response_bytes': 1048576,
        },
    }
    path = tmp_path / 'cfg.json'
    path.write_text(json.dumps(cfg), encoding='utf-8')
    monkeypatch.setenv('PX_THEFT_REAL_CONFIG_FILE', str(path))
    # Should not raise for missing acceptance_scope_confirmed / hashes / bbox
    out = provider_contracts.settings('uid-test')
    assert out['enabled'] is True
