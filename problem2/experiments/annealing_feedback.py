"""用退火的优质编码分歧或近优试探选择实际可以改变这些关系的区间。"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys
import time

from problem2.common.annealing_records import AnnealingRecords, SelectionConfig, as_code
from problem2.common.data import load_case
from problem2.common.encoding import code_from_result, decode, evaluate
from problem2.common.export import export, write_json
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.relation_tracking import features, signature, matches
from problem2.common.validation import validate_exact
from problem2.experiments.stage1_free_jobs import CONFIG, read
from problem2.stage1.annealing import run_annealing
from problem2.stage1.construction import initialize
from problem2.stage1.neighborhoods import choose_window
from problem2.stage1.windows import refine_windows

SEEDS = (23, 53, 71)
METHODS = ('baseline', 'disagreement', 'trials')


class FeedbackObserver(AnnealingRecords):
    def __init__(self, initial, cost, seed):
        super().__init__(initial, cost, seed,
                         SelectionConfig(quality_ratio=1.03, max_samples=512))
        self.near_stats = {}
        self.near_trials = 0

    def trial(self, before, after, before_cost, cost, *, temperature=None):
        near = before_cost <= self.best_cost*1.03
        super().trial(before, after, before_cost, cost, temperature=temperature)
        if near:
            self.near_trials += 1
            delta = cost-before_cost
            for key, value in self.pending:
                row = self.near_stats.setdefault(key, {'attempts': [0, 0], 'small_delta': [0, 0]})
                row['attempts'][value] += 1
                row['small_delta'][value] += int(delta <= 50)

    def report(self):
        return super().report() | {'near_trials': self.near_trials,
            'near_quality_ratio': 1.03, 'small_delta_limit': 50,
            'near_relations': [{'key': list(key), **value} for key, value in sorted(self.near_stats.items())]}


def relation_weights(reference, reference_cost, report, method):
    target = {k: v for k, v in features(reference).items() if k[0] in ('machine', 'order')}
    if method == 'disagreement':
        eligible = [signature(as_code(row['code'])) for row in report['samples']
                    if row['objective'] <= reference_cost*1.03]
        weights = {k: sum(not matches(k, v, s) for s in eligible)/len(eligible)
                   for k, v in target.items()} if eligible else {}
        return weights, {'eligible_quality_samples': len(eligible)}
    if method == 'trials':
        stats = {tuple(row['key']): row for row in report['near_relations']}
        weights = {}
        for key, value in target.items():
            row = stats.get(key)
            if row and row['attempts'][value] >= 5:
                weights[key] = row['small_delta'][value]/row['attempts'][value]
        return weights, {'relations_with_at_least_five_near_trials': len(weights)}
    raise ValueError(method)


def score_window(reference, a, b, width, weights):
    free_a = set(reference.a[a:a+width])
    free_b = set(reference.b[b:b+width])
    score = sum(weights.get(('machine', j), 0) for j in free_a | free_b)
    for q, free in (('A', free_a), ('B', free_b)):
        score += sum(weights.get(('order', q, i, j), 0)
                     for i, j in itertools.combinations(sorted(free), 2))
    return score


class FeedbackSelector:
    def __init__(self, data, report, method):
        self.data, self.report, self.method = data, report, method
        self.reference, self.weights = None, {}
        self.stats = {'selection_seconds': 0.0, 'feedback_rounds': 0, 'default_rounds': 0,
                      'reference_updates': 0, 'informative_feedback_rounds': 0}
        self.details = []

    def __call__(self, data, reference, width, uncertainty, seen, iteration, rng):
        started = time.perf_counter()
        if iteration % 3 != 1:
            result = choose_window(data, reference, width, {}, seen, iteration, rng)
            self.stats['default_rounds'] += 1
        else:
            if reference != self.reference:
                self.reference = reference
                self.weights, info = relation_weights(reference, evaluate(data, reference), self.report, self.method)
                self.stats['reference_updates'] += 1
                self.details.append({'reference_objective': evaluate(data, reference), **info,
                                     'nonzero_relation_weights': sum(v > 0 for v in self.weights.values())})
            candidates = [(a, b) for a in range(data.n-width+1) for b in range(data.n-width+1)
                          if (reference, width, a, b) not in seen]
            if not candidates:
                result = None
            else:
                ranked = [(score_window(reference, a, b, width, self.weights), rng.random(), a, b)
                          for a, b in candidates]
                score, _, a, b = max(ranked)
                seen.add((reference, width, a, b))
                self.stats['informative_feedback_rounds'] += int(score > 0)
                result = (a, b, self.method if score > 0 else 'feedback_no_evidence_random_tie')
            self.stats['feedback_rounds'] += 1
        self.stats['selection_seconds'] += time.perf_counter()-started
        return result


def prepare(root, seed):
    folder = root/f'prefix_seed{seed}'
    folder.mkdir(parents=True, exist_ok=False)
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    initial, info = initialize(data, seed, CONFIG)
    export(folder/'initial', decode(data, initial))
    write_json(folder/'initialization.json', info)
    started = time.perf_counter()
    plain = run_annealing(data, initial, seed, CONFIG)
    plain_seconds = time.perf_counter()-started
    observer = FeedbackObserver(initial, evaluate(data, initial), seed)
    started = time.perf_counter()
    recorded = run_annealing(data, initial, seed, CONFIG, observer=observer)
    recorded_seconds = time.perf_counter()-started
    if (plain.search.best != recorded.search.best or plain.search.best_cost != recorded.search.best_cost
            or plain.termination != recorded.termination):
        raise AssertionError('观察器改变了退火轨迹或接受规则')
    result = decode(data, recorded.search.best)
    result['validation'] = validate_exact(data, result)
    export(folder/'annealing', result)
    report = observer.report()
    write_json(folder/'feedback.json', report)
    write_json(folder/'summary.json', {'seed': seed, 'initial': evaluate(data, initial),
        'annealing': result['objective'], 'initialization_seconds': info['seconds'],
        'plain_annealing_seconds': plain_seconds, 'recorded_annealing_seconds': recorded_seconds,
        'samples': len(report['samples']), 'near_trials': report['near_trials'],
        'same_recorded_and_plain_trajectory': True, 'complete': True})
    print(json.dumps(read(folder/'summary.json')), flush=True)


def branch(root, seed, method, budget=210):
    started = time.perf_counter()
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    folder = root/f'seed{seed}'/method
    folder.mkdir(parents=True, exist_ok=False)
    prefix = root/f'prefix_seed{seed}'
    prefix_summary = read(prefix/'summary.json')
    reference = code_from_result(read(prefix/'annealing/result.json'), data.n)
    report = read(prefix/'feedback.json')
    charged = prefix_summary['plain_annealing_seconds' if method == 'baseline' else 'recorded_annealing_seconds']
    deadline = started+budget-charged
    if deadline <= time.perf_counter():
        raise ValueError('记录耗时已超过方案总预算')
    selector = None if method == 'baseline' else FeedbackSelector(data, report, method)
    improvements = []
    def accepted(code, row):
        if row['after'] < row['before']:
            improvements.append({'objective': row['after'], 'round': row['round'],
                'policy': row['policy'], 'additional_seconds': time.perf_counter()-started,
                'whole_seconds_after_initialization': charged+time.perf_counter()-started,
                'code': code.as_dict()})
    result = refine_windows(data, reference, {}, folder/'window',
        budget=deadline-time.perf_counter(), per_round=5, max_rounds=5000, width=5,
        seed=seed, threads=8, compact=True, reuse_env=True, cache_enabled=False,
        deadline=deadline, adaptive_width=False, selector=selector, on_round=accepted)
    export(folder/'final', result)
    summary = {'seed': seed, 'method': method, 'before': evaluate(data, reference),
        'after': result['objective'], 'start_code': reference.as_dict(), 'whole_budget': budget,
        'charged_annealing_seconds': charged, 'branch_seconds': time.perf_counter()-started,
        'whole_seconds_after_initialization': charged+time.perf_counter()-started,
        'initialization_seconds': prefix_summary['initialization_seconds'],
        'first_best_seconds_after_initialization': improvements[-1]['whole_seconds_after_initialization']
            if improvements else charged,
        'selection': selector.stats if selector else None,
        'feedback_details': selector.details if selector else None,
        'rounds': result['refinement']['records'], 'improvements': improvements,
        'scope': 'restricted', 'original_optimality_proven': False, 'complete': True}
    write_json(folder/'summary.json', summary)
    print(json.dumps({k: summary[k] for k in ('seed', 'method', 'after',
                                            'whole_seconds_after_initialization', 'selection')}), flush=True)


def audit(root, seeds, methods):
    from problem2.common.stable_constraints import StableConstraints
    config = read(root/'config.json')
    for name, digest in config['source_sha256'].items():
        assert hashlib.sha256((PROJECT_ROOT/name).read_bytes()).hexdigest() == digest
    for name, digest in config['code_sha256'].items():
        assert hashlib.sha256((root/'source'/name).read_bytes()).hexdigest() == digest
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    schedules = models = 0
    for p in root.rglob('result.json'):
        result = read(p)
        validate_exact(data, result)
        code = code_from_result(result, data.n)
        assert evaluate(data, code) <= result['objective']+1e-4
        if p.parent.name != 'solver_schedule':
            assert abs(evaluate(data, code)-result['objective']) <= 1e-4
        schedules += 1
        if (p.parent/'model.mps').exists():
            proof = result['proof']
            assert proof['scope'] == 'restricted'
            assert hashlib.sha256((p.parent/'model.mps').read_bytes()).hexdigest() == proof['model_sha256']
            raw = read(p.parent/'restrictions.json')
            restriction = StableConstraints(as_code(raw['reference_code']), raw['selected_relations'])
            assert restriction.satisfies(code)
            assert proof['bound'] <= result['objective']+1e-4
            if proof['optimal']:
                assert abs(proof['bound']-result['objective']) <= 1e-4
            models += 1
    for seed in seeds:
        rows = [read(root/f'seed{seed}'/m/'summary.json') for m in methods]
        assert all(r['start_code'] == rows[0]['start_code'] and r['whole_budget'] == rows[0]['whole_budget'] for r in rows)
    return {'schedules_verified': schedules, 'models_verified': models,
            'same_start_and_whole_budget': True, 'hashes_verified': True}


def orchestrate(root, end_utc):
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    deadline = datetime.fromisoformat(end_utc).timestamp()
    write_json(root/'config.json', {'case': 2, 'seeds': SEEDS, 'methods': METHODS,
        'whole_budget_after_initialization': 210, 'per_round_seconds': 5, 'width': 5, 'threads': 8,
        'near_quality_ratio': 1.03, 'small_delta_limit': 50, 'min_attempts': 5,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (PROJECT_ROOT/'问题2.pdf', PROJECT_ROOT/'问题2数据.xlsx')},
        'code_sha256': snapshot_source(root/'source'), 'end_utc': end_utc,
        'formal_defaults_modified': False, 'historical_references_used': False})
    runs, completed_seeds = [], []
    def worker(phase, seed, method=None):
        tag = f'{phase}_seed{seed}_{method or "shared"}'
        args = [sys.executable, '-u', '-B', '-m', 'problem2.experiments.annealing_feedback',
                '--output', str(root), '--phase', phase, '--seed', str(seed)]
        if method:
            args += ['--method', method]
        print(json.dumps({'event': 'start', 'run': tag}), flush=True)
        with (root/f'{tag}.log').open('w', encoding='utf-8') as log:
            done = subprocess.run(args, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=max(1, min(240, deadline-time.time()-15)))
        if done.returncode:
            raise RuntimeError(f'{tag} failed; inspect log')
    for i, seed in enumerate(SEEDS):
        if deadline-time.time() < 700:
            break
        worker('prepare', seed)
        order = METHODS[i:]+METHODS[:i]
        for method in order:
            if deadline-time.time() < 220:
                break
            worker('branch', seed, method)
            runs.append(read(root/f'seed{seed}'/method/'summary.json'))
            write_json(root/'summary.json', {'complete': False, 'runs': runs,
                                             'wall_seconds': time.perf_counter()-started})
        if all((root/f'seed{seed}'/m/'summary.json').exists() for m in METHODS):
            completed_seeds.append(seed)
    verification = audit(root, completed_seeds, METHODS)
    write_json(root/'verification.json', verification)
    write_json(root/'summary.json', {'complete': len(runs) == 9, 'runs': runs,
        'wall_seconds': time.perf_counter()-started, 'verification': verification,
        'completed_seeds': completed_seeds})
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
            parser.error('branch需要method')
        branch(root, args.seed, args.method)


if __name__ == '__main__':
    main()
