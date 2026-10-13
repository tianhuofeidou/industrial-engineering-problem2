"""同起点、同总预算比较直接区间求解与先退火后区间求解。"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from problem2.common.data import load_case
from problem2.common.encoding import code_from_result, decode, evaluate
from problem2.common.export import export, write_json
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.validation import validate_exact
from problem2.experiments.stage1_free_jobs import CONFIG, read
from problem2.stage1.annealing import run_annealing
from problem2.stage1.construction import initialize
from problem2.stage1.windows import refine_windows

SEEDS = (23, 53, 71)
METHODS = ('direct', 'annealing')


def prepare(root, seed):
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    folder = root/f'prefix_seed{seed}'
    folder.mkdir(parents=True, exist_ok=False)
    initial, info = initialize(data, seed, CONFIG)
    if not info['complete']:
        raise AssertionError('初始化未完整下降')
    schedule = decode(data, initial)
    schedule['validation'] = validate_exact(data, schedule)
    export(folder/'initial', schedule)
    write_json(folder/'initialization.json', info)
    print(json.dumps({'event': 'initial', 'seed': seed, 'objective': schedule['objective'],
                      'seconds': info['seconds']}), flush=True)


def branch(root, seed, method, budget=180, timer=None):
    timer = timer or time.perf_counter
    started = timer()
    deadline = started+budget
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    prefix = root/f'prefix_seed{seed}'
    schedule = read(prefix/'initial/result.json')
    validate_exact(data, schedule)
    initial = current = code_from_result(schedule, data.n)
    initialization = read(prefix/'initialization.json')
    folder = root/f'seed{seed}'/method
    folder.mkdir(parents=True, exist_ok=False)
    initial_cost = best = evaluate(data, initial)
    improvements, temperature = [], []
    def accept(phase, code, details=None):
        nonlocal best
        value = evaluate(data, code)
        if value < best:
            best = value
            row = {'phase': phase, 'objective': value, 'elapsed_seconds': timer()-started,
                   'code': code.as_dict(), **(details or {})}
            improvements.append(row)
            result = decode(data, code)
            result['validation'] = validate_exact(data, result)
            export(folder/'best', result)
            print(json.dumps({k: row[k] for k in ('phase', 'objective', 'elapsed_seconds')}), flush=True)
    annealing_seconds, termination = 0.0, None
    if method == 'annealing':
        begin = timer()
        outcome = run_annealing(data, initial, seed, CONFIG, deadline=deadline,
            on_event=lambda kind, code, row: accept('annealing', code, {'event': kind}))
        annealing_seconds = timer()-begin
        current = outcome.search.best
        termination = outcome.termination
        temperature = outcome.search.generation_history
        accept('annealing', current)
        result = decode(data, current)
        result['validation'] = validate_exact(data, result)
        export(folder/'annealing', result)
        write_json(folder/'temperature_history.json', temperature)
    elif method != 'direct':
        raise ValueError('未知对照方法')
    solver_start_code = current
    solver_begin = timer()
    remaining = deadline-solver_begin
    if remaining > .1:
        result = refine_windows(data, current, {}, folder/'window', budget=remaining,
            per_round=5, max_rounds=5000, width=5, seed=seed, threads=8,
            compact=True, reuse_env=True, cache_enabled=False, deadline=deadline,
            adaptive_width=False,
            on_round=lambda code, row: accept('gurobi', code, {'round': row['round']}))
        current = code_from_result(result, data.n)
        accept('gurobi', current)
        records = result['refinement']['records']
    else:
        records = []
    gurobi_seconds = timer()-solver_begin
    final = decode(data, current)
    final['validation'] = validate_exact(data, final)
    export(folder/'final', final)
    seconds = timer()-started
    summary = {'seed': seed, 'method': method, 'budget_seconds': budget,
        'initial': initial_cost, 'solver_start_objective': evaluate(data, solver_start_code),
        'final': final['objective'], 'initial_code': initial.as_dict(),
        'solver_start_code': solver_start_code.as_dict(), 'annealing_seconds': annealing_seconds,
        'annealing_termination': termination, 'gurobi_seconds': gurobi_seconds,
        'additional_seconds': seconds, 'historical_initialization_seconds': initialization['seconds'],
        'full_seconds_including_initialization': initialization['seconds']+seconds,
        'round_count': len(records), 'optimal_rounds': sum(r['proof']['optimal'] for r in records),
        'gurobi_improvements': sum(r['after'] < r['before'] for r in records),
        'improvements': improvements, 'rounds': records,
        'first_best_seconds': improvements[-1]['elapsed_seconds'] if improvements else 0,
        'scope': 'restricted', 'original_optimality_proven': False, 'complete': True}
    write_json(folder/'summary.json', summary)
    print(json.dumps({k: summary[k] for k in ('seed', 'method', 'initial', 'final',
                       'annealing_seconds', 'gurobi_seconds', 'additional_seconds')}), flush=True)
    return summary


def audit(root):
    cfg = read(root/'config.json')
    for name, digest in cfg['source_sha256'].items():
        assert hashlib.sha256((PROJECT_ROOT/name).read_bytes()).hexdigest() == digest
    for name, digest in cfg['code_sha256'].items():
        assert hashlib.sha256((root/'source'/name).read_bytes()).hexdigest() == digest
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    schedules, models = 0, 0
    for path in root.rglob('result.json'):
        result = read(path)
        validate_exact(data, result)
        value = evaluate(data, code_from_result(result, data.n))
        assert value <= result['objective']+1e-4
        if path.parent.name != 'solver_schedule':
            assert abs(value-result['objective']) <= 1e-4
        schedules += 1
        if (path.parent/'model.mps').exists():
            from problem2.common.stable_constraints import StableConstraints
            from problem2.common.annealing_records import as_code
            proof = result['proof']
            assert proof['scope'] == 'restricted' and not proof['original_optimality_proven_by_this_run']
            assert hashlib.sha256((path.parent/'model.mps').read_bytes()).hexdigest() == proof['model_sha256']
            raw = read(path.parent/'restrictions.json')
            restriction = StableConstraints(as_code(raw['reference_code']), raw['selected_relations'])
            assert restriction.satisfies(code_from_result(result, data.n))
            assert proof['bound'] <= result['objective']+1e-4
            if proof['optimal']:
                assert abs(proof['bound']-result['objective']) <= 1e-4
            models += 1
    for seed in cfg['seeds']:
        direct = read(root/f'seed{seed}/direct/summary.json')
        annealing = read(root/f'seed{seed}/annealing/summary.json')
        assert direct['initial_code'] == annealing['initial_code']
        assert direct['budget_seconds'] == annealing['budget_seconds']
        assert direct['annealing_seconds'] == 0
        assert direct['solver_start_code'] == direct['initial_code']
    return {'schedules_verified': schedules, 'models_verified': models,
            'input_and_snapshot_hashes_verified': True, 'same_initial_and_budget': True}


def orchestrate(root, budget):
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    write_json(root/'config.json', {'case': 2, 'seeds': SEEDS, 'methods': METHODS,
        'budget_seconds_after_initialization': budget, 'width': 5, 'adaptive_width': False,
        'per_round_seconds': 5, 'threads': 8, 'max_rounds': 5000, 'range_cache': False,
        'search': asdict(CONFIG), 'formal_defaults_modified': False, 'uses_historical_reference': False,
        'code_sha256': snapshot_source(root/'source'),
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (PROJECT_ROOT/'问题2.pdf', PROJECT_ROOT/'问题2数据.xlsx')}})
    runs = []
    def worker(phase, seed, method=None):
        tag = f'{phase}_seed{seed}_{method or "shared"}'
        args = [sys.executable, '-u', '-B', '-m', 'problem2.experiments.annealing_ablation',
                '--output', str(root), '--phase', phase, '--seed', str(seed), '--budget', str(budget)]
        if method:
            args += ['--method', method]
        print(json.dumps({'event': 'start', 'run': tag}), flush=True)
        with (root/f'{tag}.log').open('w', encoding='utf-8') as log:
            done = subprocess.run(args, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=max(180, budget+120))
        if done.returncode:
            raise RuntimeError(f'{tag} failed; inspect log')
    for i, seed in enumerate(SEEDS):
        worker('prepare', seed)
        order = METHODS if i % 2 == 0 else tuple(reversed(METHODS))
        for method in order:
            worker('branch', seed, method)
            runs.append(read(root/f'seed{seed}'/method/'summary.json'))
            write_json(root/'summary.json', {'complete': False, 'runs': runs})
    verification = audit(root)
    write_json(root/'verification.json', verification)
    write_json(root/'summary.json', {'complete': True, 'runs': runs,
        'wall_seconds': time.perf_counter()-started, 'verification': verification})
    print(json.dumps({'event': 'complete', **verification}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('all', 'prepare', 'branch'), default='all')
    parser.add_argument('--seed', type=int, default=23)
    parser.add_argument('--method', choices=METHODS)
    parser.add_argument('--budget', type=float, default=180)
    args = parser.parse_args()
    if args.budget <= 0:
        parser.error('预算必须为正')
    root = args.output.resolve()
    if args.phase == 'all':
        if root.exists():
            parser.error('输出目录已存在')
        orchestrate(root, args.budget)
    elif args.phase == 'prepare':
        prepare(root, args.seed)
    else:
        if args.method is None:
            parser.error('branch需要指定method')
        branch(root, args.seed, args.method, args.budget)


if __name__ == '__main__':
    main()
