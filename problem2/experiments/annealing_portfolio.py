"""按后段排列与机器归属保存退火样本，同预算比较一个与三个参考解。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from problem2.common.encoding import Chromosome, code_from_result, decode, evaluate
from problem2.common.data import load_case
from problem2.common.export import export, write_json
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.validation import validate_exact
from problem2.experiments.annealing_feedback import audit as audit_schedules
from problem2.experiments.stage1_free_jobs import CONFIG, read
from problem2.stage1.annealing import run_annealing
from problem2.stage1.construction import initialize
from problem2.stage1.windows import refine_windows

SEEDS = (23, 53, 71)
METHODS = ('single', 'three')


class GroupObserver:
    """只记录已接受编码与新最好编码，不评价候选、不调用随机数。"""
    def __init__(self, initial, cost, ratio=1.03, cap=4096):
        self.best_cost, self.ratio, self.cap = cost, ratio, cap
        self.groups = {}
        self.sample(initial, cost)

    def sample(self, code, cost):
        if cost > self.best_cost*self.ratio:
            return
        key = code.b, code.machines
        old = self.groups.get(key)
        if old is None or cost < old[0]:
            self.groups[key] = cost, code
        if len(self.groups) > 2*self.cap:
            ordered = sorted(self.groups, key=lambda k: (self.groups[k][0], k))[:self.cap]
            self.groups = {k: self.groups[k] for k in ordered}

    def trial(self, before, after, before_cost, cost, *, temperature=None):
        if cost < self.best_cost:
            self.best_cost = cost
            self.sample(after, cost)

    def accepted(self, code, cost):
        self.sample(code, cost)

    def rows(self):
        return sorted((row for row in self.groups.values() if row[0] <= self.best_cost*self.ratio),
                      key=lambda r: (r[0], r[1].b, r[1].machines, r[1].a))[:self.cap]


def distance(left, right):
    """后段工件对的逆序数，加上不同机器归属的工件数。"""
    pos = {j: i for i, j in enumerate(right.b)}
    order = [pos[j] for j in left.b]
    return sum(order[i] > order[j] for i in range(len(order)) for j in range(i+1, len(order))) + sum(
        a != b for a, b in zip(left.machines, right.machines))


def select_starts(best, cost, rows, count=3, slack=50):
    selected = [(cost, best)]
    while len(selected) < count:
        used_b = {c.b for _, c in selected}
        candidates = [(v, c) for v, c in rows if v <= cost+slack and c.b not in used_b]
        if not candidates:
            break
        selected.append(min(candidates, key=lambda r: (r[0], -min(distance(r[1], c) for _, c in selected),
                                                       r[1].b, r[1].machines, r[1].a)))
    return selected


def prepare(root, seed):
    folder = root/f'prefix_seed{seed}'
    folder.mkdir(parents=True, exist_ok=False)
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    initial, info = initialize(data, seed, CONFIG)
    export(folder/'initial', decode(data, initial))
    started = time.perf_counter()
    plain = run_annealing(data, initial, seed, CONFIG)
    plain_seconds = time.perf_counter()-started
    observer = GroupObserver(initial, evaluate(data, initial))
    started = time.perf_counter()
    tracked = run_annealing(data, initial, seed, CONFIG, observer=observer)
    tracked_seconds = time.perf_counter()-started
    assert plain.search.best == tracked.search.best and plain.termination == tracked.termination
    fields = ('iteration', 'temperature', 'accepted', 'current', 'uphill_accepted')
    assert [[r[k] for k in fields] for r in plain.search.generation_history] == [
        [r[k] for k in fields] for r in tracked.search.generation_history]
    rows = observer.rows()
    starts = select_starts(tracked.search.best, tracked.search.best_cost, rows)
    for i, (value, code) in enumerate(starts):
        result = decode(data, code)
        assert result['objective'] == value
        result['validation'] = validate_exact(data, result)
        export(folder/f'start{i}', result)
    summary = {'seed': seed, 'initial': evaluate(data, initial), 'annealing': tracked.search.best_cost,
        'initialization_seconds': info['seconds'], 'plain_seconds': plain_seconds,
        'tracked_seconds': tracked_seconds, 'groups': len(rows),
        'unique_b': len({c.b for _, c in rows}), 'unique_machines': len({c.machines for _, c in rows}),
        'same_trajectory': True, 'starts': [{'objective': v, 'code': c.as_dict()} for v, c in starts]}
    write_json(folder/'groups.json', [{'objective': v, 'code': c.as_dict()} for v, c in rows])
    write_json(folder/'summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'starts'}), flush=True)


def branch(root, seed, method, budget=210):
    started = time.perf_counter()
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    prefix = read(root/f'prefix_seed{seed}'/'summary.json')
    folder = root/f'seed{seed}'/method
    folder.mkdir(parents=True, exist_ok=False)
    charged = prefix['plain_seconds' if method == 'single' else 'tracked_seconds']
    deadline = started+budget-charged
    chosen = prefix['starts'][:1] if method == 'single' else prefix['starts']
    records, arms, improvements = [], [], []
    best = decode(data, code_from_result(read(root/f'prefix_seed{seed}/start0/result.json'), data.n))
    # 总精确预算等分；每个参考解独立生成固定约束，不能把不同编码的关系拼在一起。
    for i, row in enumerate(chosen):
        remaining_arms = len(chosen)-i
        arm_deadline = time.perf_counter()+max(0, deadline-time.perf_counter())/remaining_arms
        code = Chromosome(tuple(row['code']['a']), tuple(row['code']['b']), tuple(row['code']['machines']))
        def accepted(candidate, record):
            if record['after'] < best['objective']:
                best.clear()
                best.update(decode(data, candidate))
                improvements.append({'objective': record['after'], 'arm': i,
                    'whole_seconds_after_initialization': charged+time.perf_counter()-started})
        result = refine_windows(data, code, {}, folder/f'arm{i}',
            budget=max(0, arm_deadline-time.perf_counter()), per_round=5, max_rounds=5000,
            width=5, seed=seed, threads=8, compact=True, reuse_env=True, cache_enabled=False,
            deadline=arm_deadline, adaptive_width=False, on_round=accepted)
        records.extend(result['refinement']['records'])
        arms.append({'arm': i, 'before': row['objective'], 'after': result['objective'],
                     'seconds': result['refinement']['seconds'], 'rounds': len(result['refinement']['records'])})
        if result['objective'] < best['objective']:
            best = decode(data, code_from_result(result, data.n))
    best['validation'] = validate_exact(data, best)
    export(folder/'final', best)
    summary = {'seed': seed, 'method': method, 'before': prefix['annealing'], 'after': best['objective'],
        'whole_budget': budget, 'charged_annealing_seconds': charged,
        'whole_seconds_after_initialization': charged+time.perf_counter()-started,
        'initialization_seconds': prefix['initialization_seconds'], 'arms': arms,
        'rounds': records, 'improvements': improvements,
        'first_best_seconds_after_initialization': improvements[-1]['whole_seconds_after_initialization']
            if improvements else charged,
        'scope': 'restricted', 'original_optimality_proven': False, 'complete': True}
    write_json(folder/'summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in ('rounds', 'improvements')}), flush=True)


def orchestrate(root, end_utc):
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    deadline = datetime.fromisoformat(end_utc).timestamp()
    write_json(root/'config.json', {'case': 2, 'seeds': SEEDS, 'methods': METHODS,
        'whole_budget_after_initialization': 210, 'width': 5, 'per_round_seconds': 5, 'threads': 8,
        'portfolio_count': 3, 'portfolio_slack': 50, 'sample_quality_ratio': 1.03,
        'allocation': 'equal_remaining_time_per_independent_start',
        'formal_defaults_modified': False, 'historical_references_used': False,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (PROJECT_ROOT/'问题2.pdf', PROJECT_ROOT/'问题2数据.xlsx')},
        'code_sha256': snapshot_source(root/'source'), 'end_utc': end_utc})
    runs = []
    for idx, seed in enumerate(SEEDS):
        if deadline-time.time() < 455:
            break
        phases = [('prepare', None)] + [('branch', m) for m in METHODS[idx % 2:]+METHODS[:idx % 2]]
        for phase, method in phases:
            tag = f'{phase}_seed{seed}_{method or "shared"}'
            args = [sys.executable, '-u', '-B', '-m', 'problem2.experiments.annealing_portfolio',
                    '--output', str(root), '--phase', phase, '--seed', str(seed)]
            if method:
                args += ['--method', method]
            print(json.dumps({'event': 'start', 'run': tag}), flush=True)
            with (root/f'{tag}.log').open('w', encoding='utf-8') as log:
                done = subprocess.run(args, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=max(1, min(240, deadline-time.time()-15)))
            if done.returncode:
                raise RuntimeError(f'{tag} failed; inspect log')
            if method:
                runs.append(read(root/f'seed{seed}/{method}/summary.json'))
                write_json(root/'summary.json', {'complete': False, 'runs': runs})
    # 复用独立时间表、固定范围和模型文件哈希核查；不套用旧实验的启动编码比较。
    verification = audit_schedules(root, (), ())
    write_json(root/'verification.json', verification)
    write_json(root/'summary.json', {'complete': len(runs) == 6, 'runs': runs,
        'wall_seconds': time.perf_counter()-started, 'verification': verification})
    print(json.dumps({'event': 'complete', 'runs': len(runs), **verification}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('all', 'prepare', 'branch'), default='all')
    parser.add_argument('--seed', type=int, default=23)
    parser.add_argument('--method', choices=METHODS)
    parser.add_argument('--end-utc')
    args = parser.parse_args()
    root = args.output.resolve()
    if args.phase == 'all':
        if root.exists() or not args.end_utc:
            parser.error('需要新目录和end-utc')
        orchestrate(root, args.end_utc)
    elif args.phase == 'prepare':
        prepare(root, args.seed)
    else:
        if not args.method:
            parser.error('需要method')
        branch(root, args.seed, args.method)


if __name__ == '__main__':
    main()
