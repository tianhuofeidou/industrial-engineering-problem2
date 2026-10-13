"""固定区间宽度与原自动调整规则对照；同范围穷举核对宽度3的Gurobi。"""
import argparse
from dataclasses import asdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import time

from problem2.common.data import load_case
from problem2.common.encoding import BatchEvaluator, code_from_result, decode, evaluate
from problem2.common.export import export, write_json
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.solver_utils import optimize_once
from problem2.common.stable_constraints import StableConstraints
from problem2.common.validation import validate_exact
from problem2.experiments.stage1_free_jobs import CONFIG, prepare, read
from problem2.stage1.neighborhoods import choose_window, window_constraints
from problem2.stage1.windows import refine_windows

METHODS = ('fixed3', 'fixed5', 'fixed7', 'fixed9', 'adaptive5')
SEEDS = (23, 53, 71)


def enumerate_window(data, reference, start_a, start_b, width):
    """完整遍历两段排列及区间并集的机器归属；每个编码计算全部10工位。"""
    started = time.perf_counter()
    restriction = window_constraints(reference, start_a, start_b, width)
    jobs = sorted(set(reference.a[start_a:start_a+width]) |
                  set(reference.b[start_b:start_b+width]))
    # 本实验只对小区间穷举，避免误用本函数一次分配数百万行数组。
    count = math.factorial(width)**2 * 2**len(jobs)
    if count > 100000:
        raise ValueError('本实验的穷举候选数上限为100000')
    orders, machines = [], []
    for b_part in itertools.permutations(reference.b[start_b:start_b+width]):
        b = reference.b[:start_b]+b_part+reference.b[start_b+width:]
        for bits in itertools.product((0, 1), repeat=len(jobs)):
            m = list(reference.machines)
            for j, value in zip(jobs, bits):
                m[j] = value
            orders.append(b)
            machines.append(tuple(m))
    scorer = BatchEvaluator(data)
    prepared = scorer.prepare(orders, machines)
    best, best_cost = reference, evaluate(data, reference)
    evaluations = 0
    for a_part in itertools.permutations(reference.a[start_a:start_a+width]):
        a = reference.a[:start_a]+a_part+reference.a[start_a+width:]
        values = prepared.evaluate(a)
        index = int(values.argmin())
        value = int(values[index])
        if value < best_cost:
            best = type(reference)(a, orders[index], machines[index])
            best_cost = value
        evaluations += len(values)
    assert evaluations == count and restriction.satisfies(best)
    assert evaluate(data, best) == best_cost
    return best, {'objective': best_cost, 'seconds': time.perf_counter()-started,
                  'evaluations': evaluations, 'free_jobs': len(jobs), 'width': width,
                  'window_a': start_a, 'window_b': start_b,
                  'scope': 'restricted', 'optimal_in_range': True}


def branch(root, seed, method, budget):
    folder = root/f'seed{seed}'/method
    folder.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    prefix = root/f'prefix_seed{seed}'
    schedule = read(prefix/'annealing/result.json')
    validate_exact(data, schedule)
    initial = code_from_result(schedule, data.n)
    preparation = read(prefix/'summary.json')
    width = int(method[-1])
    adaptive = method.startswith('adaptive')
    improvements = []
    def observed(code, row):
        if row['after'] < row['before']:
            improvements.append({'round': row['round'], 'width': row['width'],
                'objective': row['after'], 'additional_seconds': time.perf_counter()-started,
                'code': code.as_dict()})
    final = refine_windows(data, initial, {}, folder/'window',
        budget=max(.1, budget-(time.perf_counter()-started)), per_round=5,
        max_rounds=5000, width=width, seed=seed, threads=8, compact=True,
        reuse_env=True, cache_enabled=False, deadline=started+budget,
        adaptive_width=adaptive, on_round=observed)
    elapsed = time.perf_counter()-started
    records = final['refinement']['records']
    if not adaptive:
        assert all(row['width'] == width for row in records)
    assert final['objective'] <= evaluate(data, initial)
    export(folder/'final', final)
    summary = {'seed': seed, 'method': method, 'initial_width': width,
        'adaptive_width': adaptive, 'before': evaluate(data, initial), 'after': final['objective'],
        'start_code': initial.as_dict(), 'budget_seconds': budget, 'additional_seconds': elapsed,
        'preparation_seconds': preparation['preparation_seconds'],
        'total_seconds_including_preparation': preparation['preparation_seconds']+elapsed,
        'rounds': records, 'round_count': len(records), 'improvements': improvements,
        'first_improvement_seconds': improvements[0]['additional_seconds'] if improvements else None,
        'best_first_found_seconds': improvements[-1]['additional_seconds'] if improvements else 0,
        'termination': 'time_budget' if elapsed >= budget-.1 else 'ranges_exhausted',
        'scope': 'restricted', 'original_optimality_proven': False, 'complete': True}
    write_json(folder/'summary.json', summary)
    print(json.dumps({k: summary[k] for k in ('seed', 'method', 'after', 'additional_seconds', 'round_count')},
                     ensure_ascii=False), flush=True)


