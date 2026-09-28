"""opencode inserts user messages of its own during auto-compaction; they never start a business run."""


def is_synthetic_user(message):
    info = (message or {}).get('info') or {}
    parts = (message or {}).get('parts') or []
    if info.get('role') != 'user' or not parts:
        return False
    return (all(p.get('type') == 'compaction' for p in parts)
            or all(p.get('type') == 'text' and p.get('synthetic') is True for p in parts))


def is_compaction_summary(message):
    info = (message or {}).get('info') or {}
    return info.get('role') == 'assistant' and (info.get('mode') == 'compaction' or info.get('agent') == 'compaction' or info.get('summary') is True)


def origin_user_id(messages, message_id):
    """Resolve a user message id to the real user message that started its turn."""
    index = next((i for i, m in enumerate(messages) if (m.get('info') or {}).get('id') == message_id), None)
    if index is None or not is_synthetic_user(messages[index]):
        return message_id
    for m in reversed(messages[:index]):
        if (m.get('info') or {}).get('role') == 'user' and not is_synthetic_user(m):
            return m['info']['id']
    return message_id
