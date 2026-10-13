"""ABC：共享三条前置退火轨迹，比较追加退火、区间求解、记录选约束。"""
import argparse
from collections import Counter
import csv
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from problem2.common.annealing_records import (AnnealingRecords, SelectionConfig,
        select_relations, model_counts, release_weak)
from problem2.common.data import load_case
from problem2.common.encoding import code_from_result, decode, evaluate
from problem2.common.export import export, write_json
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.solver_utils import optimize_once
from problem2.common.stable_constraints import StableConstraints
from problem2.common.validation import validate_exact
from problem2.stage1.annealing import run_annealing
from problem2.stage1.config import ComparisonConfig
from problem2.stage1.construction import initialize
from problem2.stage1.windows import refine_windows

SEEDS = (11, 23, 37)
CONFIG = ComparisonConfig(constructions=8, sa_temperature_multiplier=2, sa_cooling=.97)
SELECTION = SelectionConfig()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def prepare(root, seed):
    folder = root/f'prefix_seed{seed}'
    folder.mkdir(exist_ok=False)
    started = time.perf_counter()
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    initial, info = initialize(data, seed, CONFIG)
    export(folder/'initial', decode(data, initial))
    write_json(folder/'initialization.json', info)
    write_json(folder/'progress.json', {'phase': 'unrecorded_diagnostic', 'initial': evaluate(data, initial)})
    plain = run_annealing(data, initial, seed, CONFIG)
    diagnostic_seconds = plain.search.seconds
    tracker = AnnealingRecords(initial, evaluate(data, initial), seed, SELECTION)
    events = []
    def event(kind, code, row):
        events.append({'event': kind, **row})
        if kind != 'temperature_level' or row['level'] % 20 == 0:
            write_json(folder/'progress.json', {'phase': 'recorded_annealing', **row})
    recorded = run_annealing(data, initial, seed, CONFIG, observer=tracker, on_event=event)
    if (plain.search.best != recorded.search.best or plain.search.best_cost != recorded.search.best_cost
            or plain.termination != recorded.termination):
        raise AssertionError('记录改变了退火结果或接受计数')
    result = decode(data, recorded.search.best)
    result['validation'] = validate_exact(data, result)
    export(folder/'annealing', result)
    write_json(folder/'records.json', tracker.report())
    write_json(folder/'temperature_history.json', recorded.search.generation_history)
    write_json(folder/'events.json', events)
    summary = {'seed': seed, 'initial': evaluate(data, initial), 'annealing': result['objective'],
               'initialization_seconds': info['seconds'], 'unrecorded_diagnostic_seconds': diagnostic_seconds,
               'recorded_annealing_seconds': recorded.search.seconds,
               'tracking_seconds': tracker.seconds, 'samples': len(tracker.report()['samples']),
               'termination': recorded.termination, 'same_without_recording': True,
               'preparation_seconds_excluding_diagnostic': time.perf_counter()-started-diagnostic_seconds,
               'wall_seconds_including_diagnostic': time.perf_counter()-started,
               'complete': True}
    write_json(folder/'summary.json', summary)
    write_json(folder/'progress.json', summary | {'phase': 'prefix_complete'})
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def branch(root, seed, method, budget):
    folder = root/f'seed{seed}'/method
    folder.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    deadline = started+budget
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    initial = code_from_result(read_json(root/f'prefix_seed{seed}/annealing/result.json'), data.n)
    initial_cost = evaluate(data, initial)
    current, best = initial, initial_cost
    events, improvements, rounds = [], [], []
    def record(kind, code, details=None):
        nonlocal current, best
        cost = evaluate(data, code)
        row = {'event': kind, 'elapsed_seconds': time.perf_counter()-started,
               'candidate': cost, **(details or {})}
        if cost < best:
            current, best = code, cost
            result = decode(data, current)
            result['validation'] = validate_exact(data, result)
            export(folder/'best', result)
            improvements.append(row | {'objective': best, 'code': current.as_dict()})
        row['best'] = best
        events.append(row)
        write_json(folder/'progress.json', row | {'method': method, 'seed': seed})
        with (folder/'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')
    record('start', initial)
    status, evidence = 'finished', None
    if method == 'A':
        cycle = 0
        while time.perf_counter() < deadline-.1:
            cycle += 1
            def event(kind, code, row):
                if kind != 'temperature_level' or row['level'] % 20 == 0:
                    record(kind, code, row | {'cycle': cycle})
            # 每轮只继承本路线的最好解，不使用B/C找到的结果。
            outcome = run_annealing(data, current, seed+100003*cycle, CONFIG,
                                    deadline=deadline, on_event=event)
            record('annealing_end', outcome.search.best, {'cycle': cycle})
            rounds.append({'cycle': cycle, 'seed': seed+100003*cycle,
                           'seconds': outcome.search.seconds, 'termination': outcome.termination})
            if outcome.termination['reason'] == 'time_budget':
                break
    elif method == 'B':
        refined = refine_windows(data, initial, {}, folder/'window',
                budget=max(.1, deadline-time.perf_counter()), per_round=5, max_rounds=80,
                width=5, seed=seed, threads=8, compact=True, reuse_env=True,
                cache_enabled=False, deadline=deadline,
                on_round=lambda code, row: record('gurobi_round', code, {
                    'round': row['round'], 'status': row['proof']['status'],
                    'binaries': row['proof']['reduction']['binary_variables']}))
        record('gurobi_end', code_from_result(refined, data.n))
        rounds = refined['refinement']['records']
    elif method == 'C':
        reports = [read_json(root/f'prefix_seed{s}/records.json') for s in SEEDS]
        restriction, evidence = select_relations(initial, initial_cost, reports, SELECTION)
        write_json(folder/'selection.json', evidence)
        for iteration in range(3):
            if time.perf_counter() >= deadline-.1:
                status = 'time_budget'
                break
            restriction = StableConstraints(current, restriction.records)
            assert restriction.satisfies(current)
            counts = model_counts(restriction)
            write_json(folder/f'counts_round{iteration+1:02d}.json', counts)
            record('constraints', current, {'round': iteration+1, 'counts': counts})
            if not restriction.records or counts['binary_variables'] >= counts['full_binary_variables']:
                status = 'insufficient_supported_reduction'
                break  # 不以其他规则补齐固定，不退回完整模型。
            before = best
            result = optimize_once(data, current, restriction, folder/f'round{iteration+1:02d}',
                    min(40, deadline-time.perf_counter()), 8, strengthen=True, compact=True, deadline=deadline)
            if counts['binary_variables'] != result['proof']['reduction']['binary_variables']:
                raise AssertionError('静态计数与实际模型不一致')
            record('gurobi_round', code_from_result(result, data.n), {
                   'round': iteration+1, 'status': result['proof']['status'], 'counts': counts})
            rounds.append({'round': iteration+1, 'before': before, 'after': best,
                           'counts': counts, 'proof': result['proof']})
            if best == before:
                if not result['proof']['optimal']:
                    status = 'unfinished_range_without_improvement'
                    break
                restriction = release_weak(restriction, .25)
        else:
            status = 'round_limit'
    else:
        raise ValueError(method)
    final = decode(data, current)
    final['validation'] = validate_exact(data, final)
    final['experiment'] = {'method': method, 'seed': seed, 'scope': 'restricted' if method != 'A' else 'heuristic',
                           'original_optimality_proven': False}
    export(folder/'final', final)
    reached = [r['elapsed_seconds'] for r in improvements if r['objective'] <= 10890]
    summary = {'method': method, 'seed': seed, 'before': initial_cost, 'after': best,
               'budget_seconds': budget, 'additional_seconds': time.perf_counter()-started,
               'first_improvement_seconds': improvements[0]['elapsed_seconds'] if improvements else None,
               'first_at_most_10890_seconds': min(reached) if reached else None,
               'termination': status, 'rounds': rounds, 'improvements': improvements,
               'selected_relations': evidence['selected'] if evidence else None,
               'selected_types': evidence['selected_types'] if evidence else None,
               'valid_evidence_seeds': evidence['valid_seeds'] if evidence else None,
               'start_code': initial.as_dict(), 'complete': True,
               'original_optimality_proven': False}
    write_json(folder/'summary.json', summary)
    write_json(folder/'progress.json', {k: v for k, v in summary.items() if k not in ('rounds', 'improvements', 'start_code')})
    print(json.dumps({k: v for k, v in summary.items() if k not in ('rounds', 'improvements', 'start_code')}, ensure_ascii=False), flush=True)


