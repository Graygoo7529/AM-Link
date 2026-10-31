"""Exact reading ranges and compact presentation, shared by Select and delivery."""
from __future__ import annotations
import re
from .text import ranges, source_time, tokens, excerpt


def readable_ranges(text,excluded=()):
    start=0
    for left,right in sorted(excluded):
        if start<left:yield start,left
        start=max(start,right)
    if start<len(text):yield start,len(text)


def headings(text):
    result=[]; offset=0
    for line in text.splitlines(keepends=True):
        value=line.strip()
        if value and len(value)<=220 and (re.match(r'^#{1,6}\s+\S',value)
            or len(value)<=90 and value.endswith((':','：'))
            or re.match(r'^.{0,60}(?:#|№)\d{3,}\b',value)):
            result.append((offset,value))
        offset+=len(line)
    return result


def passage_ranges(text):
    """Lossless index slices, never crossing an explicit section start."""
    boundaries=sorted({0,len(text),*(start for start,_ in headings(text))})
    for left,right in zip(boundaries,boundaries[1:]):
        for a,b in ranges(text[left:right]):
            yield left+a,left+b


def metadata(text,start,end,region):
    left,right=region
    anchors=[(left+a,t) for a,t in headings(text[left:right]) if left+a<=start]
    if anchors:
        pos,title=anchors[-1]
        anchor={'start':pos,'end':pos+len(text[pos:].splitlines()[0]),'text':title,'kind':'heading'}
    else:
        # A quoted opening is an original locator, not an inferred event title.
        opening=text[left:right].splitlines()[0][:180] if text[left:right] else ''
        anchor={'start':left,'end':left+len(opening),'text':opening,'kind':'opening'}
    return dict(source_length=len(text),read_region=[left,right],anchor=anchor)


def index_text(row):
    text=row['text'];anchor=row['anchor']['text']
    if text.startswith(anchor):return text
    prefix=anchor.encode('utf-8')[:max(0,5999-len(text.encode('utf-8')))].decode('utf-8',errors='ignore')
    return prefix+'\n'+text


def sentence_units(row):
    """Fine original boundaries for range masking, without paraphrasing."""
    text=row['text']; points=[0]
    for match in re.finditer(r'\n\s*\n',text):
        points.append(match.end())
    points.append(len(text))
    result=[]
    for left,right in zip(points,points[1:]):
        paragraph=text[left:right]; cuts=[0]
        for match in re.finditer(r'(?<=[.!?。！？])(?:[ \t]+|\n)|\n(?=\s*(?:[-*•]|\d+[.)])\s)',paragraph):
            # A numbered-list label is attached to its sentence, not standalone evidence.
            if re.search(r'(?:^|\n)\s*\d+\.$',paragraph[:match.start()]):continue
            if match.end()>cuts[-1]:cuts.append(match.end())
        cuts.append(len(paragraph))
        for a,b in zip(cuts,cuts[1:]):
            value=paragraph[a:b]
            if value.strip():
                result.append(dict(row=row,start=row['start']+left+a,end=row['start']+left+b,text=value))
    return result


def units(row):
    """Continuous original blocks, including short paragraphs and their whitespace."""
    result=[]
    boundaries={row['start']+a for a,_ in headings(row['text'])}
    points=sorted({0,len(row['text']),*(a-row['start'] for a in boundaries),
                   *(m.end() for m in re.finditer(r'\n[ \t]*\n',row['text']))})
    parts=[]
    for a,b in zip(points,points[1:]):
        text=row['text'][a:b]
        if not text.strip():continue
        if len(text)<=600:
            parts.append(dict(row=row,start=row['start']+a,end=row['start']+b,text=text))
        else:
            parts.extend(u|{'row':row} for u in sentence_units(row|{'text':text,'start':row['start']+a}))
    for unit in parts:
        if (result and unit['end']-result[-1]['start']<=600
                and not any(result[-1]['start']<a<=unit['start'] for a in boundaries)):
            result[-1]['end']=unit['end']
            result[-1]['text']=row['text'][result[-1]['start']-row['start']:unit['end']-row['start']]
        else:result.append(dict(unit))
    # Whitespace remains original content; attach gaps to the preceding block.
    for i,unit in enumerate(result):
        unit['end']=result[i+1]['start'] if i+1<len(result) else row['end'] if 'end' in row else row['start']+len(row['text'])
        unit['text']=row['text'][unit['start']-row['start']:unit['end']-row['start']]
    return result


