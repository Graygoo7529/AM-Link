from test_core_repairs import make, request
from amlink.packing import freeze_pack
from amlink.packing_experiment import compare
from amlink.errors import MemoryError
import pytest


def test_offline_comparison_uses_one_tool_and_frozen_evidence(make):
    engine, provider = make(mode='raw')
    engine.add(request('a',['The notebook is blue.']))
    frozen = freeze_pack(engine.store,'u','notebook',engine.store.nodes('u'),{},engine.config)
    provider.decide = lambda purpose,payload: ('packing_comparison', {'groups':[{'position':0,'fragment_positions':[0]}]})
    result = compare(engine, frozen, 1)
    assert result['model_calls']==1
    assert result['llm']['data']==result['deterministic']['data']
    assert len(provider.calls)==1
    provider.decide = lambda *a: ('packing_comparison', {'groups':[{'position':0,'fragment_positions':[99]}]})
    with pytest.raises(MemoryError,match='packing_selection_invalid'):
        compare(engine, frozen, 1)
