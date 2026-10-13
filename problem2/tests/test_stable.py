"""关系证据、固定约束与缩小模型验证；--integration 对照小实例穷举。"""
import itertools
import os
import sys
import tempfile
import unittest
from pathlib import Path
from problem2.common.encoding import Chromosome, decode, evaluate, code_from_result
from problem2.common.solver import build_model, extract
from problem2.common.validation import validate_exact
from problem2.experiments.four_methods import ComparisonConfig, run_method
from problem2.common.relation_tracking import RelationTracker, EvidenceConfig, features, signature, matches
from problem2.common.stable_constraints import StableConstraints, arc_constants
from problem2.tests.test_exact_case1 import small_data


def codes(n):
    for a in itertools.permutations(range(n)):
        for b in itertools.permutations(range(n)):
            for machines in itertools.product((0, 1), repeat=n):
                yield Chromosome(a, b, machines)


class StableTests(unittest.TestCase):
    def setUp(self):
        self.code = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
        self.flipped = Chromosome(self.code.a, self.code.b, (1, 1, 0))

    def test_features_and_signature(self):
        for code in codes(3):
            f = features(code)
            sig = signature(code)
            self.assertTrue(all(matches(k, v, sig) for k, v in f.items()))
            self.assertIn(('adj', '6-1', -1, 3), f) if all(code.machines) else None

    def test_annealing_requires_exploration_and_high_temperature(self):
        t = RelationTracker(self.code, 100, 'annealing')
        t.initial_temperature = 100
        for _ in range(20):
            t.trial(self.code, self.flipped, 100, 150, temperature=0.01)
        row = next(r for r in t.report(self.code, 100)['relations'] if r['key'] == ['machine', 0])
        self.assertFalse(row['selected'])
        for _ in range(5):
            t.trial(self.code, self.flipped, 100, 150, temperature=100)
        row = next(r for r in t.report(self.code, 100)['relations'] if r['key'] == ['machine', 0])
        self.assertTrue(row['selected'])
        t.accepted(self.flipped, 150)
        t.accepted(self.code, 100)
        row = next(r for r in t.report(self.code, 100)['relations'] if r['key'] == ['machine', 0])
        self.assertFalse(row['whole_run_stable'])
        self.assertFalse(row['selected'])

    def test_tabu_excludes_blocked_trials(self):
        t = RelationTracker(self.code, 100, 'tabu')
        for _ in range(30):
            t.trial(self.code, self.flipped, 100, 110, blocked=True)
            t.tabu_selected(101)
        row = next(r for r in t.report(self.code, 100)['relations'] if r['key'] == ['machine', 0])
        self.assertFalse(row['selected'])
        for _ in range(20):
            t.trial(self.code, self.flipped, 100, 110)
            t.tabu_selected(101)
        row = next(r for r in t.report(self.code, 100)['relations'] if r['key'] == ['machine', 0])
        self.assertTrue(row['selected'])
        self.assertEqual(row['selection_gap_min'], 9)

    def test_vns_restoration(self):
        t = RelationTracker(self.code, 100, 'vns')
        for _ in range(10):
            t.perturbation(self.code, self.flipped, self.code, 100, 100)
        row = next(r for r in t.report(self.code, 100)['relations'] if r['key'] == ['machine', 0])
        self.assertTrue(row['selected'])
        self.assertEqual(row['restored'], 10)

    def test_duplicate_samples_and_best_compatibility(self):
        t = RelationTracker(self.code, 100, 'vns')
        for _ in range(100):
            t.sample(self.code, 100)
        report = t.report(self.code, 100)
        self.assertEqual(report['late_distinct_samples'], 1)
        self.assertFalse(any(r['selected'] for r in report['relations']))
        bad = {'key': ['machine', 0], 'value': 1, 'basis': 'whole_run', 'selected': True}
        self.assertEqual(StableConstraints.from_evidence(self.code, {'relations': [bad]}).records, [])

    def test_arc_removal_and_reference_preservation(self):
        rows = [{'key': ['adj', 'A', 0, 1], 'value': 1, 'basis': 'whole_run'},
                {'key': ['machine', 1], 'value': 1, 'basis': 'whole_run'}]
        r = StableConstraints(self.code, rows)
        self.assertTrue(r.satisfies(self.code))
        machines, orders, fixed = r.decisions()
        _, constants = arc_constants(3, 'A', machines, orders, fixed)
        self.assertEqual(constants[0, 1], 1)
        self.assertEqual(constants[0, 2], 0)
        self.assertEqual(constants[2, 1], 0)
        _, machine_constants = arc_constants(3, '6-1', machines, orders, fixed)
        self.assertEqual(machine_constants[-1, 1], 0)
        for code in codes(3):
            if r.satisfies(code):
                for q, edges in signature(code)[2].items():
                    _, const = arc_constants(3, q, machines, orders, fixed)
                    self.assertTrue(all(const.get(edge, 1) == 1 for edge in edges))
        relaxed = r.relaxed(0.5)
        self.assertEqual(len(relaxed.records), 1)
        self.assertTrue(relaxed.satisfies(self.code))

    def test_late_samples_separate_from_full_history(self):
        config = EvidenceConfig(min_late_samples=2)
        t = RelationTracker(self.code, 100, 'vns', config)
        # 两个不同且同质量的编码，只固定其交集；重复编码不增加支持。
        other = Chromosome((1, 0, 2), self.code.b, self.code.machines)
        t.accepted(other, 100)
        report = t.report(other, 100)
        selected = [r for r in report['relations'] if r['selected']]
        self.assertTrue(selected)
        self.assertTrue(all(r['basis'] == 'late_samples' for r in selected))
        restrictions = StableConstraints.from_evidence(other, report)
        self.assertTrue(restrictions.satisfies(other))
        self.assertTrue(restrictions.satisfies(self.code))

    def test_observer_does_not_change_search(self):
        d = small_data()
        cfg = ComparisonConfig(vns_failures=3, tabu_stall=20, sa_moves=10, sa_cooling=0.5, sa_ratio=0.125)
        for method in ('annealing', 'tabu', 'vns'):
            plain = run_method(method, d, self.code, 11, cfg)
            tracker = RelationTracker(self.code, evaluate(d, self.code), method)
            tracked = run_method(method, d, self.code, 11, cfg, tracker)
            self.assertEqual((plain.search.best, plain.search.best_cost, plain.termination),
                             (tracked.search.best, tracked.search.best_cost, tracked.termination))
            self.assertEqual([(r['best']) for r in plain.search.progress],
                             [(r['best']) for r in tracked.search.progress])
            self.assertEqual([(r['best']) for r in plain.search.generation_history],
                             [(r['best']) for r in tracked.search.generation_history])


