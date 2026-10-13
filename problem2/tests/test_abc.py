"""持续记录不改变退火轨迹；筛选保留参考解；静态计数与小模型穷举核验。"""
import itertools
import random
import sys
import tempfile
import unittest
from pathlib import Path
from problem2.common.annealing_records import (AnnealingRecords, SelectionConfig,
        changed_relations, select_relations, model_counts, release_weak)
from problem2.common.encoding import Chromosome, evaluate, decode, code_from_result
from problem2.common.local_search import combined_operations, apply_move, random_neighbor
from problem2.common.relation_tracking import features
from problem2.common.stable_constraints import StableConstraints
from problem2.common.solver_utils import optimize_once
from problem2.common.validation import validate_exact
from problem2.stage1.annealing import run_annealing
from problem2.stage1.config import ComparisonConfig
from problem2.tests.test_exact_case1 import small_data


def all_codes(n):
    for a in itertools.permutations(range(n)):
        for b in itertools.permutations(range(n)):
            for machines in itertools.product((0, 1), repeat=n):
                yield Chromosome(a, b, machines)


class BasicTrace:
    def __init__(self):
        self.trials, self.accepted_codes = [], []
        self.initial_temperature = None

    def trial(self, before, after, before_cost, cost, temperature=None):
        self.trials.append((before, after, before_cost, cost, temperature))

    def accepted(self, code, cost):
        self.accepted_codes.append((code, cost))


class RecordedTrace(AnnealingRecords):
    def __init__(self, *args):
        super().__init__(*args)
        self.trace = BasicTrace()

    def trial(self, *args, **kwargs):
        super().trial(*args, **kwargs)
        self.trace.trial(*args, **kwargs)

    def accepted(self, code, cost):
        super().accepted(code, cost)
        self.trace.accepted(code, cost)


