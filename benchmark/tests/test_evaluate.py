import pytest
from benchmark.evaluate import criteria_for, summarize_assessments
from benchmark.answer import _provider_config


def test_rubrics_and_personalized_diagnostic_do_not_claim_original_mcq_score():
    assert criteria_for({'annotations':{'rubrics':['a','b']}})==(['a','b'],'rubric')
    values, kind=criteria_for({'annotations':{'correct_answer':'teacher','expanded_persona':'SECRET'}})
    assert kind=='personalized_free_answer' and 'SECRET' not in str(values)


def test_every_criterion_required_partial_is_not_correct():
    value={'criteria':[{'number':1,'verdict':'pass'},{'number':2,'verdict':'fail'}]}
    assert summarize_assessments(value,2)['label']=='incorrect'
    value['criteria'][1]['number']=1
    with pytest.raises(ValueError):
        summarize_assessments(value,2)


def test_only_explicit_adversarial_null_answer_is_abstention():
    assert criteria_for({'annotations':{'answer':None},'attributes':{'category':'adversarial'}})[1]=='abstention'
    with pytest.raises(ValueError):
        criteria_for({'annotations':{'answer':None}})


def test_answer_resolves_current_explicit_credentials(tmp_path):
    path=tmp_path/'test.env'
    path.write_text('AML2_LLM_API_KEY=test\nAML2_LLM_BASE_URL=https://example.invalid/v1\n')
    assert _provider_config(path)==('test','https://example.invalid/v1')
