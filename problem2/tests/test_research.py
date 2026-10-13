"""强化时间界、相邻弧排除及区间范围的完整小实例核验。"""
import itertools
import os
import sys
import tempfile
import unittest
from pathlib import Path
from problem2.common.encoding import Chromosome, decode, evaluate, code_from_result
from problem2.common.solver import build_model, extract
from problem2.common.validation import validate_exact
from problem2.common.relation_tracking import features, signature
from problem2.common.stable_constraints import StableConstraints, arc_constants, propagated_decisions
from problem2.common.time_bounds import time_bounds
from problem2.stage1.neighborhoods import window_constraints, consensus_constraints, critical_weights, choose_window
from problem2.tests.test_exact_case1 import small_data
from problem2.tests.test_stable import codes


def restrictions():
    ref = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
    f = features(ref)
    groups = [[], [('order', 'A', 0, 1), ('order', 'A', 1, 2)],
              [('order', 'B', 0, 1), ('order', 'B', 1, 2), ('machine', 1)],
              [('adj', 'A', 0, 1), ('adj', '6-1', 0, 2), ('machine', 1)], list(f)]
    return [StableConstraints(ref, [{'key': list(k), 'value': f[k], 'basis': 'test'} for k in keys])
            for keys in groups]+[window_constraints(ref, 0, 1, 2)]


class ResearchTests(unittest.TestCase):
    def test_pruning_does_not_exclude_allowed_codes(self):
        for r in restrictions():
            m, o, a = propagated_decisions(3, *r.decisions())
            const = {q: arc_constants(3, q, m, o, a, True)[1] for q in ('A', 'B', '6-1', '6-2')}
            for code in codes(3):
                if r.satisfies(code):
                    for q, edges in signature(code)[2].items():
                        self.assertTrue(all(const[q].get(edge, 1) == 1 for edge in edges))
                        self.assertTrue(all((i, j) in edges for which, i, j in a if which == q))
                    self.assertTrue(all(code.machines[j] == v for j, v in m.items()))
        r = restrictions()[1]
        self.assertEqual(arc_constants(3, 'A', *r.decisions(), True)[1][0, 2], 0)

    def test_bounds_preserve_every_better_allowed_schedule(self):
        data = small_data()
        for r in restrictions():
            horizon = evaluate(data, r.reference)
            ls, lc, us, uc, objective = time_bounds(data, horizon, *propagated_decisions(3, *r.decisions()))
            for code in codes(3):
                cost = evaluate(data, code)
                if not r.satisfies(code) or cost > horizon:
                    continue
                result = decode(data, code)
                self.assertLessEqual(objective, cost)
                for row in result['operations']:
                    key = row['job'], row['station']-1
                    self.assertLessEqual(ls[key], row['start'])
                    self.assertLessEqual(row['start'], us[key])
                    self.assertLessEqual(lc[key], row['finish'])
                    self.assertLessEqual(row['finish'], uc[key])

    def test_windows_fix_positions_outside_and_free_machines(self):
        r = restrictions()[-1]
        for code in codes(3):
            expected = (code.a[-1] == 2 and code.b[0] == 0)
            self.assertEqual(r.satisfies(code), expected)

    def test_independent_consensus_and_critical_selection(self):
        import random
        ref = restrictions()[0].reference
        other = Chromosome((1, 0, 2), ref.b, (1, 1, 0))
        r, uncertainty, info = consensus_constraints(ref, [[(ref, 100)], [(other, 101)]])
        self.assertEqual(info['supported_seeds'], 2)
        self.assertTrue(r.satisfies(ref) and r.satisfies(other))
        self.assertEqual(uncertainty['machine', 0], 0.5)
        weights = critical_weights(small_data(), ref)
        self.assertGreater(sum(weights['A'].values())+sum(weights['B'].values()), 0)
        seen = set()
        for iteration in range(4):
            self.assertIsNotNone(choose_window(small_data(), ref, 2, uncertainty, seen, iteration, random.Random(11)))
        self.assertIsNone(choose_window(small_data(), ref, 2, uncertainty, seen, 4, random.Random(11)))


def integration(compact=False):
    data = small_data()
    for index, r in enumerate(restrictions()):
        allowed = [code for code in codes(3) if r.satisfies(code)]
        expected = min(evaluate(data, code) for code in allowed)
        original = Path.cwd()
        with tempfile.TemporaryDirectory(prefix='problem2-strengthened-') as temp:
            try:
                os.chdir(temp)
                env, model = build_model(data, decode(data, r.reference), Path(temp), 30, 2,
                                         stable_constraints=r, strengthen=True, compact=compact)
                try:
                    model.optimize()
                    assert model.Status == 2
                    def value(name):
                        v = model.getVarByName(name)
                        return v.X if v is not None else model._fixed_values.get(name, 0)
                    result = extract(data, value)
                    validate_exact(data, result)
                    assert r.satisfies(code_from_result(result, data.n))
                    assert abs(result['objective']-expected) < 1e-4
                    assert abs(model.ObjBound-expected) < 1e-4
                    print(f'compact={compact}, case={index}, allowed={len(allowed)}, optimum={expected}, '
                          f'binaries={model.NumBinVars}, constraints={model.NumConstrs}')
                finally:
                    model.dispose()
                    env.dispose()
            finally:
                os.chdir(original)


if __name__ == '__main__':
    if '--integration' in sys.argv:
        integration(compact='--compact' in sys.argv)
    else:
        unittest.main()
