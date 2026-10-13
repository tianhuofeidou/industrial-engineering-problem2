"""只比较题目2 Case 1：完整初始化、四方法、Gurobi逐范围求到最优。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
import argparse
import csv
import hashlib
import json
import statistics
import time
from dataclasses import asdict
from pathlib import Path
from problem2.common.data import load_case
from problem2.common.encoding import decode, evaluate
from problem2.common.solver import export
from problem2.common.validation import validate_exact
from problem2.experiments.four_methods import ComparisonConfig, initialize, run_method
from problem2.experiments.hybrid import refine_until_stable
from problem2.experiments.genetic_main import write_json, compare_to_benchmark
from problem2.common.local_search import all_neighbors


METHODS = ('vns', 'tabu', 'annealing', 'genetic')


def save_outcome(data, outcome, folder, initial, source_hashes):
    s = outcome.search
    result = decode(data, s.best)
    result['validation'] = validate_exact(data, result)
    assert result['objective'] == s.best_cost
    assert s.best_cost <= evaluate(data, initial)
    result['search'] = {'seconds': s.seconds, 'evaluations': s.evaluations,
                        'cache_hits': s.cache_hits, 'generations': s.generations,
                        'constructions': s.constructions, 'code': s.best.as_dict(),
                        'initial_code': initial.as_dict(), 'termination': outcome.termination,
                        'source_sha256': source_hashes}
    export(folder, result)
    write_json(folder/'history.json', {'improvements': s.progress, 'iterations': s.generation_history})
    write_json(folder/'archive.json', [{'code': c.as_dict(), 'objective': evaluate(data, c)} for c in s.archive])
    return result


def aggregate(records, key):
    result = []
    for method in METHODS:
        rows = [r for r in records if r['method'] == method]
        if not rows:
            continue
        values = [r[key] for r in rows]
        result.append({'method': method, 'runs': len(rows), 'best': min(values),
                       'mean': statistics.mean(values), 'stdev': statistics.pstdev(values),
                       'optimum_hits': sum(r.get(key+'_reached_optimum', False) for r in rows),
                       'mean_search_seconds': statistics.mean(r['search_seconds'] for r in rows),
                       'mean_refinement_seconds': statistics.mean(r['refinement_seconds'] for r in rows),
                       'mean_total_seconds': statistics.mean(r['total_seconds'] for r in rows)})
    return result


def main():
    root = PROJECT_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', nargs='+', type=int, default=[11, 23, 37, 53, 71])
    parser.add_argument('--methods', nargs='+', choices=METHODS, default=list(METHODS))
    parser.add_argument('--generations', type=int, default=5000)
    parser.add_argument('--population', type=int, default=60)
    parser.add_argument('--vns-failures', type=int, default=50)
    parser.add_argument('--tabu-stall', type=int, default=5000)
    parser.add_argument('--sa-moves', type=int, default=1000)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--skip-exact', action='store_true', help='仅用于检查启发式，正式对照不使用')
    parser.add_argument('--output', type=Path, default=root/'problem2/results/case1_four_methods/run01')
    args = parser.parse_args()
    config = ComparisonConfig(vns_failures=args.vns_failures, tabu_stall=args.tabu_stall,
                              sa_moves=args.sa_moves, generations=args.generations, population=args.population)
    try:
        config.check()
    except ValueError as error:
        parser.error(str(error))
    if args.threads < 1 or len(set(args.seeds)) != len(args.seeds) or len(set(args.methods)) != len(args.methods):
        parser.error('线程数须为正数，种子及方法不得重复')
    output = args.output.resolve()
    if output.exists():
        parser.error('输出目录已存在，拒绝覆盖')
    data = load_case(root/'问题2数据.xlsx', 1)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
              (root/'问题2.pdf', root/'问题2数据.xlsx')}
    output.mkdir(parents=True)
    write_json(output/'config.json', {'arguments': vars(args) | {'output': '.'},
                                     'comparison': asdict(config), 'source_sha256': hashes,
                                     'code_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                    for p in source_files(root)},
                                     'reads_benchmark_only_after_all_runs': True})
    records = []
    experiment_begin = time.perf_counter()
    for seed in args.seeds:
        initial, info = initialize(data, seed, config)
        assert all(evaluate(data, c) >= info['local_best'] for c in all_neighbors(initial))
        initial_schedule = decode(data, initial)
        initial_schedule['validation'] = validate_exact(data, initial_schedule)
        initial_schedule['initialization'] = info
        seed_folder = output/f'seed{seed}'
        export(seed_folder/'initial', initial_schedule)
        write_json(seed_folder/'initial'/'stages.json', info)
        print(json.dumps({'phase': 'initial', 'seed': seed, 'greedy': info['greedy_best'],
                          'local': info['local_best'], 'seconds': info['seconds']}), flush=True)
        for method in args.methods:
            begin = time.perf_counter()
            folder = seed_folder/method
            outcome = run_method(method, data, initial, seed, config)
            result = save_outcome(data, outcome, folder/'heuristic', initial, hashes)
            write_json(folder/'status.json', {'phase': 'heuristic_complete', 'objective': result['objective']})
            print(json.dumps({'phase': 'heuristic_complete', 'seed': seed, 'method': method,
                              'objective': result['objective'], 'seconds': outcome.search.seconds,
                              'termination': outcome.termination}), flush=True)

            def report_step(item, count):
                write_json(folder/'status.json', {'phase': 'exact', 'models': count,
                                                 'pass': item['pass'], 'objective': item['best_after']})
                print(json.dumps({'phase': 'exact_range', 'seed': seed, 'method': method,
                                  'models': count, 'pass': item['pass'], 'free_jobs': item['free_jobs'],
                                  'objective': item['best_after']}), flush=True)

            if args.skip_exact:
                final, refinement_seconds, models = result, 0, 0
            else:
                final = refine_until_stable(data, outcome.search, folder/'exact', args.threads, report_step)
                refinement_seconds, models = final['rotation']['seconds'], final['rotation']['models']
            write_json(folder/'status.json', {'phase': 'complete', 'objective': final['objective']})
            record = {'seed': seed, 'method': method, 'greedy': info['greedy_best'],
                      'initial': info['local_best'], 'heuristic': result['objective'], 'final': final['objective'],
                      'initial_seconds': info['seconds'], 'search_seconds': outcome.search.seconds,
                      'refinement_seconds': refinement_seconds,
                      'total_seconds': info['seconds']+outcome.search.seconds+refinement_seconds,
                      'method_wall_seconds_including_exports': time.perf_counter()-begin,
                      'evaluations': outcome.search.evaluations, 'cache_hits': outcome.search.cache_hits,
                      'exact_models': models, 'valid': True, 'termination': outcome.termination,
                      'heuristic_result': str((folder/'heuristic/result.json').relative_to(output)).replace('\\', '/'),
                      'final_result': str(((folder/'heuristic/result.json') if args.skip_exact else
                                           folder/'exact/final/result.json').relative_to(output)).replace('\\', '/')}
            records.append(record)
            # 所有算法和求解都结束之前不读取5031，避免影响后续搜索。
            write_json(output/'summary.json', {'complete': False, 'records': records})
    for record in records:
        for key, path_key in (('heuristic', 'heuristic_result'), ('final', 'final_result')):
            path = output/record[path_key]
            schedule = json.loads(path.read_text(encoding='utf-8'))
            comparison = compare_to_benchmark(root, schedule, hashes)
            schedule['benchmark_comparison'] = comparison
            write_json(path, schedule)
            record[key+'_reached_optimum'] = comparison.get('reached_optimum')
            record[key+'_relative_gap'] = comparison.get('relative_gap')
    summary = {'complete': True, 'records': records, 'heuristic': aggregate(records, 'heuristic'),
               'final': aggregate(records, 'final'),
               'experiment_wall_seconds': time.perf_counter()-experiment_begin}
    write_json(output/'summary.json', summary)
    # CSV只放标量；算法完整终止参数仍保留在JSON。
    scalar = [{k: v for k, v in r.items() if k != 'termination'} for r in records]
    with (output/'runs.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(scalar[0]))
        writer.writeheader()
        writer.writerows(scalar)
    print(json.dumps({'phase': 'complete', 'records': len(records), 'output': str(args.output)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
