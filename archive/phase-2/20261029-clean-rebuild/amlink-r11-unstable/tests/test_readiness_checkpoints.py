import time
import pytest
from test_core_repairs import make, request
from test_staged_reflection import proposal
from amlink.errors import MemoryError
from amlink.grounding import missing_material
from amlink.reflection import prepare_mutation
from amlink.relation_choices import connection_menu, resolve_connections
from amlink.evidence import fragment
from amlink.drafts import review_payload
from amlink.intake import valid_instruction_quote
from amlink.projection import Choices


def test_checkpoint_identity_cannot_be_overwritten_with_same_new_label(make):
    engine, provider = make(reflection_threshold=1)
    def decide(purpose, payload):
        if payload['step'] == 0:
            return 'reflection_items', proposal(payload)
        raise MemoryError('provider_timeout', 504)
    provider.decide = decide
    engine.add(request('a', ['Speaker: Maya\nI like tea.']))
    plan = engine.store.reflection_plan('u')
    context = plan['progress']['0']['context']
    # A content repair using the same deterministic new label must not bypass
    # immutability now that independent nodes are already committed.
    args = {'items': [{'ref':'new:tea','kind':'fact','text':'Maya likes coffee.',
                       'source_refs':[engine.store.raw('u')[0]['ref']]}]}
    with pytest.raises(MemoryError, match='mutation_fact_overwrite'):
        prepare_mutation(args, user='u', request_id=plan['plan_id'], number=0, context=context, store=engine.store)
    assert engine.store.maintenance_summary('u')['groups_with_committed_nodes'] == 1
    assert engine.store.state('u')['settled_through'] == 0


def test_checkpoint_is_not_a_fake_read_receipt(make):
    engine, provider = make(reflection_threshold=1)
    provider.decide = lambda purpose, p: ('reflection_items', proposal(p)) if p['step']==0 else ('reflection_relations', {'links':[]})
    engine.add(request('a', ['Speaker: Maya\nI like tea.']))
    fact = next(n for n in engine.store.nodes('u') if n['kind']=='fact')
    person = next(n for n in engine.store.nodes('u') if n['kind']=='person')
    context = dict(items={fact['ref']:fact,person['ref']:person}, committed_node_refs=[fact['ref'],person['ref']],
                   last_visible=[], read_ranges=[])
    args = {'links':[dict(from_ref=fact['ref'],to_ref=person['ref'],relation='about',source_refs=fact['source_refs'])]}
    assert len(missing_material(args, context)) == 2


def test_relation_menu_never_offers_self_or_wrong_direction():
    nodes = [dict(ref='new:f', kind='fact',source_refs=['raw:a']),
             dict(ref='memory:p', kind='person',source_refs=['raw:a']),
             dict(ref='memory:ep',kind='episode',source_refs=['raw:b'])]
    menu = connection_menu(nodes, ['new:f'])
    assert [(m['from_ref'],m['relation'],m['to_ref']) for m in menu] == [('new:f','about','memory:p')]
    with pytest.raises(MemoryError, match='position_invalid'):
        resolve_connections({'links':[dict(connection_position=12,source_refs=['raw:a'],support='Unsupported.')]}, menu)


def test_review_carries_actual_read_endpoints_across_projection(make, monkeypatch):
    engine, _ = make(mode='raw')
    left = dict(ref='memory:f', kind='fact', text='Maya likes tea.', source_refs=['raw:a'])
    right = dict(ref='memory:p', kind='person', text='Maya is the speaker.', source_refs=['raw:a'])
    args = {'links':[dict(from_ref=left['ref'],to_ref=right['ref'],relation='about',source_refs=['raw:a'])]}
    context = dict(items={n['ref']:n for n in (left,right)},
                   last_visible=[fragment(n,0,len(n['text'])) for n in (left,right)])
    seen = []
    def review(engine, arguments, projected, working, deadline, context, tool):
        seen.append(review_payload(arguments,projected,working))
        return arguments
    monkeypatch.setattr('amlink.engine.review_draft',review)
    engine._review_draft(args,{},[],time.monotonic()+10,context=context)
    assert {n['ref']:n['text'] for n in seen[0]['endpoints']} == {n['ref']:n['text'] for n in (left,right)}
    # Stored material alone, or an obsolete version receipt, grants no access.
    context['last_visible'][0]['content_digest'] = 'obsolete'
    with pytest.raises(MemoryError,match='reflection_review_endpoint_missing'):
        engine._review_draft(args,{},[],time.monotonic()+10,context=context)


def test_new_group_unpins_previous_groups_reading_without_erasing_memory(make):
    engine, _ = make(mode='raw')
    engine.add(request('a',['Maya likes tea.']))
    node = engine.store.nodes('u')[0]
    page = {**fragment(node,0,len(node['text'])),'item_ref':node['ref']}
    engine.store.save_workspace('u',context={'format_version':2,'references':{},'items':{node['ref']:node},
        'edges':[],'disclosures':[page],'pinned':[page['fragment_id']], 'read_ranges':[page]})
    context = engine._reflection_context('u',engine.store.raw('u'),time.monotonic()+10)
    assert not context.get('pinned')
    assert context.get('read_ranges')
    assert engine.store.get('u',node['ref'])


@pytest.mark.parametrize('message', ['我不会忘记那些一起学习的时光。', 'I will never forget our trip.',
    'The book says "Forget my address." It is fiction.',
    '{"subject":"李华","dialogue":["我不会忘记导师。","请删除旧地址。"]}'])
