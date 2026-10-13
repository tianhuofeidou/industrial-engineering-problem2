"""多种子启发式、强化受限模型与区间重排研究；所有试验保留完整证据。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
from problem2.stage1.windows import refine_windows, _refine_windows
import argparse
import hashlib
import json
import random
import time
from dataclasses import asdict
from pathlib import Path
from problem2.common.data import load_case
from problem2.common.encoding import decode, evaluate, code_from_result
from problem2.common.solver import export
from problem2.common.validation import validate_exact
from problem2.experiments.four_methods import ComparisonConfig, initialize, run_method
from problem2.common.relation_tracking import RelationTracker
from problem2.common.stable_constraints import StableConstraints
from problem2.experiments.stable_relations import optimize_once, write_json
from problem2.stage1.neighborhoods import window_constraints, consensus_constraints, choose_window
from problem2.common.exact_cache import ExactCache






def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=int, choices=(1, 2), required=True)
    parser.add_argument('--seeds', nargs='+', type=int, default=[11])
    parser.add_argument('--method', choices=('annealing', 'tabu', 'vns'), default='annealing')
    parser.add_argument('--reference', type=Path, help='读取已有调度进行模型诊断，跳过初始化与搜索')
    parser.add_argument('--evidence', type=Path, help='使用已有关系证据，限reference诊断')
    parser.add_argument('--variants', nargs='+', choices=('full', 'stable', 'window'), default=['window'])
    parser.add_argument('--solver-seconds', type=float, default=120)
    parser.add_argument('--round-seconds', type=float, default=5)
    parser.add_argument('--width', type=int, default=5)
    parser.add_argument('--max-rounds', type=int, default=36)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--compact-model', action='store_true', help='省略上下界已保证成立的约束，保留有用的时间约束')
    parser.add_argument('--reuse-env', action='store_true', help='区间阶段共用一个Gurobi环境，仍分别建立受限模型')
    parser.add_argument('--no-range-cache', action='store_true', help='关闭已证明范围缓存，用于对照')
    parser.add_argument('--no-batch-descent', action='store_true', help='关闭大算例初始化批量评分，用于对照')
    parser.add_argument('--sa-comparison', action='store_true', help='重复完整退火流程，追加用时至少达到区间阶段实际用时')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if min(args.solver_seconds, args.round_seconds, args.width, args.max_rounds, args.threads) <= 0:
        parser.error('时间、区间宽度、轮数和线程数必须为正')
    if len(set(args.seeds)) != len(args.seeds) or len(set(args.variants)) != len(args.variants):
        parser.error('种子和方法不得重复')
    if args.evidence and not args.reference:
        parser.error('已有证据仅供已有调度诊断')
    if args.sa_comparison and ('window' not in args.variants or args.reference):
        parser.error('退火用时对照需要完整初始化搜索与window阶段')
    root = PROJECT_ROOT
    output = args.output.resolve()
    if output.exists():
        parser.error('输出目录已存在')
    data = load_case(root/'问题2数据.xlsx', args.case)
    output.mkdir(parents=True)
    snapshot = output/'source'
    snapshot.mkdir()
    for p in source_files(root):
        copy_source_file(p, snapshot)
    config = ComparisonConfig()
    write_json(output/'config.json', {'arguments': vars(args) | {'output': '.',
               'reference': bool(args.reference), 'evidence': bool(args.evidence)}, 'search': asdict(config),
               'code_sha256': {source_relative(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files(root)},
               'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (root/'问题2.pdf', root/'问题2数据.xlsx')}})
    started = time.perf_counter()
    samples, searches = [], []
    if args.reference:
        result = json.loads(args.reference.read_text(encoding='utf-8'))
        if result['case'] != args.case:
            raise ValueError('已有调度的算例不匹配')
        validate_exact(data, result)
        current = code_from_result(result, data.n)
        uncertainty = {}
        restrictions = StableConstraints.from_evidence(current, json.loads(args.evidence.read_text(encoding='utf-8'))) if args.evidence else None
        sample_info = {'existing_reference': True}
    else:
        for seed in args.seeds:
            initial, info = initialize(data, seed, config, batch_descent=not args.no_batch_descent)
            tracker = RelationTracker(initial, info['local_best'], args.method)
            outcome = run_method(args.method, data, initial, seed, config, tracker)
            sample = list(tracker.samples)+[(outcome.search.best, outcome.search.best_cost)]
            samples.append(sample)
            folder = output/f'seed{seed}'
            schedule = decode(data, outcome.search.best)
            schedule['validation'] = validate_exact(data, schedule)
            export(folder, schedule)
            write_json(folder/'samples.json', [{'code': c.as_dict(), 'objective': v} for c, v in sample])
            write_json(folder/'evidence.json', outcome.evidence)
            searches.append({'seed': seed, 'initial': info['local_best'], 'best': outcome.search.best_cost,
                             'initial_seconds': info['seconds'], 'search_seconds': outcome.search.seconds})
            print(json.dumps({'phase': 'heuristic', 'case': args.case, **searches[-1]}), flush=True)
        current = min((code for group in samples for code, value in group), key=lambda code: evaluate(data, code))
        restrictions, uncertainty, sample_info = consensus_constraints(current, samples)
    preparation_seconds = time.perf_counter()-started
    reference = decode(data, current)
    reference['validation'] = validate_exact(data, reference)
    export(output/'reference', reference)
    write_json(output/'selection.json', {'samples': sample_info, 'constraints': restrictions.as_dict() if restrictions else None})
    records = []
    exact_cache = ExactCache() if not args.no_range_cache else None
    for variant in args.variants:
        begin = time.perf_counter()
        folder = output/variant
        if variant == 'window':
            result = refine_windows(data, current, uncertainty, folder, args.solver_seconds, args.round_seconds,
                                     args.max_rounds, args.width, args.seeds[0], args.threads,
                                     args.compact_model, args.reuse_env, exact_cache=exact_cache,
                                     cache_enabled=not args.no_range_cache)
        elif variant == 'stable' and (restrictions is None or not restrictions.records):
            records.append({'variant': variant, 'skipped': 'no_supported_relations'})
            continue
        else:
            result = optimize_once(data, current, restrictions if variant == 'stable' else None,
                                   folder, args.solver_seconds, args.threads, strengthen=True,
                                   compact=args.compact_model)
        records.append({'variant': variant, 'before': reference['objective'], 'after': result['objective'],
                        'exact_seconds': time.perf_counter()-begin,
                        'proof': result.get('proof'), 'refinement': result.get('refinement')})
        write_json(output/'summary.json', {'complete': False, 'case': args.case, 'searches': searches, 'records': records})
    if args.sa_comparison:
        target_seconds = next(r['exact_seconds'] for r in records if r['variant'] == 'window')
        own_best, own_cost = current, evaluate(data, current)
        begin, repeated = time.perf_counter(), []
        # 每次退火完成自己的降温规则；最后一次可能超过目标时间，对照方获得更多用时。
        while time.perf_counter()-begin < target_seconds:
            seed = args.seeds[0]+10000+len(repeated)
            outcome = run_method('annealing', data, own_best, seed, config)
            if outcome.search.best_cost < own_cost:
                own_best, own_cost = outcome.search.best, outcome.search.best_cost
            repeated.append({'seed': seed, 'best': own_cost, 'search_seconds': outcome.search.seconds})
            schedule = decode(data, own_best)
            schedule['validation'] = validate_exact(data, schedule)
            export(output/'sa_comparison'/f'run{len(repeated):03d}', schedule)
            write_json(output/'sa_comparison'/'checkpoint.json', {'complete': False, 'records': repeated})
            print(json.dumps({'phase': 'sa_comparison', 'case': args.case, **repeated[-1]}), flush=True)
        elapsed = time.perf_counter()-begin
        write_json(output/'sa_comparison'/'checkpoint.json', {'complete': True, 'records': repeated,
                                                            'seconds': elapsed, 'objective': own_cost})
        records.append({'variant': 'repeated_annealing', 'before': reference['objective'], 'after': own_cost,
                        'exact_seconds': 0, 'additional_search_seconds': elapsed, 'target_seconds': target_seconds,
                        'completed_runs': len(repeated), 'at_least_as_much_extra_time_as_window': True})
    write_json(output/'summary.json', {'complete': True, 'case': args.case, 'searches': searches,
               'preparation_seconds': preparation_seconds, 'reference_objective': reference['objective'],
               'sample_info': sample_info, 'records': records,
               'not_an_equal_total_budget_comparison': len(args.variants) > 1 or bool(args.reference)})
    print(json.dumps({'phase': 'complete', 'case': args.case}), flush=True)


if __name__ == '__main__':
    main()
