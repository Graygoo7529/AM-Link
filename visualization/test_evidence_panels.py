from visualization.spans import evidence_panel


def test_unknown_or_old_evidence_fields_stay_unknown():
    assert evidence_panel({}) is None
    panel=evidence_panel({'packing_unit':'evidence_group','decisions':[{'ref':'memory:a'}]})
    assert panel['rows'][0]['closure']=='unknown'


def test_disclosure_panel_is_bounded_and_marks_display_counts():
    panel=evidence_panel({'disclosures':[{'origin_ref':'raw:a','shown_range':[10,510],
        'content_digest':'v','text':'x'*500}]*22,'status':'call_returned'})
    assert panel['total']==22 and panel['shown']==20
    assert len(panel['rows'][0]['text'])==350
