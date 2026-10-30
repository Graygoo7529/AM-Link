"""Publish a compact, standalone page for a frozen campaign and its saved answers."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def build(plan: Path, output: Path):
    root=Path(__file__).resolve().parents[1]
    analysis=json.loads((plan/'analysis.json').read_text(encoding='utf-8'))
    audit=json.loads((plan/'manual-audit.json').read_text(encoding='utf-8'))
    reviews={(r['run'],r['task_id']):r for r in audit['rows']}
    coverage=json.loads((plan/'coverage.json').read_text(encoding='utf-8'))
    rows=[]
    for q in analysis['questions']:
        directory=root/'benchmark/data/runs'/q['run']
        events=[json.loads(x) for x in (directory/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
        event=next((e for e in events if e['event']=='search' and e['dataset_task']['task_id']==q['task_id']),{})
        ann=q['annotations']
        rows.append(dict(family=q['family'],run=q['run'],task=q['task_id'],question=q['question'],
            answer=q['answer'],answer_status=q['answer_status'],machine=q['evaluation'],
            review=reviews.get((q['run'],q['task_id']),{}),
            coverage=[c for c in coverage if (c['run'],c['task_id'])==(q['run'],q['task_id'])],
            reference={k:ann[k] for k in ('answer','correct_answer','ideal_response','rubric','rubrics','preference') if k in ann},
            evidence=[r['content'] for r in event.get('results',[])]))
    payload=json.dumps(dict(rows=rows,totals=analysis['status']['totals'],families=analysis['families']),ensure_ascii=False).replace('<','\\u003c')
    page=Path(__file__).with_name('campaign.template.html').read_text(encoding='utf-8').replace('/* CAMPAIGN_DATA */',payload)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(page,encoding='utf-8')
    print(str(output.resolve()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build(a.plan,a.output)