def worker(root, phase, seed, budget, method=None):
    name = f'prefix_seed{seed}' if phase == 'prepare' else f'seed{seed}_{method}'
    folder = root/name if phase == 'prepare' else root/f'seed{seed}'/method
    command = [sys.executable, '-u', '-B', '-m', 'problem2.experiments.abc_comparison',
               '--phase', phase, '--seed', str(seed), '--budget', str(budget), '--output', str(root)]
    if method:
        command.extend(('--method', method))
    launched = time.perf_counter()
    print(json.dumps({'event': 'start', 'run': name}), flush=True)
    with (root/f'{name}.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT,
                                   env=os.environ | {'PYTHONIOENCODING': 'utf-8'})
        previous = 0
        while process.poll() is None:
            elapsed = time.perf_counter()-launched
            if elapsed-previous >= 45:
                path = folder/'progress.json'
                try:
                    row = read_json(path) if path.is_file() else {}
                except json.JSONDecodeError:
                    row = {}
                message = {'event': 'running', 'run': name, 'wall_seconds': elapsed,
                           **{k: row[k] for k in ('phase', 'best', 'initial', 'steps', 'cycle', 'round') if k in row}}
                write_json(root/'status.json', message | {'complete': False})
                print(json.dumps(message, ensure_ascii=False), flush=True)
                previous = elapsed
            time.sleep(1)
    if process.returncode:
        raise RuntimeError(f'{name}: exit={process.returncode}; see {name}.log')
    result = read_json(folder/'summary.json')
    print(json.dumps({'event': 'finished', 'run': name,
                     **{k: result[k] for k in ('before', 'after', 'additional_seconds', 'samples',
                        'selected_relations', 'termination') if k in result}}, ensure_ascii=False), flush=True)
    return result