def exhaustive_comparison(root, seed):
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    schedule = read(root/f'prefix_seed{seed}/annealing/result.json')
    validate_exact(data, schedule)
    reference = code_from_result(schedule, data.n)
    folder = root/'exhaustive'/f'seed{seed}'
    folder.mkdir(parents=True, exist_ok=False)
    rows, seen, rng = [], set(), random.Random(seed)
    # 与正式选区间函数一致，取三种选择规则各一次；九个范围互不串用新解。
    for index in range(3):
        a, b, policy = choose_window(data, reference, 3, {}, seen, index, rng)
        best, stats = enumerate_window(data, reference, a, b, 3)
        enumeration = decode(data, best)
        enumeration['validation'] = validate_exact(data, enumeration)
        enumeration['enumeration'] = stats
        export(folder/f'range{index+1}/enumeration', enumeration)
        restriction = window_constraints(reference, a, b, 3)
        solved = optimize_once(data, reference, restriction, folder/f'range{index+1}/gurobi',
                               30, 8, strengthen=True, compact=True)
        assert solved['objective'] >= stats['objective']-1e-4
        if solved['proof']['optimal']:
            assert abs(solved['objective']-stats['objective']) <= 1e-4
        rows.append({'seed': seed, 'range': index+1, 'policy': policy, **stats,
            'reference_objective': evaluate(data, reference),
            'gurobi_objective': solved['objective'],
            'gurobi_optimal_in_range': solved['proof']['optimal'],
            'gurobi_total_seconds': solved['proof']['total_seconds'],
            'gurobi_solve_seconds': solved['proof']['runtime'],
            'gurobi_status': solved['proof']['status']})
        write_json(folder/'summary.json', {'complete': index == 2, 'rows': rows})
    print(json.dumps({'event': 'enumeration_complete', 'seed': seed, 'rows': rows}), flush=True)


def audit(root, seeds, methods):
    config = read(root/'config.json')
    for name, digest in config['source_sha256'].items():
        assert hashlib.sha256((PROJECT_ROOT/name).read_bytes()).hexdigest() == digest
    for name, digest in config['code_sha256'].items():
        assert hashlib.sha256((root/'source'/name).read_bytes()).hexdigest() == digest
        assert hashlib.sha256((PROJECT_ROOT/'problem2'/name).read_bytes()).hexdigest() == digest
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    schedules, models = 0, 0
    for path in root.rglob('result.json'):
        result = read(path)
        validate_exact(data, result)
        code = code_from_result(result, data.n)
        value = evaluate(data, code)
        assert value <= result['objective']+1e-4
        if path.parent.name != 'solver_schedule':
            assert abs(value-result['objective']) <= 1e-4
        schedules += 1
        if not (path.parent/'model.mps').exists():
            continue
        proof = result['proof']
        assert proof['scope'] == 'restricted' and not proof['original_optimality_proven_by_this_run']
        assert hashlib.sha256((path.parent/'model.mps').read_bytes()).hexdigest() == proof['model_sha256']
        raw = read(path.parent/'restrictions.json')
        rc = raw['reference_code']
        ref = type(code)(tuple(rc['a']), tuple(rc['b']), tuple(rc['machines']))
        restriction = StableConstraints(ref, raw['selected_relations'])
        assert restriction.satisfies(ref) and restriction.satisfies(code)
        assert proof['bound'] <= result['objective']+1e-4
        if proof['optimal']:
            assert abs(proof['bound']-result['objective']) <= 1e-4
        models += 1
    for seed in seeds:
        starts = [read(root/f'seed{seed}'/method/'summary.json')['start_code'] for method in methods]
        assert all(code == starts[0] for code in starts)
    return {'schedules_validated': schedules, 'models_validated': models,
            'hashes_verified': True, 'same_start_per_seed': True}