class ABCBehaviorTests(unittest.TestCase):
    def test_changed_pairs_exactly_match_all_features(self):
        rng = random.Random(53)
        for _ in range(12):
            a, b = list(range(5)), list(range(5))
            rng.shuffle(a); rng.shuffle(b)
            code = Chromosome(tuple(a), tuple(b), tuple(rng.randrange(2) for _ in a))
            original = features(code)
            for operation in combined_operations(5):
                after = features(apply_move(code, operation))
                expected = {k: v for k, v in original.items()
                            if k[0] in ('machine', 'order') and after[k] != v}
                self.assertEqual(dict(changed_relations(code, operation)), expected)

    def test_callback_uses_same_draw_and_candidate(self):
        code = Chromosome((0, 1, 2), (2, 0, 1), (0, 1, 0))
        first, second = random.Random(23), random.Random(23)
        seen = []
        for _ in range(100):
            self.assertEqual(random_neighbor(code, first), random_neighbor(code, second, seen.append))
        self.assertEqual(first.getstate(), second.getstate())
        self.assertEqual(len(seen), 100)

    def test_full_trial_and_acceptance_sequence_unchanged(self):
        data = small_data()
        code = Chromosome((0, 1, 2), (2, 0, 1), (0, 1, 0))
        cfg = ComparisonConfig(sa_moves=13, sa_cooling=.6, sa_ratio=.01, sa_temperature_multiplier=2)
        plain_trace = BasicTrace()
        plain = run_annealing(data, code, 37, cfg, observer=plain_trace)
        recorder = RecordedTrace(code, evaluate(data, code), 37)
        recorded = run_annealing(data, code, 37, cfg, observer=recorder)
        self.assertEqual(plain_trace.trials, recorder.trace.trials)
        self.assertEqual(plain_trace.accepted_codes, recorder.trace.accepted_codes)
        self.assertEqual(plain.termination, recorded.termination)
        self.assertEqual(plain.search.best, recorded.search.best)
        self.assertEqual(plain.search.best_cost, recorded.search.best_cost)

    def test_stats_continue_after_acceptance_and_return(self):
        code = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        other = apply_move(code, ('flip', 1, 1))
        tracker = AnnealingRecords(code, 100, 11)
        tracker.initial_temperature = 100
        for before, after, old, new in ((code, other, 100, 110), (other, code, 110, 100), (code, other, 100, 110)):
            tracker.operation(('flip', 1, 1))
            tracker.trial(before, after, old, new, temperature=100)
            tracker.accepted(after, new)
        row = tracker.stats['machine', 1]
        self.assertEqual(row['attempts'], [2, 1])
        self.assertEqual(row['accepted'], [2, 1])

    def test_distinct_samples_insufficient_attempts_and_veto(self):
        reference = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        samples = [reference, Chromosome(reference.a, reference.b, (1, 0, 0))]
        config = SelectionConfig(min_samples=2, min_attempts=2)
        def report(seed, attempts):
            return {'seed': seed, 'best_cost': 100,
                    'samples': [{'code': c.as_dict(), 'objective': 100} for c in samples],
                    'relations': [{'key': ['machine', 2], 'attempts': [attempts, 0]}]}
        r, evidence = select_relations(reference, 100, [report(11, 1), report(23, 1)], config)
        self.assertEqual([row['key'] for row in r.records], [['machine', 2]])
        self.assertTrue(r.satisfies(reference))
        r, _ = select_relations(reference, 100, [report(11, 0), report(23, 0)], config)
        self.assertEqual(r.records, [])
        duplicate = report(23, 1)
        duplicate['samples'] = [duplicate['samples'][0]]*10
        r, evidence = select_relations(reference, 100, [report(11, 1), duplicate], config)
        self.assertEqual(r.records, [])
        with self.assertRaises(ValueError):
            select_relations(reference, 100, [report(11, 1), report(11, 1)], config)
        # 95%以上一致也不能忽略已经找到的同等质量相反编码。
        broad = [report(11, 20), report(23, 20)]
        bad = Chromosome(reference.a, reference.b, (0, 0, 1))
        broad[1]['samples'].append({'code': bad.as_dict(), 'objective': 100})
        r, _ = select_relations(reference, 100, broad, SelectionConfig(min_samples=2, agreement=.6))
        self.assertEqual(r.records, [])

    def test_releasing_recomputes_transitive_relations(self):
        reference = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        rows = [{'key': ['order', 'A', 0, 1], 'value': 1, 'minimum_agreement': .96, 'eligible': 20},
                {'key': ['order', 'A', 1, 2], 'value': 1, 'minimum_agreement': 1, 'eligible': 40}]
        restriction = StableConstraints(reference, rows)
        self.assertIn(('A', 0, 2), restriction.decisions()[1])
        relaxed = release_weak(restriction)
        self.assertNotIn(('A', 0, 2), relaxed.decisions()[1])
        alternative = Chromosome((1, 2, 0), reference.b, reference.machines)
        self.assertTrue(relaxed.satisfies(alternative))


def integration():
    data = small_data()
    reference = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
    choices = [[], [('machine', 2)], [('order', 'A', 0, 2), ('machine', 2)]]
    actual = features(reference)
    for keys in choices:
        restriction = StableConstraints(reference, [{'key': list(k), 'value': actual[k],
                        'minimum_agreement': 1, 'eligible': 20} for k in keys])
        allowed = [c for c in all_codes(3) if restriction.satisfies(c)]
        optimum = min(evaluate(data, c) for c in allowed)
        with tempfile.TemporaryDirectory(prefix='problem2-abc-test-') as temp:
            result = optimize_once(data, reference, restriction, Path(temp)/'round', 30, 2,
                                   strengthen=True, compact=True)
            self_count = model_counts(restriction)['binary_variables']
            assert result['proof']['optimal']
            assert abs(result['objective']-optimum) <= 1e-4
            assert result['proof']['reduction']['binary_variables'] == self_count
            assert restriction.satisfies(code_from_result(result, 3))
            validate_exact(data, result)
            print(f'ABC integration: fixed={len(keys)}, allowed={len(allowed)}, optimum={optimum}, binaries={self_count}')


if __name__ == '__main__':
    if '--integration' in sys.argv:
        integration()
    else:
        unittest.main()