def audit(root):
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    config = read_json(root/'config.json')
    for name, digest in config['source_sha256'].items():
        assert hashlib.sha256((PROJECT_ROOT/name).read_bytes()).hexdigest() == digest
    for name, digest in config['code_sha256'].items():
        assert hashlib.sha256((root/'source'/name).read_bytes()).hexdigest() == digest
        assert hashlib.sha256((PROJECT_ROOT/'problem2'/name).read_bytes()).hexdigest() == digest
    schedules = models = 0
    difference = 0
    for path in root.rglob('result.json'):
        result = read_json(path)
        validate_exact(data, result)
        code = code_from_result(result, data.n)
        gap = abs(evaluate(data, code)-result['objective'])
        assert gap <= 1e-4, path
        difference = max(difference, gap)
        schedules += 1
        model = path.parent/'model.mps'
        if model.is_file():
            proof = result['proof']
            assert proof['scope'] == 'restricted' and not proof['original_optimality_proven_by_this_run']
            assert hashlib.sha256(model.read_bytes()).hexdigest() == proof['model_sha256']
            raw = read_json(path.parent/'restrictions.json')
            from problem2.common.annealing_records import as_code
            restriction = StableConstraints(as_code(raw['reference_code']), raw['selected_relations'])
            assert restriction.satisfies(code) and restriction.satisfies(restriction.reference)
            assert proof['bound'] <= result['objective']+1e-4
            if proof['optimal']:
                assert abs(proof['bound']-result['objective']) <= 1e-4
            models += 1
    for seed in SEEDS:
        starts = [read_json(root/f'seed{seed}'/m/'summary.json')['start_code'] for m in 'ABC']
        assert starts[0] == starts[1] == starts[2]
    return {'schedules_validated': schedules, 'models_validated': models,
            'maximum_objective_difference': difference, 'objective_tolerance': 1e-4,
            'same_start_per_seed': True, 'source_and_input_hashes_verified': True,
            'original_optimality_proven': False}