def orchestrate(root, seeds, budget):
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    write_json(root/'config.json', {'case': 2, 'seeds': seeds, 'methods': METHODS,
        'additional_budget_seconds': budget, 'per_round_seconds': 5, 'max_rounds': 5000,
        'threads': 8, 'search': asdict(CONFIG), 'range_cache': False,
        'uses_historical_reference': False, 'formal_defaults_modified': False,
        'code_sha256': snapshot_source(root/'source'),
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (PROJECT_ROOT/'问题2.pdf', PROJECT_ROOT/'问题2数据.xlsx')}})
    rows = []
    def worker(phase, seed, method=None):
        tag = f'{phase}_seed{seed}_{method or "shared"}'
        cmd = [sys.executable, '-u', '-B', '-m', 'problem2.experiments.stage1_width_comparison',
               '--output', str(root), '--phase', phase, '--seed', str(seed), '--budget', str(budget)]
        if method:
            cmd += ['--method', method]
        print(json.dumps({'event': 'start', 'run': tag}), flush=True)
        with (root/f'{tag}.log').open('w', encoding='utf-8') as log:
            proc = subprocess.run(cmd, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=max(300, budget+120))
        if proc.returncode:
            raise RuntimeError(f'{tag} failed; inspect log')
    for i, seed in enumerate(seeds):
        worker('prepare', seed)
        order = METHODS[i:]+METHODS[:i]
        for method in order:
            worker('branch', seed, method)
            row = read(root/f'seed{seed}'/method/'summary.json')
            rows.append(row)
            write_json(root/'summary.json', {'complete': False, 'runs': rows,
                                            'wall_seconds': time.perf_counter()-started})
        worker('exhaustive', seed)
    verification = audit(root, seeds, METHODS)
    write_json(root/'verification.json', verification)
    write_json(root/'summary.json', {'complete': True, 'runs': rows,
        'exhaustive': [r for seed in seeds for r in read(root/'exhaustive'/f'seed{seed}'/'summary.json')['rows']],
        'wall_seconds': time.perf_counter()-started, 'verification': verification})
    print(json.dumps({'event': 'complete', 'seconds': time.perf_counter()-started, **verification}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('all', 'prepare', 'branch', 'exhaustive'), default='all')
    parser.add_argument('--seed', type=int, default=23)
    parser.add_argument('--seeds', type=int, nargs='+', default=list(SEEDS))
    parser.add_argument('--method', choices=METHODS)
    parser.add_argument('--budget', type=float, default=180)
    args = parser.parse_args()
    if args.budget <= 0 or len(set(args.seeds)) != len(args.seeds):
        parser.error('预算必须为正，种子不能重复')
    root = args.output.resolve()
    if args.phase == 'all':
        if root.exists():
            parser.error('输出目录已存在')
        orchestrate(root, args.seeds, args.budget)
    elif args.phase == 'prepare':
        prepare(root, args.seed)
    elif args.phase == 'branch':
        if args.method is None:
            parser.error('branch需要指定method')
        branch(root, args.seed, args.method, args.budget)
    else:
        exhaustive_comparison(root, args.seed)


if __name__ == '__main__':
    main()
