"""三数组编码的贪心、遗传、Case 1 遗传加受限求解统一运行入口。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from problem2.common.data import load_case
from problem2.common.encoding import decode, evaluate
from problem2.common.solver import export
from problem2.common.validation import validate_exact
from problem2.experiments.genetic import SearchConfig, run_genetic, run_greedy
from problem2.experiments.hybrid import refine


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def save_search(data, result, folder, method, seed, config, source_hashes):
    schedule = decode(data, result.best)
    assert schedule['objective'] == result.best_cost
    schedule['validation'] = validate_exact(data, schedule)
    schedule['search'] = {'method': method, 'seed': seed, 'config': asdict(config),
                          'seconds': result.seconds, 'evaluations': result.evaluations,
                          'cache_hits': result.cache_hits, 'generations': result.generations,
                          'constructions': result.constructions, 'code': result.best.as_dict(),
                          'source_sha256': source_hashes}
    export(folder, schedule)
    write_json(folder/'history.json', {'improvements': result.progress,
                                      'generations': result.generation_history})
    write_json(folder/'archive.json', [{'code': code.as_dict(), 'objective': evaluate(data, code)}
                                      for code in result.archive])
    return schedule


def compare_to_benchmark(root, schedule, source_hashes):
    """只在算法返回后读取已证明基准；不向搜索或受限模型传入最优值。"""
    path = root/'problem2/results/exact_case1/run01/benchmark.json'
    if not path.is_file():
        return {'available': False}
    benchmark = json.loads(path.read_text(encoding='utf-8'))
    if benchmark['source_sha256'] != source_hashes:
        return {'available': False, 'reason': 'input_hash_mismatch'}
    optimum = benchmark['optimal_makespan']
    difference = schedule['objective']-optimum
    if difference < -1e-4:
        raise ValueError('验证结果小于已证明最优值，请检查模型或输入')
    return {'available': True, 'optimum': optimum, 'reached_optimum': abs(difference) <= 1e-4,
            'relative_gap': max(0, difference)/optimum}


def main():
    root = PROJECT_ROOT
    parser = argparse.ArgumentParser(description='题目2遗传算法初版及Case 1受限精确优化')
    parser.add_argument('--case', choices=['1', '2', 'all'], default='1')
    parser.add_argument('--method', choices=['greedy', 'genetic', 'hybrid', 'compare'], default='hybrid')
    parser.add_argument('--seconds', type=float, default=10, help='每个种子的启发式预算，含初始化')
    parser.add_argument('--population', type=int, default=60)
    parser.add_argument('--generations', type=int, default=None, help='可选代数上限；与时间预算先到者停止')
    parser.add_argument('--archive-size', type=int, default=12)
    parser.add_argument('--mutation-rate', type=float, default=0.35)
    parser.add_argument('--local-candidates', type=int, default=80)
    parser.add_argument('--seeds', type=int, nargs='+', default=[11, 23, 37])
    parser.add_argument('--free-jobs', type=int, default=3)
    parser.add_argument('--solver-seconds', type=float, default=10)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--output', type=Path, default=root/'problem2/results/genetic_v1')
    args = parser.parse_args()
    config = SearchConfig(args.seconds, args.population, args.generations, args.archive_size,
                          args.mutation_rate, args.local_candidates)
    try:
        config.check()
    except ValueError as error:
        parser.error(str(error))
    if len(set(args.seeds)) != len(args.seeds):
        parser.error('种子不得重复')
    if args.method in ('hybrid', 'compare') and args.case != '1':
        parser.error('hybrid/compare仅允许Case 1；Case 2请选genetic或greedy')
    if not 0 <= args.free_jobs <= 7 or args.solver_seconds <= 0 or args.threads < 1:
        parser.error('可调整工件数须在0到7之间，求解预算和线程数须为正数')
    output = args.output.resolve()
    if output.exists():
        parser.error('输出目录已存在，请使用新的 --output')
    cases = (1, 2) if args.case == 'all' else (int(args.case),)
    inputs = {case: load_case(root/'问题2数据.xlsx', case) for case in cases}
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (root/'问题2.pdf', root/'问题2数据.xlsx')}
    output.mkdir(parents=True)
    records = []
    for case, data in inputs.items():
        for seed in args.seeds:
            begin = perf_counter()
            pending = []
            seed_folder = output/f'case{case}'/f'seed{seed}'
            if args.method in ('greedy', 'compare'):
                search = run_greedy(data, seed, config)
                folder = seed_folder/'greedy'
                schedule = save_search(data, search, folder, 'randomized_greedy', seed, config, source_hashes)
                pending.append(('greedy', folder, schedule, search.seconds))
                print(json.dumps({'case': case, 'seed': seed, 'method': 'greedy',
                                  'objective': schedule['objective'], 'seconds': search.seconds}), flush=True)
            if args.method in ('genetic', 'hybrid', 'compare'):
                search = run_genetic(data, seed, config)
                folder = seed_folder/'genetic'
                schedule = save_search(data, search, folder, 'genetic_with_local_search', seed, config, source_hashes)
                pending.append(('genetic', folder, schedule, search.seconds))
                print(json.dumps({'case': case, 'seed': seed, 'method': 'genetic',
                                  'objective': schedule['objective'], 'seconds': search.seconds,
                                  'evaluations': search.evaluations}), flush=True)
                if args.method in ('hybrid', 'compare'):
                    folder = seed_folder/'hybrid'
                    refined = refine(data, search, folder, args.free_jobs, args.solver_seconds, args.threads)
                    refined['source_sha256'] = source_hashes
                    pending.append(('hybrid', folder, refined,
                                    refined['proof']['total_search_and_refinement_seconds']))
            # 基准只在本种子的所有搜索及求解结束后读取，不用于选工件、初始解或上界。
            for method, folder, schedule, elapsed in pending:
                comparison = compare_to_benchmark(root, schedule, source_hashes) if case == 1 else {'available': False}
                schedule['benchmark_comparison'] = comparison
                write_json(folder/'result.json', schedule)
                proof = schedule.get('proof', {})
                records.append({'case': case, 'seed': seed, 'method': method,
                                'makespan': schedule['objective'], 'seconds': elapsed,
                                'valid': schedule['validation']['valid'],
                                'known_optimum_gap': comparison.get('relative_gap'),
                                'reached_known_optimum': comparison.get('reached_optimum'),
                                'solver_scope': proof.get('scope'), 'solver_bound': proof.get('bound'),
                                'solver_gap': proof.get('gap'), 'solver_optimal': proof.get('optimal'),
                                'result': str((folder/'result.json').relative_to(output)).replace('\\', '/')})
            print(json.dumps({'phase': 'seed_complete', 'case': case, 'seed': seed,
                              'wall_seconds_including_exports': perf_counter()-begin}), flush=True)
            write_json(output/'summary.json', records)
    with (output/'runs.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    code_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in source_files(PROJECT_ROOT)}
    write_json(output/'config.json', vars(args) | {'output': '.', 'source_sha256': source_hashes,
                                                 'code_sha256': code_hashes})
    print(json.dumps({'phase': 'complete', 'records': len(records)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