def nearby(row,corpus):
    """Immediate ranges, or boundary messages in this session, across Add packets."""
    episodes=[r for r in corpus if r['kind']=='episode' and r['session_id']==row['session_id']]
    same=sorted((r for r in episodes if r['sources']==row['sources']),key=lambda r:r['start'])
    result=[]
    for r in same:
        if r['end']==row['start'] or r['start']==row['end']:
            result.append(r)
    # A gap is a non-readable range, not permission to jump across forgotten text.
    if row['start']==0:
        previous=[r for r in episodes if r.get('sequence',0)<row.get('sequence',0)]
        if previous:
            seq=max(r.get('sequence',0) for r in previous)
            result.append(max((r for r in previous if r.get('sequence',0)==seq),key=lambda r:r['end']))
    if row['end']==row.get('source_length',row['end']):
        following=[r for r in episodes if r.get('sequence',0)>row.get('sequence',0)]
        if following:
            seq=min(r.get('sequence',0) for r in following)
            result.append(min((r for r in following if r.get('sequence',0)==seq),key=lambda r:r['start']))
    return list({r['ref']:r for r in result}.values())


def header(row):
    anchor=row.get('anchor',{})
    # An empty original opening has an empty range; never substitute a generated
    # display label while keeping that zero-length range as if it were a quote.
    title=anchor.get('text',row.get('title',''))
    context=(f"Original {anchor.get('kind','opening')}: {title}\n" if title else '')
    return context+f"Message role: {row['role']}; said at {source_time(row['time'])} (not an event date)."


def preview(row,question,limit=300):
    """One verbatim query-focused excerpt; never a generated claim or full reading."""
    blocks=units(row); terms=set(tokens(question))
    best=max(blocks,key=lambda u:len(terms.intersection(tokens(u['text']))),default={'text':row['text']})
    return excerpt(best['text'],limit)


def unit_key(unit):
    return (unit['row']['ref'],unit['start'],unit['end'])


def model_ref(unit):
    """Stable, semantic reference for one exact original range.

    The local position used by a Select tool is intentionally ephemeral.  This
    reference is safe to repeat in the narrative and the observation ledger so
    that a later Select can recognize the same source range.
    """
    row=unit['row']
    base=row['ref'].rsplit('#',1)[0]
    return f"{base}#{unit['start']}:{unit['end']}"


def delivery_cost(unit):
    """Conservative per-unit delivery estimate used before Select.

    A final package shares a passage header between units, so this is an
    upper-bound estimate rather than a promise of the exact packed size.
    """
    return len(render_group([unit],1))+64


_CONTEXT_PRONOUN=re.compile(
    r"(?:\b(?:it|they|them|he|she|her|his|their|this|that|these|those|another|one)\b|"
    r"它|他|她|其|这|那|这些|那些|上述|这个|那个)",
    re.I,
)
_CONTEXT_OPENING=re.compile(
    r"^(?:yes|yeah|no|i\s+(?:did|do|have|had|was|am|went|got|like|prefer|remember)|"
    r"we\s+(?:did|have|had|were|went)|是的|不是|我(?:有|在|去|喜欢|记得)|我们)",
    re.I,
)


def needs_context(text):
    """Whether an original unit is likely to need its immediately preceding unit."""
    value=' '.join(text.strip().split())
    if not value:
        return False
    return bool(_CONTEXT_PRONOUN.search(value) or _CONTEXT_OPENING.search(value))


