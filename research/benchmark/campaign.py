"""Fresh frozen histories, then Answer and rubric diagnosis; one attempt per stage."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
from pathlib import Path
import time

from research.benchmark import broad
from research.benchmark.core import write_json


def record(plan_path, index, prefix, env_file):
    from research.benchmark.answer import main as answer, MODEL
    from research.benchmark.evaluate import evaluate
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    spec = plan['records'][index]
    directory = broad.ROOT/'research/benchmark/data/runs'/f'{prefix}-{index:02d}-{spec["family"]}'
    row = dict(index=index, run=directory.name)
    try:
        broad.run(plan_path,[index],prefix,env_file,no_register=True)
    except Exception as error:
        row['memory_error'] = type(error).__name__
    if (directory/'report.json').exists():
        try:
            answer(['--run',str(directory),'--env-file',str(env_file),'--model',MODEL,
                    '--answer-id','hundred','--max-questions','100',
                    '--no-view','--no-register'])
            values = evaluate(directory,env_file)
            row.update(judged=sum(r['status']=='ok' for r in values),
                       correct=sum(r.get('label')=='correct' for r in values))
        except Exception as error:
            row['answer_eval_error'] = type(error).__name__
    write_json(plan_path.parent/f'completion-{index:02d}.json',row)
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--prefix',required=True)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error('workers must be 1..4')
    plan=json.loads(args.plan.read_text(encoding='utf-8'))
    # Freeze public configuration once before spawning independent database workers.
    broad.run(args.plan,[],args.prefix,args.env_file,no_register=True)
    from research.benchmark.answer import MODEL, REASONING_EFFORT, PROMPT_VERSION
    with (args.plan.parent/'campaign.json').open('x',encoding='utf-8') as stream:
        json.dump(dict(prefix=args.prefix,workers=args.workers,started=time.time(),pid=os.getpid(),
                       plan_sha256=broad.sha(args.plan),answer_model=MODEL,answer_reasoning_effort=REASONING_EFFORT,
                       answer_prompt_version=PROMPT_VERSION,judge_model='gpt-4o-mini'),stream)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(record,args.plan,r['index'],args.prefix,args.env_file) for r in plan['records']]
        for future in as_completed(futures):
            print(json.dumps(future.result(),ensure_ascii=False),flush=True)
    # Registry writes occur serially, after the parallel runs have closed their files.
    from research.benchmark.workspace import register
    for spec in plan['records']:
        directory=broad.ROOT/'research/benchmark/data/runs'/f'{args.prefix}-{spec["index"]:02d}-{spec["family"]}'
        if (directory/'report.json').exists():
            observations=directory/'evaluated-observations.json'
            register(directory,observations=observations if observations.exists() else None)
    write_json(args.plan.parent/'status.json',broad.status(args.plan,args.prefix))


if __name__=='__main__':
    main()
