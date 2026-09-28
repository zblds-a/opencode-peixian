"""Map scoped person references back to identity numbers in police-facing text only.

The model keeps seeing person-... references; only rendered answers are rewritten.
"""
import re

REF = re.compile(r'person-[0-9a-f]{32}')
IDENTITY = re.compile(r'(?<![0-9])[0-9]{17}[0-9Xx](?![0-9])')


def _pair(raw, public, out):
    if isinstance(public, dict) and isinstance(raw, dict):
        for key, value in public.items():
            if key in raw:
                _pair(raw[key], value, out)
    elif isinstance(public, list) and isinstance(raw, list) and len(public) == len(raw):
        for a, b in zip(raw, public):
            _pair(a, b, out)
    elif isinstance(public, str) and isinstance(raw, str):
        refs, values = REF.findall(public), IDENTITY.findall(raw)
        if refs and len(refs) == len(values):
            for ref, value in zip(refs, values):
                out.setdefault(ref, value.upper())


def collect(snapshot):
    """Reference-to-identity pairs from frozen call identities and raw/public response pairs."""
    out = {}
    for call in (snapshot.get('native_calls') or {}).values():
        for ref, value in ((call.get('frozen') or {}).get('identities') or {}).items():
            if isinstance(ref, str) and REF.fullmatch(ref) and isinstance(value, str) and IDENTITY.fullmatch(value):
                out[ref] = value.upper()
    for entry in ((snapshot.get('provider_state') or {}).get('modules') or {}).values():
        if not isinstance(entry, dict) or entry.get('status') != 'completed':
            continue
        raw = {r.get('source_ref'): r for r in (entry.get('response') or {}).get('records') or [] if isinstance(r, dict)}
        for record in (entry.get('public_response') or {}).get('records') or []:
            if isinstance(record, dict) and record.get('source_ref') in raw:
                _pair(raw[record['source_ref']].get('fields'), record.get('fields'), out)
    return out


def mapping(snapshot):
    history = (snapshot.get('table_answer_policy') or {}).get('display_identities') or {}
    return {**history, **collect(snapshot)}


def reveal(text, identities):
    if not isinstance(text, str) or not identities:
        return text
    return REF.sub(lambda m: identities.get(m.group(0), m.group(0)), text)
