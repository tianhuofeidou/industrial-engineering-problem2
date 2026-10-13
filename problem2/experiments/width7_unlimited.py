"""随机抽取未完成的宽度7范围，不设单轮时限，仅遵守实验总截止时间。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
import time

from problem2.common.annealing_records import as_code
from problem2.common.data import load_case
from problem2.common.encoding import evaluate
from problem2.common.export import write_json
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.restricted_session import RestrictedSession
from problem2.common.stable_constraints import StableConstraints
from problem2.experiments.stage1_free_jobs import read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--end-utc', required=True)
    args = parser.parse_args()
    remaining = datetime.fromisoformat(args.end_utc).timestamp()-time.time()
    deadline = time.perf_counter()+remaining
    started = time.perf_counter()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = PROJECT_ROOT/'problem2/results/stage1_width_comparison/run02'
    rng = random.Random(20261013)
    selected = {}
    for seed in (23, 53, 71):
        rows = read(source/f'seed{seed}/fixed7/summary.json')['rounds']
        selected[seed] = rng.sample([r for r in rows if not r['proof']['optimal']], 2)
    choices = [(seed, selected[seed][i]) for i in range(2) for seed in (23, 53, 71)]
    write_json(root/'config.json', {'seeds': [23, 53, 71], 'sample_seed': 20261013,
        'selected': [{'seed': s, 'round': r['round']} for s, r in choices],
        'per_model_time_limit': None, 'threads': 8, 'global_end_utc': args.end_utc,
        'scope': 'restricted', 'uses_historical_reference': True,
        'historical_search_cost_not_included': True,
        'code_sha256': snapshot_source(root/'source'),
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (PROJECT_ROOT/'问题2.pdf', PROJECT_ROOT/'问题2数据.xlsx')}})
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    results = []
    for index, (seed, old) in enumerate(choices):
        if time.perf_counter() >= deadline-5:
            break
        origin = source/f'seed{seed}/fixed7/window'/f"round{old['round']:03d}"
        raw = read(origin/'restrictions.json')
        ref = as_code(raw['reference_code'])
        restriction = StableConstraints(ref, raw['selected_relations'])
        folder = root/f"sample{index+1}_seed{seed}_round{old['round']}"
        print(json.dumps({'event': 'start', 'sample': index+1, 'seed': seed,
                          'round': old['round'], 'before': evaluate(data, ref)}), flush=True)
        session = RestrictedSession(data, ref, restriction, folder, threads=8)
        try:
            assert session.digest == hashlib.sha256((origin/'model.mps').read_bytes()).hexdigest()
            # 模型参数TimeLimit保持无穷；仅在整个实验截止时中断当前模型。
            assert session.model.Params.TimeLimit > 1e90
            solved = session.run(float('inf'), deadline=deadline-5)
            proof = solved['proof']
            trace = session.trace
            improved = [r for r in trace if r['solver_objective'] < evaluate(data, ref)-1e-4]
            row = {'seed': seed, 'old_round': old['round'], 'before': evaluate(data, ref),
                'old_5s_objective': old['after'], 'after': solved['objective'],
                'optimal_in_range': proof['optimal'], 'solve_seconds': proof['runtime'],
                'total_seconds': time.perf_counter()-session.created,
                'first_improvement_solve_seconds': improved[0]['phase_seconds'] if improved else None,
                'first_improvement_objective': improved[0]['solver_objective'] if improved else None,
                'bound': proof['bound'], 'gap': proof['gap'], 'nodes': proof['nodes'],
                'status': proof['status'], 'stopped_by_total_budget': proof['callback_time_stop'],
                'model_hash_matches_original': True, 'scope': 'restricted'}
            results.append(row)
            print(json.dumps({'event': 'end', **row}), flush=True)
            write_json(root/'summary.json', {'complete': False, 'runs': results})
        finally:
            session.close()
    write_json(root/'summary.json', {'complete': True, 'runs': results, 'selected_count': len(choices),
        'attempted_count': len(results), 'wall_seconds': time.perf_counter()-started,
        'stopped_on_global_deadline': time.perf_counter() >= deadline-5,
        'scope': 'restricted', 'original_optimality_proven': False})


if __name__ == '__main__':
    main()
