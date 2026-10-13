"""同模型5/15/30秒诊断；有效时三个种子相同总预算对照。"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import time
from problem2.common.annealing_records import as_code, model_counts
from problem2.common.data import load_case
from problem2.common.encoding import code_from_result, decode, evaluate
from problem2.common.export import export, write_json
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.solver_utils import optimize_once
from problem2.common.stable_constraints import StableConstraints
from problem2.common.validation import validate_exact
from problem2.experiments.stage1_free_jobs import CONFIG, SEEDS, audit, branch, choose_jobs, prepare, read
from problem2.stage2.joint_search import free_job_constraints

METHODS = ('interval', 'guided', 'random')


def timed_branch(root, seed, method, budget, per_round):
    folder = root/f'seed{seed}'/method
    folder.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    deadline = started+budget
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    current = code_from_result(read(root/f'prefix_seed{seed}/annealing/result.json'), data.n)
    initial, best = current, evaluate(data, current)
    archive = [as_code(r['code']) for r in read(root/f'prefix_seed{seed}/archive.json')]
    records, improvements, seen = [], [], set()
    rng = random.Random(seed+1000)
    import gurobipy as gp
    env = gp.Env(empty=True)
    env.setParam('OutputFlag', 0)
    env.start()
    try:
        for iteration in range(80):
            if time.perf_counter() >= deadline-.1:
                break
            choice = choose_jobs(data, current, archive, method, iteration, rng, seen)
            if choice is None:
                break
            jobs, details = choice
            restriction = free_job_constraints(current, jobs)
            before = best
            result = optimize_once(data, current, restriction, folder/f'round{iteration+1:03d}',
                    min(per_round, max(0, deadline-time.perf_counter())), 8,
                    strengthen=True, compact=True, solver_env=env, deadline=deadline)
            counts = model_counts(restriction)
            assert counts['binary_variables'] == result['proof']['reduction']['binary_variables']
            candidate = code_from_result(result, data.n)
            cost = evaluate(data, candidate)
            if cost < best:
                current, best = candidate, cost
                improvements.append({'objective': best, 'elapsed_seconds': time.perf_counter()-started,
                                     'code': current.as_dict()})
                export(folder/'best', decode(data, current))
            records.append({'round': iteration+1, 'jobs': list(jobs), 'selection': details,
                'before': before, 'after': best, 'counts': counts, 'proof': result['proof'],
                'elapsed_seconds': time.perf_counter()-started})
            write_json(folder/'checkpoint.json', {'rounds': records, 'best': best, 'complete': False})
            print(json.dumps({'seed': seed, 'method': method, 'round': iteration+1,
                              'best': best, 'nodes': result['proof']['nodes']}, ensure_ascii=False), flush=True)
    finally:
        env.dispose()
    final = decode(data, current)
    final['validation'] = validate_exact(data, final)
    export(folder/'final', final)
    summary = {'seed': seed, 'method': method, 'before': evaluate(data, initial), 'after': best,
        'budget_seconds': budget, 'per_round_seconds': per_round,
        'additional_seconds': time.perf_counter()-started, 'round_count': len(records),
        'rounds': records, 'improvements': improvements, 'start_code': initial.as_dict(),
        'first_improvement_seconds': improvements[0]['elapsed_seconds'] if improvements else None,
        'scope': 'restricted', 'complete': True, 'original_optimality_proven': False}
    write_json(folder/'summary.json', summary)


def diagnose(root):
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    old = PROJECT_ROOT/'problem2/results/stage1_free_jobs/run01'
    sources = [(11, 'guided', 1), (23, 'guided', 1), (37, 'guided', 1), (37, 'random', 5)]
    rows = []
    for index, (seed, method, iteration) in enumerate(sources):
        source = old/f'seed{seed}'/method/f'round{iteration:03d}'
        raw, previous = read(source/'restrictions.json'), read(source/'result.json')
        restriction = StableConstraints(as_code(raw['reference_code']), raw['selected_relations'])
        before = evaluate(data, restriction.reference)
        for seconds in ((5, 15, 30), (15, 30, 5), (30, 5, 15), (5, 30, 15))[index]:
            result = optimize_once(data, restriction.reference, restriction,
                root/'diagnostic'/f'seed{seed}_{method}_r{iteration:03d}'/f'time{seconds}',
                seconds, 8, strengthen=True, compact=True)
            proof = result['proof']
            assert proof['model_sha256'] == previous['proof']['model_sha256']
            row = {'seed': seed, 'method': method, 'original_round': iteration,
                'seconds': seconds, 'before': before, 'after': result['objective'],
                'source_path': str(source.relative_to(PROJECT_ROOT)), 'same_model_sha256': True,
                'proof': proof}
            rows.append(row)
            write_json(root/'diagnostic_summary.json', rows)
            print(json.dumps({k: v for k, v in row.items() if k != 'proof'} |
                {'nodes': proof['nodes'], 'optimal': proof['optimal'], 'bound': proof['bound']},
                ensure_ascii=False), flush=True)
    # 只有延长时间产生新增改善或完成受限证明，才启动后续对照。
    benefits = []
    for seed, method, iteration in sources:
        group = [r for r in rows if (r['seed'], r['method'], r['original_round']) == (seed, method, iteration)]
        baseline = next(r for r in group if r['seconds'] == 5)
        benefits += [r for r in group if r['seconds'] > 5 and
            (r['after'] < baseline['after'] or (r['proof']['optimal'] and not baseline['proof']['optimal']))]
    chosen = min((r['seconds'] for r in benefits), default=None)
    write_json(root/'decision.json', {'selected_per_round_seconds': chosen,
        'beneficial_diagnostics': [{k: r[k] for k in ('seed', 'method', 'original_round', 'seconds', 'after')} for r in benefits],
        'rule': 'smallest_extended_limit_with_new_improvement_or_restricted_optimality',
        'diagnostic_reuses_saved_reference': True, 'diagnostic_historical_cost_excluded': True})
    return chosen


def worker(root, phase, seed=None, method=None, seconds=30):
    name = phase if seed is None else f'{phase}_{seed}_{method or "prefix"}'
    command = [sys.executable, '-u', '-B', '-m', 'problem2.experiments.stage1_round_time', '--output', str(root), '--phase', phase,
               '--seconds', str(seconds)]
    if seed is not None:
        command += ['--seed', str(seed)]
    if method:
        command += ['--method', method]
    with (root/f'{name}.log').open('w', encoding='utf-8') as log:
        completed = subprocess.run(command, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=300)
    if completed.returncode:
        raise RuntimeError(f'{name}: inspect log')


def orchestrate(root):
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    hashes = snapshot_source(root/'source')
    write_json(root/'config.json', {'case': 2, 'seeds': SEEDS, 'search': asdict(CONFIG),
        'code_sha256': hashes, 'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (PROJECT_ROOT/'问题2.pdf', PROJECT_ROOT/'问题2数据.xlsx')},
        'diagnostic_limits': [5, 15, 30], 'additional_budget': 110, 'threads': 8,
        'full_case2_model_allowed': False, 'default_algorithm_modified': False})
    worker(root, 'diagnostic')
    seconds = read(root/'decision.json')['selected_per_round_seconds']
    rows, prefixes = [], []
    if seconds:
        for seed in SEEDS:
            worker(root, 'prepare', seed)
            prefixes.append(read(root/f'prefix_seed{seed}/summary.json'))
        for seed, order in zip(SEEDS, (METHODS, METHODS[1:]+METHODS[:1], METHODS[2:]+METHODS[:2])):
            for method in order:
                print(f'start seed={seed} method={method} seconds={seconds}', flush=True)
                worker(root, 'branch', seed, method, seconds)
                row = read(root/f'seed{seed}'/method/'summary.json')
                rows.append(row)
                write_json(root/'partial_summary.json', {'records': rows, 'complete': False})
                print(json.dumps({k: row[k] for k in ('seed', 'method', 'after', 'additional_seconds')}, ensure_ascii=False), flush=True)
    verification = audit(root, rows)
    write_json(root/'verification.json', verification)
    summary = {'complete': True, 'diagnostic': read(root/'diagnostic_summary.json'),
        'decision': read(root/'decision.json'), 'prefixes': prefixes, 'records': rows,
        'wall_seconds': time.perf_counter()-started, 'verification': verification,
        'original_optimality_proven': False}
    write_json(root/'summary.json', summary)
    print(json.dumps({'complete': True, 'wall_seconds': summary['wall_seconds'], 'verification': verification}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('all', 'diagnostic', 'prepare', 'branch'), default='all')
    parser.add_argument('--seed', type=int, choices=SEEDS)
    parser.add_argument('--method', choices=METHODS)
    parser.add_argument('--seconds', type=int, choices=(15, 30), default=30)
    args = parser.parse_args()
    root = args.output.resolve()
    if args.phase == 'all':
        orchestrate(root)
    elif args.phase == 'diagnostic':
        diagnose(root)
    elif args.phase == 'prepare':
        prepare(root, args.seed)
    elif args.method == 'interval':
        branch(root, args.seed, args.method, 110)
    else:
        timed_branch(root, args.seed, args.method, 110, args.seconds)


if __name__ == '__main__':
    main()
