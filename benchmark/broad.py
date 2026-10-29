"""Frozen full-history research suite. Preparation never calls a model."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

from benchmark.datasets import build_retrieval_manifest
from benchmark.core import write_json
from dataset.pack import load_pack
from dataset.selection import select_pack

ROOT = Path(__file__).resolve().parents[1]
SPECS = [
    ('locomo', ['locomo-full'], 4, 10),
    ('longmemeval', ['longmemeval-research'], 7, 1),
    ('perltqa', ['perltqa-zh-full'], 6, 4),
    ('personamem', ['personamem-v2-research'], 2, 6),
    ('beam', ['beam-smoke', 'beam-update-cases'], 2, 6),
    ('clbench-life', ['clbench-life-smoke', 'clbench-life-extra'], 5, 1),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files():
    return sorted(p for folder in ('amlink', 'benchmark', 'dataset')
                  for p in (ROOT / folder).glob('*.py'))


def source_hashes():
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in source_files()}


def stable_key(seed, value):
    return hashlib.sha256(f'{seed}:{value}'.encode()).hexdigest()


def choose_tasks(record, number, seed):
    """Balance published categories, never select using answers or method scores."""
    groups = defaultdict(list)
    for task in record['tasks']:
        if not isinstance(task.get('input', {}).get('text'), str) or not task['input']['text'].strip():
            continue
        attrs = task.get('attributes', {})
        category = str(attrs.get('category', attrs.get('question_type', 'general')))
        groups[category].append(task)
    groups = {k: sorted(v, key=lambda t: stable_key(seed, record['id'] + ':' + t['id']))
              for k, v in sorted(groups.items())}
    selected = []
    while len(selected) < number and any(groups.values()):
        for tasks in groups.values():
            if tasks and len(selected) < number:
                selected.append(tasks.pop(0)['id'])
    if len(selected) != number:
        raise ValueError(f"record {record['id']} lacks {number} separated tasks")
    return selected


def prepare(output, seed=20261029):
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for family, names, count, per_record in SPECS:
        candidates = []
        for name in names:
            path = ROOT / 'dataset/data/prepared' / (name + '.json')
            pack = load_pack(path)
            for record in pack['records']:
                candidates.append((path, pack, record))
        candidates.sort(key=lambda v: stable_key(seed, family + ':' + v[2]['id']))
        if len({v[2]['id'] for v in candidates}) < count:
            raise ValueError(f'not enough independent record IDs for {family}')
        for path, pack, record in candidates[:count]:
            selected = choose_tasks(record, per_record, seed)
            sample = select_pack(pack, record_ids=[record['id']], task_ids=selected, scope='full')
            manifest = build_retrieval_manifest(sample, chunk_size=20, top_k=100)
            index = len(records)
            pack_path = output / f'{index:02d}-{family}.json'
            write_json(pack_path, sample)
            adds = manifest['cases'][0]['adds']
            records.append(dict(index=index, family=family, record_id=record['id'], tasks=selected,
                pack=pack_path.name, pack_sha256=sha(pack_path), source_pack=path.relative_to(ROOT).as_posix(),
                source_sha256=sha(path), adds=len(adds), questions=len(selected),
                original_chars=sum(len(m['content']) for a in adds for m in a['messages']),
                max_request_chars=max(sum(len(m['content']) for m in a['messages']) for a in adds),
                scope='full', exposure='public research; not certified unseen'))
    total = sum(r['questions'] for r in records)
    if total != 100 or len(records) != 26:
        raise ValueError('suite must contain exactly 26 records and 100 questions')
    sources = {p.relative_to(ROOT).as_posix(): p.read_text(encoding='utf-8') for p in source_files()}
    write_json(output / 'method-snapshot.json', {'files': sources, 'sha256': source_hashes()})
    plan = dict(version=1, seed=seed, source_sha256=source_hashes(), records=records,
        questions=total, adds=sum(r['adds'] for r in records),
        adapter=dict(chunk_size=20, top_k=100, max_add_words=2000),
        budget_per_record=dict(max_provider_calls=4000, max_provider_input_chars=100000000),
        semantics='All selected history is added before Search; annotations are evaluation-only; no internal retry.')
    write_json(output / 'suite.json', plan)
    return plan


def run(plan_path, indices, prefix, env_file):
    from amlink.config import load_env_file, Config
    from benchmark.study import main as study
    import os
    import shutil
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if plan['source_sha256'] != source_hashes():
        raise ValueError('source changed since suite freeze; prepare a new version, do not mix results')
    load_env_file(env_file)
    for key, value in plan['budget_per_record'].items():
        os.environ['AML2_' + key.upper()] = str(value)
    config = Config.from_env()
    if config.mode != 'graph' or not config.embedding_enabled or not config.search_model:
        raise ValueError('suite requires the complete default method')
    # Freeze all non-secret options too: separate workers must use one configuration.
    config_path = plan_path.parent / 'run-config.json'
    public = config.public()
    try:
        with config_path.open('x', encoding='utf-8') as f:
            json.dump(public, f, ensure_ascii=False, sort_keys=True)
    except FileExistsError:
        if json.loads(config_path.read_text(encoding='utf-8')) != public:
            raise ValueError('configuration differs from this suite run')
    for index in indices:
        if plan['source_sha256'] != source_hashes():
            raise ValueError('source changed between records; stop before another database is started')
        row = next(r for r in plan['records'] if r['index'] == index)
        pack_path = plan_path.parent / row['pack']
        if sha(pack_path) != row['pack_sha256']:
            raise ValueError('frozen dataset pack changed')
        run_id = f'{prefix}-{index:02d}-{row["family"]}'
        print(json.dumps({'starting': run_id, 'adds': row['adds'], 'questions': row['questions']}, ensure_ascii=False), flush=True)
        directory = ROOT / 'benchmark/data/runs' / run_id
        if directory.exists():
            raise ValueError('run already exists; choose a new prefix, never overwrite or resume a study')
        try:
            study(['--dataset-pack', str(pack_path), '--target', 'native', '--factory', 'amlink.native:factory',
                   '--run-id', run_id, '--system-name', 'AM-Link full-history readiness', '--system-version', '0.2.1-ready29',
                   '--chunk-size', '20', '--top-k', '100', '--no-view'])
        finally:
            if directory.exists():
                shutil.copyfile(plan_path.parent / 'method-snapshot.json', directory / 'method-source-snapshot.json')
                write_json(directory / 'suite-record.json', {**row, 'suite_sha256': sha(plan_path)})
        # An incomplete intake is a diagnostic failure, never a complete-history success.
        report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
        if report['summary']['add']['success_rate'] != 1:
            raise RuntimeError(f'{run_id}: incomplete Add history; stop this worker without retry')


def _completed_lines(path):
    if not path.exists():
        return []
    raw = path.read_text(encoding='utf-8')
    lines = raw.splitlines()
    # Writers flush complete JSONL records. A trailing partial concurrent write
    # is not a completed operation and must not make status unusable.
    if raw and not raw.endswith('\n'):
        lines = lines[:-1]
    return [json.loads(line) for line in lines if line.strip()]


def status(plan_path, prefix):
    """Read-only accounting: unstarted and incomplete histories remain explicit."""
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    rows = []
    for row in plan['records']:
        directory = ROOT / 'benchmark/data/runs' / f'{prefix}-{row["index"]:02d}-{row["family"]}'
        report_path = directory / 'report.json'
        out = {k: row[k] for k in ('index','family','record_id','adds','questions')}
        out.update(run=directory.name, state='not_started', add_success=0, search_success=0,
                   model_attempts=0, input_tokens=0, output_tokens=0)
        if directory.exists():
            out['state'] = 'unfinished'
            calls = _completed_lines(directory / 'trace.jsonl')
            out['add_success'] = sum(e['event'] == 'add' and e['ok'] for e in calls)
            out['search_success'] = sum(e['event'] == 'search' and e['ok'] for e in calls)
            if (directory / 'interrupted.json').exists():
                out['state'] = 'interrupted'
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding='utf-8'))['summary']
            out.update(add_success=report['add']['success'], search_success=report['search']['success'],
                state='complete' if report['add']['success'] == row['adds'] and report['search']['success'] == row['questions'] else 'failed',
                retrieval=report['retrieval']['overall'])
        trace = directory / 'observability.jsonl'
        if trace.exists():
            for event in _completed_lines(trace):
                if event['operation'] == 'model':
                    out['model_attempts'] += 1
                    for key in ('input_tokens','output_tokens'):
                        out[key] += (event.get('model') or {}).get(key) or 0
        rows.append(out)
    return {'records':rows, 'totals':{key:sum(r[key] for r in rows) for key in
        ('adds','questions','add_success','search_success','model_attempts','input_tokens','output_tokens')},
        'complete_histories':sum(r['state']=='complete' for r in rows),
        'meaning':'Complete means all API operations succeeded, not that Reflection, evidence or answers are correct.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--output', type=Path, required=True)
    prep.add_argument('--seed', type=int, default=20261029)
    execute = sub.add_parser('run')
    execute.add_argument('--plan', type=Path, required=True)
    execute.add_argument('--indices', type=int, nargs='+', required=True)
    execute.add_argument('--prefix', required=True)
    execute.add_argument('--env-file', type=Path, required=True)
    summary = sub.add_parser('status')
    summary.add_argument('--plan', type=Path, required=True)
    summary.add_argument('--prefix', required=True)
    summary.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        plan = prepare(args.output, args.seed)
        print(json.dumps({'plan': str(args.output / 'suite.json'), 'records': len(plan['records']),
                          'questions': plan['questions'], 'adds': plan['adds']}))
    elif args.command == 'run':
        run(args.plan, args.indices, args.prefix, args.env_file)
    else:
        result = status(args.plan,args.prefix)
        if args.output:
            write_json(args.output,result)
        print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
