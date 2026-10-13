"""一阶段：贪心与完整下降、高温退火、区间Gurobi；从原始数据独立运行。"""
import argparse
import hashlib
import json
import platform
import time
from dataclasses import asdict
from pathlib import Path

from problem2.common.data import load_case
from problem2.common.encoding import code_from_result, decode, evaluate
from problem2.common.export import export, write_json
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.validation import validate_exact
from problem2.stage1.config import ComparisonConfig
from problem2.stage1.construction import initialize
from problem2.stage1.annealing import run_annealing
from problem2.stage1.windows import refine_windows


def run(data, output, seed=2026101114, seconds=600, annealing_seconds=90,
        solver_seconds=110, per_round=5, max_rounds=80, width=5, threads=8,
        config=None, batch_descent=True, range_cache=False, started=None):
    """各阶段使用自己的结果继续；已知历史目标值不参与任何决策。"""
    started = time.perf_counter() if started is None else started
    deadline = started + seconds
    config = config or ComparisonConfig(sa_temperature_multiplier=2, sa_cooling=0.97)
    config.check()
    if min(seconds, annealing_seconds, solver_seconds, per_round, width, threads) <= 0 or max_rounds < 0:
        raise ValueError('时间、宽度和线程数须为正；精确轮数不能为负')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('输出目录已存在，重复实验请使用新目录')
    output.mkdir(parents=True)
    hashes = snapshot_source(output/'source')
    write_json(output/'config.json', {
        'case': data.case, 'seed': seed, 'search': asdict(config), 'seconds': seconds,
        'annealing_seconds': annealing_seconds, 'solver_seconds': solver_seconds,
        'per_round': per_round, 'max_rounds': max_rounds, 'width': width, 'threads': threads,
        'batch_descent': batch_descent, 'range_cache': range_cache,
        'uses_saved_reference': False, 'includes_initialization': True,
        'python': platform.python_version(), 'code_sha256': hashes,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (PROJECT_ROOT/'问题2.pdf', PROJECT_ROOT/'问题2数据.xlsx')},
        'scope': 'restricted', 'original_optimality_proven_by_this_run': False,
    })
    events, improvements, best_cost = [], [], float('inf')

    with (output/'events.jsonl').open('w', encoding='utf-8') as stream:
        def record(phase, event, code, details=None):
            nonlocal best_cost
            value = evaluate(data, code)
            row = {'phase': phase, 'event': event, 'elapsed_seconds': time.perf_counter()-started,
                   'objective': value, **(details or {})}
            improved = value < best_cost
            if improved:
                best_cost = value
                schedule = decode(data, code)
                schedule['validation'] = validate_exact(data, schedule)
                export(output/'best', schedule)
                improvements.append(row | {'code': code.as_dict()})
            row['global_best'] = best_cost
            events.append(row)
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')
            stream.flush()
            if improved or event == 'end':
                write_json(output/'progress.json', {'best': best_cost, 'phase': phase,
                           'elapsed_seconds': row['elapsed_seconds'], 'complete': False})
                print(json.dumps(row, ensure_ascii=False), flush=True)

        initial, initialization = initialize(data, seed, config, deadline=deadline,
                                              batch_descent=batch_descent)
        schedule = decode(data, initial)
        schedule['validation'] = validate_exact(data, schedule)
        export(output/'initial', schedule)
        write_json(output/'initialization.json', initialization)
        record('initialization', 'end', initial, {'stage_seconds': initialization['seconds']})

        outcome = run_annealing(data, initial, seed, config,
            deadline=min(deadline, time.perf_counter()+annealing_seconds),
            on_event=lambda event, code, row: record('annealing', event, code, row))
        annealed = decode(data, outcome.search.best)
        annealed['validation'] = validate_exact(data, annealed)
        annealed['termination'] = outcome.termination
        export(output/'annealing', annealed)
        write_json(output/'annealing/temperature_history.json', {
            'levels': outcome.search.generation_history, 'improvements': outcome.search.progress,
            'termination': outcome.termination})
        record('annealing', 'end', outcome.search.best, {'stage_seconds': outcome.search.seconds})

        remaining = deadline-time.perf_counter()
        if max_rounds and remaining > 0.1:
            refined = refine_windows(data, outcome.search.best, {}, output/'window',
                budget=min(solver_seconds, remaining), per_round=per_round, max_rounds=max_rounds,
                width=width, seed=seed, threads=threads, compact=True, reuse_env=True,
                cache_enabled=range_cache, deadline=deadline,
                on_round=lambda code, row: record('gurobi', 'round_end', code, {
                    'round': row['round'], 'before': row['before'], 'after': row['after'],
                    'window_a': row['window_a'], 'window_b': row['window_b'], 'width': row['width'],
                    'status': row['proof']['status'], 'optimal_in_range': row['proof']['optimal']}))
        else:
            refined = annealed
        final = decode(data, code_from_result(refined, data.n))
        final['validation'] = validate_exact(data, final)
        final['run_info'] = {'scope': 'restricted', 'original_optimality_proven_by_this_run': False,
                             'seed': seed, 'includes_initialization': True}
        export(output/'final', final)
        record('final', 'end', code_from_result(final, data.n))
    summary = {'complete': True, 'case': data.case, 'seed': seed,
               'initial': schedule['objective'], 'annealing': annealed['objective'],
               'final': final['objective'], 'total_seconds': time.perf_counter()-started,
               'initialization_seconds': initialization['seconds'],
               'annealing_seconds': outcome.search.seconds, 'annealing_termination': outcome.termination,
               'refinement': refined.get('refinement'), 'improvements': improvements,
               'uses_saved_reference': False, 'includes_initialization': True,
               'scope': 'restricted', 'original_optimality_proven_by_this_run': False}
    write_json(output/'history.json', {'events': events, 'improvements': improvements})
    write_json(output/'summary.json', summary)
    write_json(output/'progress.json', {'complete': True, 'best': final['objective'],
                                       'elapsed_seconds': summary['total_seconds']})
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=int, choices=(1, 2), default=2)
    parser.add_argument('--seed', type=int, default=2026101114)
    parser.add_argument('--seconds', type=float, default=600)
    parser.add_argument('--annealing-seconds', type=float, default=90)
    parser.add_argument('--solver-seconds', type=float, default=110)
    parser.add_argument('--round-seconds', type=float, default=5)
    parser.add_argument('--max-rounds', type=int, default=80)
    parser.add_argument('--width', type=int, default=5)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--temperature-multiplier', type=float, default=2)
    parser.add_argument('--cooling', type=float, default=0.97)
    parser.add_argument('--moves', type=int, default=1000)
    parser.add_argument('--constructions', type=int, default=8)
    parser.add_argument('--no-batch-descent', action='store_true')
    parser.add_argument('--range-cache', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    config = ComparisonConfig(constructions=args.constructions, sa_moves=args.moves,
        sa_temperature_multiplier=args.temperature_multiplier, sa_cooling=args.cooling)
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', args.case)
    result = run(data, args.output, seed=args.seed, seconds=args.seconds,
        annealing_seconds=args.annealing_seconds, solver_seconds=args.solver_seconds,
        per_round=args.round_seconds, max_rounds=args.max_rounds, width=args.width, threads=args.threads,
        config=config, batch_descent=not args.no_batch_descent, range_cache=args.range_cache, started=started)
    print(json.dumps({'complete': True, 'objective': result['objective']}), flush=True)


if __name__ == '__main__':
    main()
