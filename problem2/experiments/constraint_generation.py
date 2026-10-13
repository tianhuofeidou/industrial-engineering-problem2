"""退火记录直接决定解除的先后关系和新增的相邻关系；参考解保持一致。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import time

from problem2.common.annealing_records import changed_relations, as_code, model_counts
from problem2.common.data import load_case
from problem2.common.encoding import code_from_result, decode, evaluate
from problem2.common.export import export, write_json
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.relation_tracking import features, signature, matches
from problem2.common.stable_constraints import StableConstraints
from problem2.common.solver_utils import optimize_once
from problem2.common.validation import validate_exact
from problem2.experiments.annealing_portfolio import GroupObserver
from problem2.experiments.annealing_feedback import audit as audit_schedules
from problem2.experiments.stage1_free_jobs import CONFIG, read
from problem2.stage1.annealing import run_annealing
from problem2.stage1.construction import initialize
from problem2.stage1.neighborhoods import choose_window, window_constraints

SEEDS = (23, 53, 71)
METHODS = ('window', 'record', 'random')


class ConstraintObserver(GroupObserver):
    def __init__(self, initial, cost):
        self.front_groups = {}
        self.statistics = {}
        self.current_operation = None
        self.near_trials = 0
        super().__init__(initial, cost)

    def operation(self, operation):
        self.current_operation = operation

    def sample(self, code, cost):
        super().sample(code, cost)
        if cost <= self.best_cost*self.ratio:
            old = self.front_groups.get(code.a)
            if old is None or cost < old[0]:
                self.front_groups[code.a] = cost, code
        if len(self.front_groups) > 8192:
            keep = sorted(self.front_groups, key=lambda a: (self.front_groups[a][0], a))[:4096]
            self.front_groups = {a: self.front_groups[a] for a in keep}

    def trial(self, before, after, before_cost, cost, *, temperature=None):
        super().trial(before, after, before_cost, cost, temperature=temperature)
        if before_cost > self.best_cost*1.03:
            return
        self.near_trials += 1
        relations = changed_relations(before, self.current_operation)
        kind = self.current_operation[0]
        if kind != 'flip':
            q = 'A' if kind.endswith('_a') else 'B'
            left = before.a if q == 'A' else before.b
            right = after.a if q == 'A' else after.b
            n = len(left)
            broken = set(zip((-1,)+left, left+(n,))) - set(zip((-1,)+right, right+(n,)))
            relations += [(('adj', q, i, j), 1) for i, j in broken]
        for key, value in relations:
            row = self.statistics.setdefault((key, value), {'attempts': 0,
                'small_delta': 0, 'minimum_candidate_cost': None})
            row['attempts'] += 1
            row['small_delta'] += int(cost-before_cost <= 50)
            old = row['minimum_candidate_cost']
            row['minimum_candidate_cost'] = cost if old is None else min(old, cost)

    def report(self):
        fronts = sorted((r for r in self.front_groups.values() if r[0] <= self.best_cost*1.03),
                        key=lambda r: (r[0], r[1].a))[:4096]
        return {'quality_ratio': 1.03, 'near_trials': self.near_trials,
            'front_samples': [{'objective': v, 'code': c.as_dict()} for v, c in fronts],
            'other_samples': [{'objective': v, 'code': c.as_dict()} for v, c in self.rows()],
            'statistics': [{'key': list(key), 'value': value, **row}
                           for (key, value), row in sorted(self.statistics.items())]}


def evidence_for(reference, reference_cost, report):
    target = features(reference)
    stats = {(tuple(r['key']), r['value']): r for r in report['statistics']}
    # 各排列或机器数组只计一次，避免前段的许多等值变体重复投票给同一后段。
    pools = {}
    for kind, raw, extract in (
            ('A', report['front_samples'], lambda c: c.a),
            ('B', report['other_samples'], lambda c: c.b),
            ('machine', report['other_samples'], lambda c: c.machines)):
        unique = {}
        for row in raw:
            if row['objective'] > reference_cost*1.03:
                continue
            code = as_code(row['code'])
            key = extract(code)
            if key not in unique or row['objective'] < unique[key][0]:
                unique[key] = row['objective'], signature(code)
        pools[kind] = list(unique.values())
    rows = {}
    for key, value in target.items():
        if key[0] == 'adj' and key[1] not in ('A', 'B'):
            continue
        pool = pools['machine' if key[0] == 'machine' else key[1]]
        count = sum(matches(key, value, sig) for _, sig in pool)
        agreement = count/len(pool) if pool else 0
        opposite = min((v for v, sig in pool if not matches(key, value, sig)), default=None)
        stat = stats.get((key, value), {})
        minimum = stat.get('minimum_candidate_cost')
        veto = ((opposite is not None and opposite <= reference_cost)
                or (minimum is not None and minimum <= reference_cost))
        attempts = stat.get('attempts', 0)
        selected = (len(pool) >= 5 and agreement >= .95 and attempts >= 20 and not veto)
        rows[key] = {'key': list(key), 'value': value, 'basis': 'annealing_record',
            'distinct_samples': len(pool), 'agreement': agreement, 'attempts': attempts,
            'minimum_breaking_candidate_cost': minimum, 'minimum_opposite_sample_cost': opposite,
            'small_delta_ratio': stat.get('small_delta', 0)/attempts if attempts else 0,
            'better_or_equal_opposite': veto, 'selected': selected}
    return rows


def release_job_orders(base, q, job):
    """解除该工件在一段中的全部直接先后约束；推论由共享模块重新计算。"""
    rows = [r for r in base.records if not (r['key'][0] == 'order'
            and r['key'][1] == q and job in r['key'][2:])]
    return StableConstraints(base.reference, rows)


def weakness(evidence, q, job):
    rows = [r for key, r in evidence.items() if key[0] == 'order' and key[1] == q and job in key[2:]]
    return sum(1-r['agreement']+r['small_delta_ratio'] for r in rows)/max(1, len(rows))


def generate(base, evidence, q, method, seed, tolerance=.20):
    started = time.perf_counter()
    target = model_counts(base)['binary_variables']
    rng = random.Random(seed)
    jobs = list(range(len(base.reference.a)))
    if method == 'record':
        jobs.sort(key=lambda j: (-weakness(evidence, q, j), j))
        adjacent = [r for key, r in evidence.items() if key[0] == 'adj' and r['selected']]
        adjacent.sort(key=lambda r: (-r['agreement'], -r['attempts'], tuple(r['key'])))
    elif method == 'random':
        rng.shuffle(jobs)
        # 控制组使用同一参考解上的相邻弧，保留相同的解除与补充操作形式。
        adjacent = [r for key, r in evidence.items() if key[0] == 'adj' and r['attempts'] >= 20]
        rng.shuffle(adjacent)
        adjacent = [{**r, 'basis': 'random_reference_adjacency'} for r in adjacent]
    else:
        raise ValueError(method)
    candidates = []
    for job in jobs[:8]:
        reduced = release_job_orders(base, q, job)
        initial_records = reduced.records
        best = (abs(model_counts(reduced)['binary_variables']-target), reduced,
                model_counts(reduced)['binary_variables'], [])
        added = []
        for row in adjacent:
            key = row['key']
            if key[1] == q and job in key[2:]:
                continue
            added.append(row)
            trial = StableConstraints(base.reference, initial_records+added[:])
            count = model_counts(trial)['binary_variables']
            error = abs(count-target)
            if error < best[0]:
                best = error, trial, count, added[:]
            if count < target*(1-tolerance):
                break
        error, restriction, count, selected = best
        candidates.append((error, restriction, count, selected, job))
        if error <= target*tolerance:
            break
    error, restriction, count, selected, job = min(candidates, key=lambda r: r[0])
    assert restriction.satisfies(base.reference)
    return restriction, {'method': method, 'released_segment': q, 'released_job': job,
        'weakness': weakness(evidence, q, job), 'added_adjacencies': len(selected),
        'base_binaries': target, 'generated_binaries': count,
        'matched_within_twenty_percent': error <= target*tolerance,
        'generation_seconds': time.perf_counter()-started,
        'selected_adjacencies': selected, 'candidate_jobs_tested': len(candidates)}


def relax_adjacencies(restriction):
    eligible = [r for r in restriction.records if r['key'][0] == 'adj']
    if not eligible:
        return None
    ordered = sorted(eligible, key=lambda r: (r.get('agreement', 0), r.get('attempts', 0), str(r['key'])))
    remove = {tuple(r['key']) for r in ordered[:max(1, (len(ordered)+3)//4)]}
    return StableConstraints(restriction.reference, [r for r in restriction.records if tuple(r['key']) not in remove])


def prepare(root, seed):
    folder = root/f'prefix_seed{seed}'
    folder.mkdir(parents=True, exist_ok=False)
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    initial, info = initialize(data, seed, CONFIG)
    export(folder/'initial', decode(data, initial))
    started = time.perf_counter()
    plain = run_annealing(data, initial, seed, CONFIG)
    plain_seconds = time.perf_counter()-started
    observer = ConstraintObserver(initial, evaluate(data, initial))
    started = time.perf_counter()
    tracked = run_annealing(data, initial, seed, CONFIG, observer=observer)
    tracked_seconds = time.perf_counter()-started
    assert plain.search.best == tracked.search.best and plain.termination == tracked.termination
    fields = ('iteration', 'temperature', 'accepted', 'current', 'uphill_accepted')
    assert [[r[k] for k in fields] for r in plain.search.generation_history] == [
        [r[k] for k in fields] for r in tracked.search.generation_history]
    result = decode(data, tracked.search.best)
    result['validation'] = validate_exact(data, result)
    export(folder/'annealing', result)
    report = observer.report()
    write_json(folder/'tracking.json', report)
    evidence = evidence_for(tracked.search.best, tracked.search.best_cost, report)
    write_json(folder/'evidence.json', list(evidence.values()))
    pure = StableConstraints(tracked.search.best, [r for r in evidence.values() if r['selected']])
    pure_counts = model_counts(pure)
    rng, seen, cases = random.Random(seed+4000), set(), []
    for i in range(6):
        a, b, policy = choose_window(data, tracked.search.best, 5, {}, seen, i, rng)
        base = window_constraints(tracked.search.best, a, b, 5)
        case_folder = folder/f'case{i}'
        case_folder.mkdir(parents=True, exist_ok=False)
        write_json(case_folder/'window.json', base.as_dict())
        variants = {}
        for method in ('record', 'random'):
            restriction, detail = generate(base, evidence, 'A' if i%2 == 0 else 'B', method, seed+i*100)
            write_json(case_folder/f'{method}.json', restriction.as_dict())
            variants[method] = detail
        cases.append({'case_index': i, 'a': a, 'b': b, 'selection_policy': policy,
                      'base_counts': model_counts(base), 'variants': variants})
    summary = {'seed': seed, 'initial': evaluate(data, initial), 'annealing': result['objective'],
        'initialization_seconds': info['seconds'], 'plain_seconds': plain_seconds,
        'tracked_seconds': tracked_seconds, 'same_trajectory': True, 'near_trials': observer.near_trials,
        'front_samples': len(report['front_samples']), 'other_samples': len(report['other_samples']),
        'selected_machine': sum(r['selected'] for k,r in evidence.items() if k[0]=='machine'),
        'selected_order': sum(r['selected'] for k,r in evidence.items() if k[0]=='order'),
        'selected_adjacency': sum(r['selected'] for k,r in evidence.items() if k[0]=='adj'),
        'pure_evidence_counts': pure_counts, 'cases': cases, 'complete': True}
    write_json(folder/'summary.json', summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='cases'}), flush=True)


def branch(root, seed, index, method, end_utc):
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    prefix = root/f'prefix_seed{seed}'
    reference = code_from_result(read(prefix/'annealing/result.json'), data.n)
    raw = read(prefix/f'case{index}/{method}.json')
    restriction = StableConstraints(as_code(raw['reference_code']), raw['selected_relations'])
    folder = root/f'seed{seed}/case{index}/{method}'
    folder.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    deadline = min(started+20, started+datetime.fromisoformat(end_utc).timestamp()-time.time())
    first = optimize_once(data, reference, restriction, folder/'primary',
                          min(10, max(0, deadline-started)), 8, strengthen=True, compact=True, deadline=deadline)
    relaxed, second = None, None
    # 已证明本轮无改善才解除弱相邻关系；超时不因没改善就随意扩大范围。
    if first['proof']['optimal'] and first['objective'] == evaluate(data, reference):
        relaxed = relax_adjacencies(restriction)
        if relaxed is not None and deadline-time.perf_counter() > .2:
            count = model_counts(relaxed)['binary_variables']
            if count <= 2*model_counts(restriction)['binary_variables']:
                second = optimize_once(data, reference, relaxed, folder/'relaxed',
                    max(0, deadline-time.perf_counter()), 8, strengthen=True, compact=True, deadline=deadline)
    best = second if second is not None and second['objective'] < first['objective'] else first
    export(folder/'final', best)
    summary = {'seed': seed, 'case_index': index, 'method': method,
        'before': evaluate(data, reference), 'primary_after': first['objective'], 'after': best['objective'],
        'primary_proof': first['proof'], 'relaxed_proof': second['proof'] if second else None,
        'seconds': time.perf_counter()-started, 'reference_code': reference.as_dict(),
        'scope': 'restricted', 'original_optimality_proven': False, 'complete': True}
    write_json(folder/'summary.json', summary)
    print(json.dumps({k:summary[k] for k in ('seed','case_index','method','before','primary_after','after','seconds')}), flush=True)


def orchestrate(root, end_utc):
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    deadline = datetime.fromisoformat(end_utc).timestamp()
    write_json(root/'config.json', {'case': 2, 'seeds': SEEDS, 'methods': METHODS, 'cases_per_seed': 6,
        'width': 5, 'primary_limit': 10, 'case_limit': 20, 'threads': 8,
        'constraints': 'window_base_release_one_job_orders_add_record_or_random_adjacencies',
        'recording_and_generation_cost_reported_separately': True,
        'formal_defaults_modified': False, 'historical_reference_used': False,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (PROJECT_ROOT/'问题2.pdf', PROJECT_ROOT/'问题2数据.xlsx')},
        'code_sha256': snapshot_source(root/'source'), 'end_utc': end_utc})
    runs = []
    def worker(phase, seed, index=0, method=None):
        tag = f'{phase}_seed{seed}_case{index}_{method or "shared"}'
        args = [sys.executable,'-u','-B','-m','problem2.experiments.constraint_generation',
                '--output',str(root),'--phase',phase,'--seed',str(seed),'--case-index',str(index),
                '--end-utc',end_utc]
        if method:
            args += ['--method',method]
        print(json.dumps({'event':'start','run':tag}), flush=True)
        with (root/f'{tag}.log').open('w',encoding='utf-8') as log:
            done = subprocess.run(args,cwd=PROJECT_ROOT,stdout=log,stderr=subprocess.STDOUT,
                timeout=max(1,min(300 if phase=='prepare' else 35,deadline-time.time()-10)))
        if done.returncode:
            raise RuntimeError(f'{tag} failed; inspect log')
    for seed in SEEDS:
        if deadline-time.time() < 510:
            break
        worker('prepare',seed)
        for index in range(6):
            order = METHODS[index%3:]+METHODS[:index%3]
            for method in order:
                if deadline-time.time() < 35:
                    break
                worker('branch',seed,index,method)
                runs.append(read(root/f'seed{seed}/case{index}/{method}/summary.json'))
                write_json(root/'summary.json',{'complete':False,'runs':runs})
    verification = audit_schedules(root,(),())
    verification.pop('same_start_and_whole_budget',None)
    for seed in SEEDS:
        for index in range(6):
            rows = [r for r in runs if r['seed']==seed and r['case_index']==index]
            if len(rows)==3:
                assert all(r['reference_code']==rows[0]['reference_code'] for r in rows)
    verification['same_reference_per_comparison_verified'] = True
    write_json(root/'verification.json',verification)
    write_json(root/'summary.json',{'complete':len(runs)==54,'runs':runs,
        'wall_seconds':time.perf_counter()-started,'verification':verification})
    print(json.dumps({'event':'complete','runs':len(runs),**verification}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--phase',choices=('all','prepare','branch'),default='all')
    parser.add_argument('--seed',type=int,default=23)
    parser.add_argument('--case-index',type=int,default=0)
    parser.add_argument('--method',choices=METHODS)
    parser.add_argument('--end-utc',required=True)
    args=parser.parse_args()
    root=args.output.resolve()
    if args.phase=='all':
        if root.exists():
            parser.error('需要新输出目录')
        orchestrate(root,args.end_utc)
    elif args.phase=='prepare':
        prepare(root,args.seed)
    else:
        if not args.method:
            parser.error('需要method')
        branch(root,args.seed,args.case_index,args.method,args.end_utc)


if __name__=='__main__':
    main()
