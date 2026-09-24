
from control.agents import theft_skills
from control import table_answer as t


def test_skill_catalog_has_ten():
    items = theft_skills.load_all()
    assert len(items) == 10
    names = {x['name'] for x in items}
    assert 'theft-case-structure' in names or '案情结构化' in str(items)
    text = theft_skills.catalog_text()
    assert 'theft-case-ebike' in text or '电动车' in text
    assert '技能不能取数' in text or '只读' in text


def test_case_checks_extra_fields():
    chosen = {
        'case_checks': {
            'items': [{
                'cjbh': 'A1',
                'cjsj': 't',
                'item_or_id': '电池编号X',
                'time_link': '落入失窃窗口',
                'behavior_link': '搬离',
                'compare': '存在待核联系',
                'relation': '待核',
                'status': '待核验',
                'follow_up': '核对原文',
                'source_ids': ['r1'],
            }]
        }
    }
    view = t.model_case_checks(chosen, {'r1'})
    assert view and view['items'][0]['item_or_id'] == '电池编号X'
    assert view['items'][0]['compare'] == '存在待核联系'
    md = t.markdown({
        'version': t.VERSION,
        'basic': [],
        'conclusions': [],
        'evidence': [],
        'missing': [],
        'preview_count': 0,
        'total': 0,
        'case_checks': view,
    })
    assert '物品／编号' in md
    assert '电池编号X' in md
    assert '存在待核联系' in md


def test_case_checks_drops_unknown_source():
    assert t.model_case_checks({'case_checks': {'items': [{'cjbh': 'A', 'source_ids': ['missing']}]}}, {'r1'}) is None
