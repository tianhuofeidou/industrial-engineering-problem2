"""四个宽度分别运行，单区间不限时；完整一轮无改善才结束该种子。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import time
import traceback

from problem2.common.annealing_records import as_code
from problem2.common.data import load_case
from problem2.common.encoding import code_from_result, decode, evaluate
from problem2.common.export import export
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.solver_utils import optimize_once
from problem2.common.validation import validate_exact
from problem2.stage1.neighborhoods import choose_window, window_constraints

SEEDS = (23, 53, 71)
WIDTHS = (3, 5, 7, 9)


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic_json(path, obj):
    path = Path(path)
    pending = path.with_name(path.name+'.tmp')
    pending.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(pending, path)


def tuples(value):
    return tuple(tuples(x) for x in value) if isinstance(value, list) else value


def search_until_exhausted(data, initial, folder, width, seed, threads=4, env=None,
                           solver=optimize_once, on_event=None):
    """当前编码所有区间证明无严格改善才停止；有改善则从新编码重新计数。"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if not 1 <= width < data.n:
        raise ValueError('区间宽度必须在1至n-1之间')
    validate_exact(data, decode(data, initial))
    checkpoint = folder/'checkpoint.json'
    if checkpoint.exists():
        state = read(checkpoint)
        if state['initial_code'] != initial.as_dict() or state['width'] != width or state['seed'] != seed:
            raise ValueError('恢复参数与原检查点不一致')
        if state['status'] == 'completed':
            return read(folder/'summary.json')
        current = as_code(state['best_code'])
        rng = random.Random()
        rng.setstate(tuples(state['rng_state']))
        completed_pairs = {tuple(p) for p in state['checked_pairs']}
        seen = {(current, width, a, b) for a, b in completed_pairs}
    else:
        current, rng, completed_pairs, seen = initial, random.Random(seed), set(), set()
        schedule = decode(data, initial)
        schedule['validation'] = validate_exact(data, schedule)
        export(folder/'best', schedule)
        state = {'status': 'running', 'seed': seed, 'width': width, 'threads': threads,
            'initial_code': initial.as_dict(), 'initial_objective': evaluate(data, initial),
            'best_code': initial.as_dict(), 'best': evaluate(data, initial),
            'completed_rounds': 0, 'improvements': 0, 'reference_changes': 0,
            'checked_pairs': [], 'pairs_required': (data.n-width+1)**2,
            'pending': None, 'rng_state': rng.getstate(), 'elapsed_seconds': 0,
            'started_utc': now(), 'scope': 'restricted', 'original_optimality_proven': False}
    start, prior_elapsed = time.perf_counter(), state['elapsed_seconds']
    state['status'] = 'running'
    def save():
        state.update(best_code=current.as_dict(), best=evaluate(data, current),
            checked_pairs=sorted(completed_pairs), rng_state=rng.getstate(),
            elapsed_seconds=prior_elapsed+time.perf_counter()-start, updated_utc=now(), pid=os.getpid())
        atomic_json(checkpoint, state)
    save()
    try:
        with (folder/'rounds.jsonl').open('a', encoding='utf-8') as journal:
            while True:
                pending = state['pending']
                if pending is None:
                    choice = choose_window(data, current, width, {}, seen,
                                           state['completed_rounds'], rng)
                    if choice is None:
                        if len(completed_pairs) != state['pairs_required']:
                            raise AssertionError('区间尚未全部证明，不能报告完整检查结束')
                        schedule = decode(data, current)
                        schedule['validation'] = validate_exact(data, schedule)
                        schedule['neighborhood_proof'] = {
                            'width': width, 'all_pairs_optimal_without_strict_improvement': True,
                            'pairs_checked_for_final_reference': len(completed_pairs),
                            'scope': 'restricted', 'original_optimality_proven': False}
                        export(folder/'final', schedule)
                        save()
                        summary = {k: state[k] for k in ('seed', 'width', 'initial_objective', 'best',
                            'completed_rounds', 'improvements', 'reference_changes', 'elapsed_seconds',
                            'pairs_required', 'started_utc', 'updated_utc')}
                        summary.update(complete=True, final_pairs_checked=len(completed_pairs),
                            local_optimal_for_this_width=True, original_optimality_proven=False)
                        atomic_json(folder/'summary.json', summary)
                        state['status'] = 'completed'
                        save()
                        return summary
                    a, b, policy = choice
                    pending = {'round': state['completed_rounds']+1,
                               'window_a': a, 'window_b': b, 'policy': policy}
                    state['pending'] = pending
                    save()
                a, b = pending['window_a'], pending['window_b']
                restriction = window_constraints(current, a, b, width)
                before = evaluate(data, current)
                round_dir = folder/f"round{pending['round']:06d}"
                # 若进程在提交检查点前结束，复用已经验证且有最优证明的结果。
                if (round_dir/'result.json').exists():
                    result = read(round_dir/'result.json')
                    raw = read(round_dir/'restrictions.json')
                    if raw != restriction.as_dict():
                        raise AssertionError('已存轮次固定关系与检查点不一致')
                    validate_exact(data, result)
                    if hashlib.sha256((round_dir/'model.mps').read_bytes()).hexdigest() != result['proof']['model_sha256']:
                        raise AssertionError('已存轮次模型哈希不一致')
                else:
                    target = round_dir
                    retry = 1
                    while target.exists():
                        target = folder/f"round{pending['round']:06d}_retry{retry}"
                        retry += 1
                    if on_event:
                        on_event({'event': 'solving', 'seed': seed, 'width': width,
                                  'round': pending['round'], 'best': before,
                                  'solver_folder': str(target.relative_to(folder))})
                    result = solver(data, current, restriction, target, None, threads,
                                    strengthen=True, compact=True, solver_env=env)
                proof = result['proof']
                if (not proof['optimal'] or proof['status'] != 2 or proof['scope'] != 'restricted'
                    or abs(proof['bound']-result['objective']) > 1e-4
                    or abs(proof['solver_objective']-result['objective']) > 1e-4):
                    raise RuntimeError('本轮未证明范围最优，停止该进程并保留检查点')
                candidate = code_from_result(result, data.n)
                validate_exact(data, result)
                if not restriction.satisfies(candidate) or result['objective'] > before+1e-4:
                    raise AssertionError('结果违反固定范围或劣于参考解')
                value = evaluate(data, candidate)
                if abs(value-result['objective']) > 1e-4:
                    raise AssertionError('范围最优值与完整解码不一致')
                improved = value < before
                state['completed_rounds'] += 1
                state['pending'] = None
                if improved:
                    current = candidate
                    state['improvements'] += 1
                    state['reference_changes'] += 1
                    # 只接受严格改善，不会返回旧编码；旧编码的已检查位置不用于新编码。
                    seen, completed_pairs = set(), set()
                    schedule = decode(data, current)
                    schedule['validation'] = validate_exact(data, schedule)
                    export(folder/'best', schedule)
                else:
                    completed_pairs.add((a, b))
                    seen.add((current, width, a, b))
                row = {'round': pending['round'], 'seed': seed, 'width': width, 'window_a': a,
                    'window_b': b, 'policy': pending['policy'], 'before': before, 'after': value,
                    'improved': improved, 'optimal_in_range': True, 'solve_seconds': proof['runtime'],
                    'model_sha256': proof['model_sha256'],
                    'elapsed_seconds': prior_elapsed+time.perf_counter()-start,
                    'final_reference_pairs_checked': len(completed_pairs)}
                journal.write(json.dumps(row, ensure_ascii=False)+'\n')
                journal.flush()
                save()
                if on_event:
                    on_event({'event': 'round_end', **row})
    except BaseException as error:
        state['status'] = 'failed'
        state['error'] = f'{type(error).__name__}: {error}'
        save()
        raise


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    source = PROJECT_ROOT/'problem2/results/stage1_width_comparison/run02'
    old = read(source/'config.json')
    for name, digest in old['source_sha256'].items():
        if hashlib.sha256((PROJECT_ROOT/name).read_bytes()).hexdigest() != digest:
            raise ValueError('原始输入与对照起点不一致')
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    preparations = []
    for seed in SEEDS:
        prefix = source/f'prefix_seed{seed}'
        schedule = read(prefix/'annealing/result.json')
        validate_exact(data, schedule)
        if evaluate(data, code_from_result(schedule, data.n)) != schedule['objective']:
            raise AssertionError('历史退火起点评分不一致')
        export(root/'references'/f'seed{seed}', schedule)
        cost = read(prefix/'summary.json')
        preparations.append({'seed': seed, 'objective': schedule['objective'],
            'historical_preparation_seconds': cost['preparation_seconds']})
    atomic_json(root/'config.json', {'case': 2, 'seeds': SEEDS, 'widths': WIDTHS, 'threads_per_process': 4,
        'max_processes': 4, 'per_round_seconds': None, 'total_seconds': None, 'max_rounds': None,
        'stop_rule': 'all_window_pairs_optimal_without_strict_improvement_for_current_reference',
        'same_reference_for_all_widths': True, 'references': preparations,
        'uses_historical_annealing_reference': True, 'historical_preparation_cost_not_included': True,
        'formal_defaults_modified': False, 'scope': 'restricted', 'original_optimality_proven': False,
        'created_utc': now(), 'source_sha256': old['source_sha256'],
        'code_sha256': snapshot_source(root/'source')})


