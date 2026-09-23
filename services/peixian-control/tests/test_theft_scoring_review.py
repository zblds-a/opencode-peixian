"""Prompt/corpus assertions for native intent review v4 scoring rules."""
from shared import native_intent_review as review
from evaluation.theft_scoring_cases import cases


def test_reviewer_version_and_scoring_codes():
    assert review.VERSION == 'native-intent-context-v4'
    text = review.PROMPT
    assert 'scoring_requested' in text
    assert 'unrequested_scoring' in text
    assert 'conclusive_scoring' in text
    assert 'matched_request' in text
    # retain existing privacy/binding rules
    assert 'identity_binding' in text
    assert 'person_ref' in text
    assert 'contract_defaults' in text


def test_p23_p38_corpus_covers_scoring_paths():
    ids = {c['id'] for c in cases}
    assert ids == {f'P{n}' for n in range(23, 39)}
    assert any(c['expect']['reason_code'] == 'unrequested_scoring' for c in cases)
    assert any(c['expect']['reason_code'] == 'conclusive_scoring' for c in cases)
    assert any(c['scoring_requested'] and c['expect']['verdict'] == 'allow' for c in cases)