def orchestrate(root, budget):
    if root.exists():
        raise FileExistsError('实验目录已存在')
    root.mkdir(parents=True)
    started = time.perf_counter()
    hashes = snapshot_source(root/'source')
    write_json(root/'config.json', {'case': 2, 'seeds': SEEDS, 'additional_budget_seconds': budget,
               'search': asdict(CONFIG), 'selection': asdict(SELECTION),
               'code_sha256': hashes, 'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (PROJECT_ROOT/'问题2.pdf', PROJECT_ROOT/'问题2数据.xlsx')},
               'C_round_limit': 3, 'C_per_round_seconds': 40, 'C_release_fraction': .25,
               'B_round_limit': 80, 'B_per_round_seconds': 5,
               'recording_diagnostic_not_in_algorithm_cost': True,
               'C_uses_all_three_prefixes': True, 'all_routes_share_same_prefix_batch': True,
               'run_order': 'sequential;seed11_ABC,seed23_BCA,seed37_CAB',
               'original_optimality_proven': False})
    prefixes = [worker(root, 'prepare', seed, budget) for seed in SEEDS]
    shared = sum(p['preparation_seconds_excluding_diagnostic'] for p in prefixes)
    diagnostic = sum(p['unrecorded_diagnostic_seconds'] for p in prefixes)
    write_json(root/'preparation_summary.json', {'prefixes': prefixes,
               'shared_preparation_seconds': shared, 'extra_diagnostic_seconds': diagnostic})
    records = []
    # 轮换执行次序；不并发竞争求解器CPU。
    for seed, order in zip(SEEDS, ('ABC', 'BCA', 'CAB')):
        for method in order:
            result = worker(root, 'branch', seed, budget, method)
            records.append(result)
            write_json(root/'partial_summary.json', {'records': records, 'complete': False})
    verification = audit(root)
    write_json(root/'verification.json', verification)
    rows = [{k: r[k] for k in ('seed', 'method', 'before', 'after', 'additional_seconds',
             'first_improvement_seconds', 'first_at_most_10890_seconds', 'termination', 'selected_relations')}
            for r in sorted(records, key=lambda x: (x['seed'], x['method']))]
    groups = {m: {'best': min(r['after'] for r in records if r['method'] == m),
              'additional_seconds_sum': sum(r['additional_seconds'] for r in records if r['method'] == m),
              'group_seconds_including_shared_preparation': shared+sum(r['additional_seconds'] for r in records if r['method'] == m)}
              for m in 'ABC'}
    summary = {'complete': True, 'records': rows, 'prefixes': prefixes, 'groups': groups,
               'shared_preparation_seconds': shared, 'extra_diagnostic_seconds': diagnostic,
               'wall_seconds_including_diagnostics_and_audit': time.perf_counter()-started,
               'verification': verification, 'original_optimality_proven': False}
    write_json(root/'summary.json', summary)
    write_json(root/'status.json', summary)
    with (root/'comparison.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    lines = ['# ABC对照实验记录', '',
             '三条前置退火轨迹先完整运行并记录；ABC同一种子从同一完整编码出发。每个分支追加预算110秒，含分支读取、筛选、建模、求解及导出；实际用时按检查点停止，可能略有额外开销。',
             'A反复从自己的最好解重新校准并退火；B沿用连续区间；C使用三条记录的优质样本，首轮只固定机器和先后，最多3轮、每轮最多40秒，超时无改善提前停止。',
             'C使用其他种子的记录：逐分支追加时间用于比较后续搜索，部署总成本要把整个前置批次计入。组级总时间包含三条公共准备加本方法三个分支，不把C的额外信息称作免费。', '',
             '| 种子 | 方法 | 起点 | 最终 | 追加秒 | 首次改善秒 | 首次≤10890秒 | 固定关系数 | 停止原因 |',
             '|---:|:---:|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:
        value = lambda x: '-' if x is None else f'{x:.2f}'
        lines.append(f"|{r['seed']}|{r['method']}|{r['before']}|{r['after']}|{r['additional_seconds']:.2f}|{value(r['first_improvement_seconds'])}|{value(r['first_at_most_10890_seconds'])}|{r['selected_relations'] if r['selected_relations'] is not None else '-'}|{r['termination']}|")
    lines += ['', f'公共准备{shared:.2f}秒；额外未记录退火诊断{diagnostic:.2f}秒不计入算法成本。实验墙钟总时间{summary["wall_seconds_including_diagnostics_and_audit"]:.2f}秒。',
              '各次目标值和耗时分别报告，不使用平均值。全部模型的下界、gap和OPTIMAL只对应受限范围。',
              f'核验{verification["schedules_validated"]}份调度、{verification["models_validated"]}个模型；源码、输入与参考保留检查通过。',
              '每个prefix的summary.json记录记录前后的一致性、额外开销、样本数；每个C目录的selection.json、counts_round*.json和round*/restrictions.json记录筛选证据及实际固定范围。']
    (root/'实验记录.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({'event': 'all_complete', 'records': rows, 'groups': groups,
                      'verification': verification}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget', type=float, default=110)
    parser.add_argument('--phase', choices=('all', 'prepare', 'branch'), default='all')
    parser.add_argument('--seed', type=int, choices=SEEDS)
    parser.add_argument('--method', choices=tuple('ABC'))
    args = parser.parse_args()
    if args.budget <= 0:
        parser.error('追加预算须为正')
    root = args.output.resolve()
    if args.phase == 'all':
        orchestrate(root, args.budget)
    elif args.seed is None or (args.phase == 'branch' and args.method is None):
        parser.error('子进程须指定种子及方法')
    elif args.phase == 'prepare':
        prepare(root, args.seed)
    else:
        branch(root, args.seed, args.method, args.budget)


if __name__ == '__main__':
    main()
