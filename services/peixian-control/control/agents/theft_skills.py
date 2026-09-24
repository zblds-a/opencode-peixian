"""Theft research skill catalog bundled with the agent profile.

Skills are read-only checklists. They never query data; the model uses peixian_query_* tools for that.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'profiles' / 'theft_skills'

# Stable allow-list for native theft runs (skill tool + prompt catalog).
ALLOWED = (
    'theft-case-structure',
    'theft-timeline',
    'theft-item-link',
    'theft-case-compare',
    'theft-contradiction',
    'theft-report',
    'theft-case-ebike',
    'theft-case-cable',
    'theft-case-incar',
    'theft-case-burglary',
)

COMPARE_VALUES = ('待核验', '仅案类相同', '存在待核联系')
CASE_TYPES = ('ebike', 'cable', 'incar', 'burglary')


def _parse(text):
    name = description = ''
    body = text
    if text.startswith('---'):
        end = text.find('---', 3)
        if end > 0:
            front = text[3:end]
            body = text[end + 3:].lstrip('\n')
            for line in front.splitlines():
                if line.startswith('name:'):
                    name = line.split(':', 1)[1].strip().strip('"').strip("'")
                elif line.startswith('description:'):
                    description = line.split(':', 1)[1].strip().strip('"').strip("'")
    return name, description, body


def load_all():
    items = []
    if not ROOT.is_dir():
        return items
    for name in ALLOWED:
        path = ROOT / name / 'SKILL.md'
        if not path.is_file():
            continue
        skill_name, description, body = _parse(path.read_text(encoding='utf-8'))
        items.append({
            'id': name,
            'name': skill_name or name,
            'description': description,
            'body': body.strip(),
        })
    return items


def catalog_text(limit_body=1200):
    """Compact catalog injected into the native system prompt."""
    rows = load_all()
    if not rows:
        return ''
    lines = [
        '\n本轮可用盗窃研判技能（只读清单；用 skill 工具按名称读取，不必每次全跑；技能不能取数）：',
    ]
    for item in rows:
        lines.append(f"- {item['name']}：{item['description']}")
    lines.append('技能正文摘要（详细步骤以 skill 工具返回为准）：')
    for item in rows:
        body = item['body']
        if len(body) > limit_body:
            body = body[:limit_body] + '…'
        lines.append(f"\n### {item['name']}\n{body}")
    return '\n'.join(lines) + '\n'


def names():
    return list(ALLOWED)
