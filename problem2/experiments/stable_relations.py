"""启发式记录稳定关系，再调用少量缩小后的Gurobi模型。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
from problem2.common.solver_utils import optimize_once
from problem2.common.export import write_json
import argparse
import hashlib
import json
import os
import re
import time
import math
from dataclasses import asdict
from pathlib import Path
from problem2.common.data import load_case
from problem2.common.encoding import decode, evaluate, code_from_result
from problem2.common.solver import build_model, extract, export
from problem2.common.validation import validate_exact
from problem2.experiments.four_methods import ComparisonConfig, initialize, run_method
from problem2.common.relation_tracking import RelationTracker, EvidenceConfig
from problem2.common.stable_constraints import StableConstraints






def refine_stable(data, search, evidence, output, rounds=3, seconds=120, threads=8, release_fraction=0.25):
    output.mkdir(parents=True)
    current, cost = search.best, search.best_cost
    restrictions = StableConstraints.from_evidence(current, evidence)
    initial_constraints = restrictions.as_dict()
    records, started = [], time.perf_counter()
    reason = 'round_limit'
    for iteration in range(rounds):
        if not restrictions.records:
            reason = 'no_supported_fixed_relations'
            break
        before = cost
        result = optimize_once(data, current, restrictions, output/f'round{iteration+1:02d}', seconds, threads)
        if result['objective'] < cost:
            current, cost = code_from_result(result, data.n), result['objective']
        records.append({'round': iteration+1, 'before': before, 'after': cost,
                        'direct_relations': len(restrictions.records), 'proof': result['proof']})
        write_json(output/'status.json', {'complete': False, 'records': records, 'best': cost})
        print(json.dumps({'phase': 'stable_exact_round', 'case': data.case, 'round': iteration+1,
                          'before': before, 'after': cost, 'fixed': len(restrictions.records),
                          'binary_variables': result['proof']['reduction']['binary_variables'],
                          'status': result['proof']['status']}), flush=True)
        if cost == before:
            if not result['proof']['optimal']:
                reason = 'unfinished_range_without_improvement'
                break  # 尚未求完且没有改善，不通过扩大范围增加困难。
            restrictions = restrictions.relaxed(release_fraction)
    final = decode(data, current)
    final['validation'] = validate_exact(data, final)
    final['refinement'] = {'scope': 'restricted', 'original_optimality_proven_by_this_run': False,
                           'rounds': len(records), 'reason': reason, 'records': records,
                           'initial_constraints': initial_constraints,
                           'seconds': time.perf_counter()-started, 'before': search.best_cost, 'after': cost}
    export(output/'final', final)
    write_json(output/'status.json', {'complete': True, 'records': records, 'best': cost, 'reason': reason})
    return final


def main():
    root = PROJECT_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=int, choices=(1, 2), default=1)
    parser.add_argument('--methods', nargs='+', choices=('annealing', 'tabu', 'vns'), default=None)
    parser.add_argument('--seed', type=int, default=11)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--solver-seconds', type=float, default=120)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--release-fraction', type=float, default=0.25)
    parser.add_argument('--min-attempts', type=int, default=20)
    parser.add_argument('--min-perturbations', type=int, default=10)
    parser.add_argument('--min-late-samples', type=int, default=5)
    parser.add_argument('--measure-overhead', action='store_true', help='同一初始解额外运行未启用记录的搜索')
    args = parser.parse_args()
    methods = args.methods or (['annealing'] if args.case == 2 else ['annealing', 'tabu', 'vns'])
    if len(set(methods)) != len(methods) or not 1 <= args.rounds <= 3 or args.solver_seconds <= 0 or args.threads < 1:
        parser.error('方法不得重复，首版最多3轮，求解时间与线程数须为正')
    if not 0 < args.release_fraction <= 1:
        parser.error('解除比例须在(0,1]')
    ec = EvidenceConfig(min_attempts=args.min_attempts, min_perturbations=args.min_perturbations,
                        min_late_samples=args.min_late_samples)
    try:
        ec.check()
    except ValueError as error:
        parser.error(str(error))
    output = args.output.resolve()
    if output.exists():
        parser.error('输出目录已存在，拒绝覆盖')
    data = load_case(root/'问题2数据.xlsx', args.case)
    config = ComparisonConfig()
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'问题2.pdf', root/'问题2数据.xlsx')}
    output.mkdir(parents=True)
    write_json(output/'config.json', {'arguments': vars(args) | {'output': '.', 'methods': methods},
                                     'search': asdict(config), 'evidence': asdict(ec), 'source_sha256': hashes,
                                     'code_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                    for p in source_files(root)}})
    initial, info = initialize(data, args.seed, config)
    schedule = decode(data, initial)
    schedule['validation'] = validate_exact(data, schedule)
    schedule['initialization'] = info
    export(output/'initial', schedule)
    print(json.dumps({'phase': 'initial', 'case': args.case, 'objective': info['local_best'],
                      'seconds': info['seconds']}), flush=True)
    records = []
    for method in methods:
        folder = output/method
        folder.mkdir()
        baseline = run_method(method, data, initial, args.seed, config) if args.measure_overhead else None
        started = time.perf_counter()
        tracker = RelationTracker(initial, info['local_best'], method, ec)
        outcome = run_method(method, data, initial, args.seed, config, tracker)
        tracked_seconds = time.perf_counter()-started
        if baseline is not None:
            if (baseline.search.best, baseline.search.best_cost, baseline.termination) != (
                    outcome.search.best, outcome.search.best_cost, outcome.termination):
                raise AssertionError('关系记录改变了搜索轨迹或终止规则')
        result = decode(data, outcome.search.best)
        result['validation'] = validate_exact(data, result)
        result['search'] = {'method': method, 'objective': outcome.search.best_cost, 'seconds': tracked_seconds,
                            'termination': outcome.termination, 'evaluations': outcome.search.evaluations,
                            'cache_hits': outcome.search.cache_hits}
        export(folder/'heuristic', result)
        write_json(folder/'evidence.json', outcome.evidence)
        write_json(folder/'history.json', {'improvements': outcome.search.progress,
                                          'iterations': outcome.search.generation_history})
        print(json.dumps({'phase': 'tracked_search', 'case': args.case, 'method': method,
                          'objective': result['objective'], 'seconds': tracked_seconds,
                          'selected_relations': sum(r['selected'] for r in outcome.evidence['relations'])}), flush=True)
        final = refine_stable(data, outcome.search, outcome.evidence, folder/'exact', args.rounds,
                              args.solver_seconds, args.threads, args.release_fraction)
        records.append({'method': method, 'initial': info['local_best'], 'heuristic': result['objective'],
                        'final': final['objective'], 'initial_seconds': info['seconds'],
                        'search_seconds': tracked_seconds, 'exact_seconds': final['refinement']['seconds'],
                        'pipeline_seconds': info['seconds']+tracked_seconds+final['refinement']['seconds'],
                        'baseline_search_seconds': baseline.search.seconds if baseline else None,
                        'baseline_best': baseline.search.best_cost if baseline else None,
                        'same_search_result_with_recording': True if baseline else None,
                        'evidence': str((folder/'evidence.json').relative_to(output)),
                        'refinement': final['refinement'], 'valid': True})
        write_json(output/'summary.json', {'complete': False, 'case': args.case, 'records': records})
    write_json(output/'summary.json', {'complete': True, 'case': args.case, 'seed': args.seed,
                                      'source_sha256': hashes, 'records': records,
                                      'not_an_equal_total_budget_comparison': True})
    print(json.dumps({'phase': 'complete', 'case': args.case, 'methods': methods}), flush=True)


if __name__ == '__main__':
    main()
