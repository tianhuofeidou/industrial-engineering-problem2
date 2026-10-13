"""保留不同局部最优起点，独立多进程联合重排；统一预算包含初始化。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
import argparse
import contextlib
import hashlib
import json
import math
import multiprocessing
import os
import platform
import time
import traceback
from pathlib import Path

from problem2.common.data import load_case
from problem2.common.encoding import Chromosome, decode, evaluate
from problem2.common.solver import export
from problem2.common.validation import validate_exact
from problem2.stage1.config import ComparisonConfig
from problem2.stage1.construction import initialize
from problem2.stage2.main import run
from problem2.common.export import write_json


def from_dict(value):
    return Chromosome(tuple(value['a']), tuple(value['b']), tuple(value['machines']))


def differences(first, second):
    """比较两排列的工件对先后关系及按编号保存的机器归属。"""
    n = len(first.a)
    counts = []
    for a, b in ((first.a, second.a), (first.b, second.b)):
        positions = {job: index for index, job in enumerate(b)}
        counts.append(sum(positions[a[i]] > positions[a[j]]
                          for i in range(n) for j in range(i+1, n)))
    counts.append(sum(x != y for x, y in zip(first.machines, second.machines)))
    return tuple(counts)


def distance(first, second):
    # 三部分各自除以可能差异数；等价整数形式避免排序时的浮点误差。
    n = len(first.a)
    a, b, machines = differences(first, second)
    return n*(a+b)+max(1, n*(n-1)//2)*machines


def select_starts(records, count, tolerance=0.10):
    """保留最低目标值；在明确的质量范围内最大化与已选起点的最小差异。"""
    if count < 1 or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError('进程数量必须为正，目标值允许比例必须为有限非负数')
    unique = {}
    for record in records:
        code = from_dict(record['code'])
        code.check(len(code.a))
        if code not in unique or record['objective'] < unique[code]['objective']:
            unique[code] = record
    if not unique:
        return [], {'unique_candidates': 0, 'eligible_candidates': 0}
    key = lambda c: (unique[c]['objective'], c.a, c.b, c.machines)
    ordered = sorted(unique, key=key)
    upper = unique[ordered[0]]['objective']*(1+tolerance)
    eligible = [c for c in ordered if unique[c]['objective'] <= upper]
    selected = [eligible.pop(0)]
    while eligible and len(selected) < count:
        chosen = min(eligible, key=lambda c: (-min(distance(c, s) for s in selected), key(c)))
        selected.append(chosen)
        eligible.remove(chosen)
    pairs = [{'first': i+1, 'second': j+1,
              'a_pairs': differences(selected[i], selected[j])[0],
              'b_pairs': differences(selected[i], selected[j])[1],
              'machines': differences(selected[i], selected[j])[2]}
             for i in range(len(selected)) for j in range(i+1, len(selected))]
    return [unique[c] for c in selected], {'unique_candidates': len(unique),
        'eligible_candidates': len(selected)+len(eligible), 'objective_upper': upper,
        'requested_workers': count, 'actual_workers': len(selected),
        'tolerance': tolerance, 'pair_differences': pairs}


def read_json_if_ready(path):
    # 搜索进程单独写自己的检查点；读取时文件可能正好处于写入过程中。
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def worker(data, initial, folder, deadline, overall_started, seed, size, groups, perturbations):
    started, cpu_started = time.perf_counter(), 0.0
    folder.mkdir(parents=True, exist_ok=True)
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    metadata = {'seed': seed, 'initial': evaluate(data, initial),
                'start_offset': started-overall_started, 'complete': False}
    with (folder/'console.log').open('w', encoding='utf-8') as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                result = run(data, initial, folder, seconds=max(0, deadline-time.perf_counter()),
                             size=size, groups=groups, seed=seed, solver_rounds=0,
                             explore=True, perturbations=perturbations, deadline=deadline)
                metadata.update(complete=True, final=result['objective'])
            except Exception:
                metadata['error'] = traceback.format_exc()
                traceback.print_exc()
            finally:
                metadata.update(seconds=time.perf_counter()-started,
                                cpu_seconds=time.process_time()-cpu_started,
                                end_offset=time.perf_counter()-overall_started)
                write_json(folder/'worker.json', metadata)


def collect_worker(data, folder, initial, number, overall_started):
    metadata = read_json_if_ready(folder/'worker.json') or {'complete': False, 'error': '进程未正常结束'}
    summary = read_json_if_ready(folder/'summary.json')
    if summary is None:
        summary = read_json_if_ready(folder/'checkpoint.json') or {}
    code = initial
    if metadata.get('complete'):
        result = read_json_if_ready(folder/'final'/'result.json')
        if result is None:
            raise RuntimeError('正常结束的进程缺少完整调度')
        from problem2.common.encoding import code_from_result
        code = code_from_result(result, data.n)
        validate_exact(data, result)
    elif 'code' in summary:
        code = from_dict(summary['code'])
    result = decode(data, code)
    result['validation'] = validate_exact(data, result)
    # 异常也不能丢失该进程的起点；检查点必须确实达到其声称的目标值。
    if summary.get('best', summary.get('final', result['objective'])) != result['objective']:
        raise RuntimeError('检查点目标值与重新解码不一致')
    if result['objective'] > evaluate(data, initial):
        raise RuntimeError('进程丢失了原始可行上界')
    row = {'worker': number, **metadata, 'final': result['objective'],
           'enumerations': sum(r['phase'] == 'enumeration' for r in summary.get('records', [])),
           'evaluations': sum(r.get('evaluations', 0) for r in summary.get('records', [])),
           'perturbations': summary.get('perturbations', 0),
           'solver_calls': summary.get('solver_calls', 0), 'validation': result['validation']}
    history = [{'worker': number, 'objective': r['objective'],
                'seconds': metadata.get('start_offset', time.perf_counter()-overall_started)+r['seconds'],
                'phase': r['phase']} for r in summary.get('improvements', [])]
    return code, row, history


def experiment(data, output, started, deadline, workers=4, seeds=(11, 23, 37),
               constructions=8, tolerance=0.10, size=3, groups=80, perturbations=1000):
    # 本入口每次使用独立进程；process_time从0起计，包含导入及输入加载的CPU开销。
    cpu_started = 0.0
    pool, initialization, history = [], [], []
    for seed in seeds:
        code, info = initialize(data, seed, ComparisonConfig(constructions=constructions),
                                deadline=deadline, retain_candidates=True)
        initialization.append(info)
        pool.extend(info['candidates'])
        history.append({'objective': evaluate(data, code), 'seconds': time.perf_counter()-started,
                        'phase': 'initialization', 'seed': seed})
        write_json(output/'initialization.json', initialization)
        print(json.dumps({'phase': 'initialization', 'seed': seed, 'best': info['local_best'],
                          'candidates': len(pool), 'elapsed': time.perf_counter()-started}), flush=True)
        if time.perf_counter() >= deadline:
            break
    starts, selection = select_starts(pool, workers, tolerance)
    write_json(output/'starts.json', {'pool': pool, 'selected': starts, 'selection': selection})
    codes = [from_dict(r['code']) for r in starts]
    for i, code in enumerate(codes):
        result = decode(data, code)
        result['validation'] = validate_exact(data, result)
        export(output/'starts'/f'start{i+1:02d}', result)
    best = min(codes, key=lambda c: evaluate(data, c))
    context = multiprocessing.get_context('spawn')
    processes, launched = [], []
    for i, code in enumerate(codes):
        if time.perf_counter() >= deadline:
            break
        folder = output/f'worker{i+1:02d}'
        process = context.Process(target=worker, args=(data, code, folder, deadline, started,
                                  seeds[0]+i*101, size, groups, perturbations))
        process.start()
        processes.append(process)
        launched.append((folder, code, i+1))
    print(json.dumps({'phase': 'launch', 'workers': len(processes), 'selection': selection,
                      'initial_values': [r['objective'] for r in starts],
                      'elapsed': time.perf_counter()-started}), flush=True)
    next_report = time.perf_counter()
    while any(p.is_alive() for p in processes):
        for process in processes:
            process.join(timeout=0.2)
        now = time.perf_counter()
        if now >= next_report:
            progress = []
            for folder, code, number in launched:
                checkpoint = read_json_if_ready(folder/'checkpoint.json') or {}
                progress.append({'worker': number, 'best': checkpoint.get('best', evaluate(data, code)),
                                 'events': len(checkpoint.get('records', []))})
            print(json.dumps({'phase': 'progress', 'elapsed': now-started,
                              'workers': progress}, ensure_ascii=False), flush=True)
            next_report = now+30
        # 正常搜索在候选批次之间检查预算；只对截止一分钟后仍未退出的异常进程终止。
        if now >= deadline+60:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            break
    rows = []
    for folder, code, number in launched:
        candidate, row, changes = collect_worker(data, folder, code, number, started)
        rows.append(row)
        history.extend(changes)
        if evaluate(data, candidate) < evaluate(data, best):
            best = candidate
    global_history, best_value = [], math.inf
    for entry in sorted(history, key=lambda r: r['seconds']):
        if entry['objective'] < best_value:
            best_value = entry['objective']
            global_history.append(entry)
    result = decode(data, best)
    result['validation'] = validate_exact(data, result)
    result['multistart_search'] = {'workers': len(rows), 'solver_calls': 0,
                                 'original_optimality_proven_by_this_run': False}
    export(output/'final', result)
    summary = {'complete': all(r.get('complete', False) for r in rows), 'case': data.case,
        'initial': min(r['objective'] for r in starts), 'final': result['objective'],
        'budget_seconds': deadline-started, 'total_seconds': time.perf_counter()-started,
        'includes_initialization': True, 'workers': rows, 'global_improvements': global_history,
        'initialization_seconds': sum(r['seconds'] for r in initialization),
        'parent_cpu_seconds': time.process_time()-cpu_started,
        'worker_cpu_seconds': sum(r.get('cpu_seconds', 0) for r in rows),
        'worker_wall_seconds_sum': sum(r.get('seconds', 0) for r in rows),
        'worker_cpu_measurement_complete': all('cpu_seconds' in r for r in rows),
        'scope': 'heuristic', 'solver_calls': 0, 'launched_workers': len(rows),
        'original_optimality_proven_by_this_run': False, 'validation': result['validation']}
    write_json(output/'summary.json', summary)
    print(json.dumps({'phase': 'final', 'final': result['objective'],
                      'total_seconds': summary['total_seconds'], 'workers': rows}, ensure_ascii=False), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=int, choices=(1, 2), required=True)
    parser.add_argument('--seconds', type=float, default=1800)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--initial-seeds', type=int, nargs='+', default=[11, 23, 37])
    parser.add_argument('--constructions', type=int, default=8)
    parser.add_argument('--tolerance', type=float, default=0.10)
    parser.add_argument('--size', type=int, choices=(2, 3, 4), default=3)
    parser.add_argument('--groups', type=int, default=80)
    parser.add_argument('--perturbations', type=int, default=1000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (not math.isfinite(args.seconds) or args.seconds <= 0
            or min(args.workers, args.constructions, args.groups) < 1 or args.perturbations < 0
            or not math.isfinite(args.tolerance) or args.tolerance < 0):
        parser.error('时间、进程、构造和扫描数量必须为正；扰动次数和质量比例不能为负')
    output = args.output.resolve()
    if output.exists():
        parser.error('输出目录已存在，拒绝覆盖')
    root = PROJECT_ROOT
    started = time.perf_counter()
    deadline = started+args.seconds
    data = load_case(root/'问题2数据.xlsx', args.case)
    output.mkdir(parents=True)
    (output/'source').mkdir()
    hashes = {}
    for source in source_files(root):
        raw = source.read_bytes()
        copy_source_file(source, output/'source', raw)
        hashes[source_relative(source)] = hashlib.sha256(raw).hexdigest()
    write_json(output/'config.json', {'arguments': vars(args) | {'output': '.'},
        'code_sha256': hashes, 'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (root/'问题2.pdf', root/'问题2数据.xlsx')},
        'python': platform.python_version(), 'logical_cpus': os.cpu_count(),
        'solver_calls': 0, 'shared_deadline_includes_initialization': True,
        'single_process_comparison_has_different_cpu_budget': True})
    experiment(data, output, started, deadline, args.workers, tuple(args.initial_seeds),
               args.constructions, args.tolerance, args.size, args.groups, args.perturbations)


if __name__ == '__main__':
    main()
