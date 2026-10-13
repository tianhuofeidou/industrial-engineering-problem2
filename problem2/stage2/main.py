"""前后段联合重排、少量自由工件Gurobi及扰动后局部下降的研究入口。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
import argparse
import hashlib
import json
import random
import time
from pathlib import Path
from problem2.common.data import load_case
from problem2.common.encoding import BatchEvaluator, code_from_result, decode, evaluate
from problem2.common.validation import validate_exact
from problem2.common.solver import export
from problem2.common.exact_cache import ExactCache
from problem2.stage1.construction import initialize
from problem2.stage1.config import ComparisonConfig
from problem2.common.evaluator import Evaluator, BudgetExpired
from problem2.common.local_search import descend, perturb
from problem2.stage2.joint_search import enumerate_block, choose_groups, free_job_constraints
from problem2.common.solver_utils import optimize_once
from problem2.common.export import write_json


def run(data, initial, output, seconds=600, size=3, groups=80, seed=11, solver_seconds=120,
        solver_rounds=3, solver_period=32, explore=False, perturbations=12, deadline=None):
    started = time.perf_counter()
    deadline = min(started+seconds, deadline) if deadline is not None else started+seconds
    output.mkdir(parents=True, exist_ok=True)
    scorer, cache = BatchEvaluator(data), ExactCache()
    current = best = initial
    best_value = evaluate(data, best)
    rng = random.Random(seed)
    seen, attempted_solver, rows, improvements = set(), set(), [], []
    solver_calls = shakes = scans_since_solver = 0
    env = None
    stream = (output/'events.jsonl').open('w', encoding='utf-8', newline='\n')

    def record(phase, candidate, row):
        nonlocal best, best_value
        value = evaluate(data, candidate)
        improved = value < best_value
        if improved:
            best, best_value = candidate, value
            result = decode(data, best)
            result['validation'] = validate_exact(data, result)
            result['discovery'] = {'phase': phase, 'seconds': time.perf_counter()-started}
            improvements.append({'phase': phase, 'objective': value, 'seconds': time.perf_counter()-started,
                                 'code': best.as_dict()})
            export(output/'improvements'/f'best{len(improvements):03d}', result)
            export(output/'best', result)
        event = {'phase': phase, 'best': best_value, 'candidate': value, 'improved': improved,
                 'elapsed': time.perf_counter()-started, **row}
        rows.append(event)
        stream.write(json.dumps(event, ensure_ascii=False)+'\n')
        stream.flush()
        write_json(output/'checkpoint.json', {'complete': False, 'best': best_value, 'code': best.as_dict(),
                                              'records': rows, 'improvements': improvements})
        if improved or phase != 'enumeration' or len(rows) % 10 == 0:
            print(json.dumps({k: v for k, v in event.items() if k not in ('reference', 'proof', 'code')}, ensure_ascii=False), flush=True)

    warm = decode(data, initial)
    warm['validation'] = validate_exact(data, warm)
    export(output/'reference', warm)
    reason = 'time_budget'
    try:
        while time.perf_counter() < deadline:
            selected = choose_groups(data, current, min(size, data.n), groups)
            available = [jobs for jobs in selected if (current, jobs) not in seen]
            improved_current = False
            for jobs in available[:solver_period]:
                before = evaluate(data, current)
                candidate, info = enumerate_block(data, current, jobs, deadline, scorer)
                if info['complete']:
                    seen.add((current, jobs))
                if info['after'] < before:
                    current, improved_current = candidate, True
                scans_since_solver += 1
                record('enumeration', candidate, info)
                if improved_current or not info['complete']:
                    break
            if time.perf_counter() >= deadline:
                break
            if improved_current:
                scans_since_solver = 0
                continue
            if solver_calls < solver_rounds and scans_since_solver > 0 and (
                    scans_since_solver >= solver_period or not available):
                # 精确阶段从最好编码出发；每轮只放开一组，其他工件仅固定相对顺序。
                options = [jobs for jobs in choose_groups(data, best, min(size, data.n-1), groups)
                           if (best, jobs) not in attempted_solver]
                if options:
                    import gurobipy as gp
                    if env is None:
                        env = gp.Env(empty=True)
                        env.setParam('OutputFlag', 0)
                        env.start()
                    jobs = options[0]
                    attempted_solver.add((best, jobs))
                    solver_calls += 1
                    before = best_value
                    solved = cache.solve(optimize_once, data, best, free_job_constraints(best, jobs),
                        output/'solver'/f'round{solver_calls:03d}', min(solver_seconds, max(0, deadline-time.perf_counter())),
                        8, strengthen=True, compact=True, solver_env=env, deadline=deadline)
                    candidate = code_from_result(solved, data.n)
                    record('gurobi', candidate, {'jobs': list(jobs), 'before': before,
                                                  'after': evaluate(data, candidate), 'proof': solved['proof']})
                    # 求解器只从全程最好解出发；无改善时保留扰动后的参考解。
                    if evaluate(data, candidate) < before:
                        current = candidate
                    scans_since_solver = 0
                    continue
            if available:
                continue
            if not explore or shakes >= perturbations:
                reason = 'selected_ranges_exhausted' if not explore else 'perturbation_limit'
                break
            shakes += 1
            evaluator = Evaluator(data, batch_size=1024 if data.n >= 20 else 0)
            evaluator.deadline = deadline
            shaken = perturb(best, rng, (2, 3, 4)[(shakes-1) % 3])
            completed = True
            try:
                current = descend(shaken, evaluator)
            except BudgetExpired:
                completed = False
                current = evaluator.best or best
            # 允许较差的局部最优成为下一轮参考；全局最好编码始终单独保留。
            record('perturbation', current, {'round': shakes, 'descent_complete': completed,
                    'strength': (2, 3, 4)[(shakes-1) % 3], 'before': best_value,
                    'after': evaluate(data, current), 'evaluations': evaluator.evaluations})
            scans_since_solver = 0
    finally:
        stream.close()
        if env is not None:
            env.dispose()
    result = decode(data, best)
    result['validation'] = validate_exact(data, result)
    result['joint_search'] = {'before': evaluate(data, initial), 'after': best_value,
        'seconds': time.perf_counter()-started, 'termination': reason, 'solver_calls': solver_calls,
        'perturbations': shakes, 'scope': 'restricted', 'original_optimality_proven_by_this_run': False}
    export(output/'final', result)
    write_json(output/'summary.json', {'complete': True, 'case': data.case, 'initial': evaluate(data, initial),
        'final': best_value, 'seconds': time.perf_counter()-started, 'records': rows, 'improvements': improvements,
        'termination': reason, 'solver_calls': solver_calls, 'perturbations': shakes, 'range_cache': cache.summary(),
        'scope': 'restricted', 'original_optimality_proven_by_this_run': False})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', type=int, choices=(1, 2), required=True)
    p.add_argument('--reference', type=Path)
    p.add_argument('--seconds', type=float, default=600)
    p.add_argument('--size', type=int, choices=(2, 3, 4), default=3)
    p.add_argument('--groups', type=int, default=80)
    p.add_argument('--seed', type=int, default=11)
    p.add_argument('--solver-seconds', type=float, default=120)
    p.add_argument('--solver-rounds', type=int, default=3)
    p.add_argument('--solver-period', type=int, default=32)
    p.add_argument('--explore', action='store_true')
    p.add_argument('--perturbations', type=int, default=12)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if min(args.seconds, args.groups, args.solver_seconds, args.solver_period) <= 0 or min(args.solver_rounds, args.perturbations) < 0:
        p.error('时间和扫描数量必须为正；轮数不能为负')
    if args.output.exists():
        p.error('输出目录已存在')
    root = PROJECT_ROOT
    started = time.perf_counter()
    data = load_case(root/'问题2数据.xlsx', args.case)
    args.output.mkdir(parents=True)
    (args.output/'source').mkdir()
    hashes = {}
    for source in source_files(root):
        raw = source.read_bytes()
        copy_source_file(source, args.output/'source', raw)
        hashes[source_relative(source)] = hashlib.sha256(raw).hexdigest()
    write_json(args.output/'config.json', {'arguments': vars(args) | {'output': '.',
        'reference': str(args.reference) if args.reference else None}, 'code_sha256': hashes,
        'source_sha256': {source.name: hashlib.sha256(source.read_bytes()).hexdigest()
                         for source in (root/'问题2.pdf', root/'问题2数据.xlsx')},
        'includes_reference_computation': False if args.reference else True})
    deadline = started+args.seconds
    if args.reference:
        saved = json.loads(args.reference.read_text(encoding='utf-8'))
        if saved['case'] != args.case:
            p.error('参考解算例不一致')
        validate_exact(data, saved)
        initial = code_from_result(saved, data.n)
    else:
        initial, info = initialize(data, args.seed, ComparisonConfig(), deadline=deadline)
        write_json(args.output/'initialization.json', info)
    result = run(data, initial, args.output, seconds=max(0, deadline-time.perf_counter()), size=args.size,
                 groups=args.groups, seed=args.seed, solver_seconds=args.solver_seconds, solver_rounds=args.solver_rounds,
                 solver_period=args.solver_period, explore=args.explore, perturbations=args.perturbations, deadline=deadline)
    total_seconds = time.perf_counter()-started
    summary = json.loads((args.output/'summary.json').read_text(encoding='utf-8'))
    summary.update(total_seconds=total_seconds, includes_initialization=not bool(args.reference))
    write_json(args.output/'summary.json', summary)
    print(json.dumps({'final': result['objective'], 'total_seconds': total_seconds}), flush=True)


if __name__ == '__main__':
    main()