def context_closure(selected,context=()):
    """Add the nearest preceding original unit for unresolved conversational context.

    The same episode is preferred. If it has no preceding unit, an already
    disclosed, immediately preceding episode in the same session may supply
    one unit. Returned additions are exact source slices and carry a reason so
    observation can distinguish model choice from deterministic context repair.
    """
    result=list(selected)
    known={unit_key(unit) for unit in result}
    additions=[]
    for unit in list(selected):
        if not needs_context(unit['text']):
            continue
        all_units=units(unit['row'])
        index=next((i for i,candidate in enumerate(all_units)
                    if unit_key(candidate)==unit_key(unit)),None)
        scope='same_episode'
        if index is not None and index>0:
            previous=all_units[index-1]
        else:
            episodes=[row for row in context if row.get('kind')=='episode'
                      and row.get('ref')!=unit['row'].get('ref')
                      and row.get('session_id')==unit['row'].get('session_id')]
            neighbors=nearby(unit['row'],episodes)
            previous_rows=[row for row in neighbors
                           if row.get('end',0)<=unit['row'].get('start',0)
                           or row.get('sequence',0)<unit['row'].get('sequence',0)]
            if not previous_rows:
                continue
            previous_row=max(previous_rows,key=lambda row:(row.get('sequence',0),row.get('end',0)))
            previous=units(previous_row)[-1]
            scope='adjacent_episode'
        key=unit_key(previous)
        if key in known:
            continue
        known.add(key)
        additions.append(previous|{'selection_reason':'context_closure',
                                   'closure_for':unit_key(unit),
                                   'closure_scope':scope})
    result.extend(additions)
    return result,additions


def ledger(unit,position,state='read'):
    row=unit['row']
    result=dict(position=position,state=state,ref=row['ref'],sources=row['sources'],
                start=unit['start'],end=unit['end'],sequence=row.get('sequence'),role=row['role'],time=row['time'])
    if unit.get('selection_reason'):
        result['selection_reason']=unit['selection_reason']
        result['closure_for']=unit.get('closure_for')
        result['closure_scope']=unit.get('closure_scope')
    return result


def render_group(group,position):
    row=group[0]['row']; ordered=sorted(group,key=lambda u:u['start'])
    pieces=[]; last=None
    for u in ordered:
        if last is not None and last!=u['start']:pieces.append('\n[unselected original text between ranges]\n')
        pieces.append(u['text']);last=u['end']
    return f"Evidence {position}\n{header(row)}\nSelected original text:\n"+''.join(pieces)


def pack(selected,top_k,budget):
    """Preserve model group priority; copy verified units, never cut prose to fit."""
    groups={}; omissions=[]; total=0
    for unit in selected:
        ref=unit['row']['ref']
        if ref not in groups and len(groups)>=top_k:
            omissions.append({'ref':ref,'start':unit['start'],'end':unit['end'],'reason':'top_k'});continue
        old=groups.get(ref,[])
        if any(unit_key(u)==unit_key(unit) for u in old):continue
        position=list(groups).index(ref)+1 if ref in groups else len(groups)+1
        before=len(render_group(old,position)) if old else 0
        after=len(render_group(old+[unit],position))
        extra=64 if not old else 0 # bounded natural chronology link, computed after selection
        if total+after-before+extra>budget:
            omissions.append({'ref':ref,'start':unit['start'],'end':unit['end'],'reason':'characters'});continue
        groups[ref]=old+[unit];total+=after-before+extra
    order=sorted(groups,key=lambda ref:(groups[ref][0]['row'].get('sequence',0),groups[ref][0]['start']))
    ranks={ref:i for i,ref in enumerate(groups,1)}
    chronology={ref:(f"Recorded before Evidence {ranks[order[i+1]]} in this history." if i+1<len(order)
                     else 'Latest of these returned messages in the recorded history.') for i,ref in enumerate(order)}
    data=[]
    for i,(ref,group) in enumerate(groups.items(),1):
        content=render_group(group,i).replace('Selected original text:',chronology[ref]+'\nSelected original text:',1)
        data.append(dict(id=ref,content=content,score=1/i,created_at=group[0]['row']['created_at']))
    return data,omissions
