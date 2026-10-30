"""Presentation boundary checks with synthetic content only."""
import hashlib
import json
from unittest.mock import patch

import pytest

from research.web.build import artifact_view, safe_child, script_json, validate_studies, run_payload
from research.web.test_imports import fixture, span_fixture


def test_script_payload_cannot_close_script():
    value = {"text": '</script><script>alert("source text")</script>\u2028'}
    encoded = script_json(value)
    assert '<' not in encoded and '\u2028' not in encoded
    assert json.loads(encoded) == value


def test_artifact_projection_keeps_text_and_identity(tmp_path):
    value = {"data": [{"index": 0, "embedding": [0.1, 0.2]}], "usage": {"total_tokens": 4}}
    path = tmp_path / 'embedding.json'
    path.write_text(json.dumps(value), encoding='utf8')
    reference = {"artifact": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    projected = artifact_view(tmp_path, reference)
    assert projected['projected'] and '2 维' in projected['value']['data'][0]['embedding']
    assert projected['value']['usage'] == value['usage']
    path.write_text('{"data":[]}', encoding='utf8')
    with pytest.raises(ValueError, match='digest'):
        artifact_view(tmp_path, reference)
    with pytest.raises(ValueError, match='outside'):
        safe_child(tmp_path, '../external.json')


def test_study_identity_and_completeness():
    row = {'run_id':'r','record_id':'record','task_id':'q','dataset_pack_sha256':'a'*64}
    study = {'run_id':'r','dataset_pack_sha256':'a'*64,'theory':'Need both facts',
        'observed':'One returned','limits':'Synthetic'}
    catalog = {'cases':{'c':{'data':{'record':'record','task':'q'},'studies':[study]}}}
    validate_studies(catalog, [row])
    study['dataset_pack_sha256'] = 'b'*64
    with pytest.raises(ValueError, match='pack mismatch'):
        validate_studies(catalog,[row])
    study['run_id']='other'
    with pytest.raises(ValueError, match='unknown study'):
        validate_studies(catalog,[row])


@pytest.mark.parametrize("value", [None, [], "", 0])
def test_failed_call_artifact_preserves_non_object_result(tmp_path, value):
    path = tmp_path / 'result.json'
    path.write_text(json.dumps(value), encoding='utf8')
    reference = {"artifact": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    result = artifact_view(tmp_path, reference)
    assert result['value'] == value
    assert not result['projected']


def test_page_payload_preserves_complete_api_evidence(tmp_path):
    directory=tmp_path/'run';directory.mkdir()
    digest=fixture(directory,task_count=2);span_fixture(directory,digest)
    registration=dict(directory='run',kind='fixture',dataset_pack_sha256=digest)
    with patch('research.web.build.ROOT',tmp_path):
        payload=run_payload(registration,{},[])
    original=[json.loads(s) for s in (directory/'trace.jsonl').read_text(encoding='utf8').splitlines()]
    assert len(payload['queries'])==2
    assert payload['queries'][0]['results']==next(e['results'] for e in original if e['event']=='search')
    assert payload['adds']==[e for e in original if e['event']=='add']
    assert payload['events'] and payload['history'][0]['id']=='u'