def worker(root, width):
    import gurobipy as gp
    import msvcrt
    root = Path(root).resolve()
    config = read(root/'config.json')
    for name, digest in config['source_sha256'].items():
        if hashlib.sha256((PROJECT_ROOT/name).read_bytes()).hexdigest() != digest:
            raise ValueError('原始输入已改变')
    for name, digest in config['code_sha256'].items():
        if hashlib.sha256((PROJECT_ROOT/'problem2'/name).read_bytes()).hexdigest() != digest:
            raise ValueError('源码已改变，不恢复原实验')
    lane = root/f'width{width}'
    lane.mkdir(exist_ok=True)
    lock = (lane/'worker.lock').open('a+b')
    if lock.tell() == 0:
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    state = {'width': width, 'pid': os.getpid(), 'status': 'starting', 'completed_seeds': [],
             'started_utc': now(), 'threads': 4}
    env = None
    try:
        atomic_json(lane/'status.json', state)
        data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
        env = gp.Env(empty=True)
        env.setParam('OutputFlag', 0)
        # 较大的树节点允许写入当前模型目录，减少并行求解的内存占用。
        env.setParam('NodefileStart', 1.0)
        env.setParam('NodefileDir', '.')
        env.start()
        for seed in SEEDS:
            initial = code_from_result(read(root/'references'/f'seed{seed}/result.json'), data.n)
            state.update(status='running', current_seed=seed, updated_utc=now())
            atomic_json(lane/'status.json', state)
            def event(row):
                state.update(current_seed=seed, latest=row, updated_utc=now())
                atomic_json(lane/'status.json', state)
                print(json.dumps(row, ensure_ascii=False), flush=True)
            summary = search_until_exhausted(data, initial, lane/f'seed{seed}', width, seed,
                                            threads=4, env=env, on_event=event)
            state['completed_seeds'].append(summary)
            atomic_json(lane/'status.json', state)
        state.update(status='completed', updated_utc=now())
        atomic_json(lane/'status.json', state)
    except BaseException as error:
        state.update(status='failed', error=f'{type(error).__name__}: {error}', updated_utc=now())
        atomic_json(lane/'status.json', state)
        (lane/'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
    finally:
        if env is not None:
            env.dispose()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('prepare', 'worker'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--width', type=int, choices=WIDTHS)
    args = parser.parse_args()
    if args.phase == 'prepare':
        prepare(args.output.resolve())
    else:
        if args.width is None:
            parser.error('worker需要指定width')
        worker(args.output, args.width)


if __name__ == '__main__':
    main()