def integration():
    d = small_data()
    reference = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
    all_features = features(reference)
    mixed = [('order', 'A', 0, 2), ('adj', 'B', 0, 1), ('machine', 1), ('adj', '6-1', 0, 2)]
    cases = [[], mixed, list(all_features)]
    for keys in cases:
        restriction = StableConstraints(reference, [{'key': list(k), 'value': all_features[k],
                                                      'basis': 'whole_run'} for k in keys])
        allowed = [code for code in codes(3) if restriction.satisfies(code)]
        expected = min(evaluate(d, code) for code in allowed)
        original = Path.cwd()
        with tempfile.TemporaryDirectory(prefix='problem2-stable-test-') as temporary:
            try:
                os.chdir(temporary)
                env, model = build_model(d, decode(d, reference), Path(temporary), 30, 2,
                                         stable_constraints=restriction)
                try:
                    model.optimize()
                    assert model.Status == 2
                    def value(name):
                        var = model.getVarByName(name)
                        return var.X if var is not None else model._fixed_values.get(name, 0)
                    result = extract(d, value)
                    validate_exact(d, result)
                    assert restriction.satisfies(code_from_result(result, d.n))
                    assert abs(result['objective']-expected) <= 1e-4
                    assert abs(model.ObjBound-expected) <= 1e-4
                    if len(keys) == len(all_features):
                        assert model.NumBinVars == 0
                    print(f'fixed={len(keys)}, allowed={len(allowed)}, optimum={expected}, binaries={model.NumBinVars}')
                finally:
                    model.dispose()
                    env.dispose()
            finally:
                os.chdir(original)


if __name__ == '__main__':
    if '--integration' in sys.argv:
        integration()
    else:
        unittest.main()