def test_noncommands_cannot_trigger_destructive_intake_even_with_bad_model(make, message):
    engine, provider = make(mode='raw')
    engine.add(request('old',['My old address is Elm Street.']))
    provider.tool = lambda *args: pytest.fail('Noncommands must not enter the authorization model')
    engine.add(request('data',[message]))
    assert len(engine.store.raw('u')) == 2
    assert not engine.store.rows('select * from blocks')


def test_forget_quote_requires_original_complete_command():
    assert valid_instruction_quote('Speaker: Maya\nPlease forget my old address.', 'Please forget my old address.')
    assert valid_instruction_quote('请删除我的旧地址。', '请删除我的旧地址。')
    assert not valid_instruction_quote('Please forget my old address.', 'forget my old address')
    assert not valid_instruction_quote('Please forget nothing; do not erase my address.', 'Please forget nothing;')


def test_reflection_cannot_bypass_intake_forget_authorization(make):
    engine, _ = make(mode='raw')
    engine.add(request('old',['I will never forget my mentor.']))
    row=engine.store.raw('u')[0]
    with pytest.raises(MemoryError,match='forget_intake_only'):
        prepare_mutation({'forget':[{'instruction_refs':[row['ref']],'source_refs':[row['ref']],'memory_refs':[]}]},
            user='u',request_id='x',number=0,context={'sources':[row],'new_refs':[row['ref']]},store=engine.store)


def test_old_type_pairs_do_not_create_an_empty_current_group_tool(make):
    engine, _ = make(mode='raw')
    nodes = [dict(ref='memory:ep',kind='episode',source_refs=['raw:old']),
             dict(ref='memory:old',kind='fact',source_refs=['raw:old']),
             dict(ref='memory:new',kind='person',source_refs=['raw:new'])]
    # The old episode/fact pair is legal but unrelated to the checkpoint;
    # the new identity is outside the actual visible choices.
    choices = Choices.freeze(nodes[:2], {n['ref']:[] for n in nodes[:2]})
    context = {'items':{n['ref']:n for n in nodes}, 'pending_mutation':{'items':[]},
               'committed_node_refs':['memory:new']}
    assert engine._relation_menu(context,choices) == []


def test_empty_connection_menu_advances_without_an_empty_only_model_call(make, monkeypatch):
    engine, provider = make(reflection_threshold=1)
    def decide(purpose, payload):
        assert payload['step'] == 0
        return 'reflection_items', proposal(payload)
    provider.decide = decide
    monkeypatch.setattr(engine,'_relation_menu',lambda context, choices: [])
    assert engine.add(request('a',['Speaker: Maya\nI like tea.']))['success']
    assert len(engine.store.nodes('u')) == 3
    assert engine.store.state('u')['settled_through'] == 1


def test_unchanged_failed_work_does_not_resume_for_unread_keyword_matches(make, monkeypatch):
    from amlink.local_reflection import freeze_groups
    engine, _ = make(mode='raw')
    engine.add(request('a',['Maya likes tea.']))
    source = engine.store.raw('u')[0]
    plan = freeze_groups({'groups':[dict(title='tea',question='tea',positions=[0])]},[source])
    engine.store.freeze_plan('u',plan)
    attempts=[]
    def fail(*args):
        attempts.append(1)
        raise MemoryError('model_tool_schema_invalid',502)
    monkeypatch.setattr(engine,'_run_reflection_group',fail)
    req=request('b',['More words about tea.'])
    engine._run_reflection(req,[],time.monotonic(),engine.store.reflection_plan('u'))
    monkeypatch.setattr(engine.store,'lexical',lambda *a,**kw: [{'ref':'memory:unread','text':'tea','status':'active'}])
    engine._run_reflection(req,[],time.monotonic(),engine.store.reflection_plan('u'))
    assert len(attempts)==1
    saved=engine.store.reflection_plan('u'); group={**saved['groups'][0], 'plan_id':saved['plan_id'],'index':0}
    engine.store.group_progress('u',group,{**saved['progress']['0'],'versions':{source['ref']:'obsolete'}})
    engine._run_reflection(req,[],time.monotonic(),engine.store.reflection_plan('u'))
    assert len(attempts)==2


@pytest.mark.parametrize('relation',['about','contains','contradicts','same_event_as','supersedes'])
def test_relation_reviews_share_fields_without_allowing_fake_replacement_quotes(relation):
    from amlink.drafts import review_schema,decode_review
    payload={'units':[{'position':0,'kind':'relation','source_positions':[0],
                      'proposal':{'relation':relation,'from_ref':'memory:a','to_ref':'memory:b'}}]}
    fields=review_schema(payload)['properties']['u0']['properties']
    assert set(fields)=={'action','detail','evidence_positions','replacement_quote'}
    wire={'u0':{'action':'drop','detail':'The originals do not establish this connection.',
                'evidence_positions':[0],'replacement_quote':None},'remaining_work':[],
          'no_change_reason':'The proposed edge is unnecessary.'}
    assert decode_review(payload,wire)['reviews'][0]['action']=='drop'
    if relation!='supersedes':
        wire['u0']['replacement_quote']='An invented replacement'
        with pytest.raises(MemoryError,match='reflection_review_invalid'):
            decode_review(payload,wire)
