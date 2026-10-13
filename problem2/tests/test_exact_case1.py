"""一般模型的边界测试；可选小实例穷举与 Gurobi 精确模型对照。"""
import copy
import itertools
import os
import sys
import tempfile
import unittest
from pathlib import Path
from problem2.common.data import CaseData, m62_duration
from problem2.common.solver import decode, build_model, extract
from problem2.common.validation import validate_exact


def small_data():
    return CaseData(0, ('J1', 'J2', 'J3'),
                    ((3, 2, 4, 1, 3, 11, 4, 2, 3, 1),
                     (2, 4, 1, 3, 2, 7, 3, 4, 1, 2),
                     (4, 1, 3, 2, 1, 9, 2, 1, 4, 3)),
                    ((0, 8, 2), (1, 0, 7), (4, 3, 0)))


class ExactTests(unittest.TestCase):
    def test_round_half_up(self):
        self.assertEqual(m62_duration(834), 1001)

    def test_waiting_and_ties(self):
        d = CaseData(0, ('J1', 'J2'), ((1,)*5+(100,)+(1,)*4, (1,)*10), ((0, 3), (7, 0)))
        result = decode(d, [0, 1], [0, 1], [0, 1])
        validate_exact(d, result)
        rows = {(r['job'], r['station']): r for r in result['operations']}
        self.assertEqual(rows[0, 6]['finish'], rows[1, 6]['finish'])
        self.assertGreater(rows[1, 6]['start'], rows[1, 6]['arrival'])
        self.assertEqual(rows[1, 6]['start'], rows[1, 6]['setup_start'])  # 各队首免换模

    def test_reject_anticipatory_setup(self):
        d = small_data()
        result = decode(d, [0, 1, 2], [0, 1, 2], [0, 0, 0])
        bad = copy.deepcopy(result)
        r = next(r for r in bad['operations'] if r['job'] == 1 and r['station'] == 2)
        shift = r['setup_start']-r['arrival']+1
        for key in ('start', 'finish', 'setup_start', 'setup_finish'):
            r[key] -= shift
        with self.assertRaisesRegex(AssertionError, '提前换模'):
            validate_exact(d, bad)

    def test_exhaustive_decoding(self):
        d = small_data()
        count = 0
        for a in itertools.permutations(range(d.n)):
            for b in itertools.permutations(range(d.n)):
                for machines in itertools.product(range(2), repeat=d.n):
                    validate_exact(d, decode(d, a, b, machines))
                    count += 1
        self.assertEqual(count, 288)


def integration():
    """穷举全体前段、完工顺序、归属；模型最优值必须一致。"""
    d = small_data()
    solutions = (decode(d, a, b, m) for a in itertools.permutations(range(d.n))
                 for b in itertools.permutations(range(d.n))
                 for m in itertools.product(range(2), repeat=d.n))
    best = min(solutions, key=lambda r: r['objective'])
    original = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='problem2-exact-test-') as temporary:
        try:
            os.chdir(temporary)
            env, model = build_model(d, best, Path(temporary), 60, 2)
            try:
                model.optimize()
                assert model.Status == 2
                result = extract(d, lambda name: model.getVarByName(name).X)
                validate_exact(d, result)
                assert abs(result['objective']-best['objective']) < 1e-4
                print(f'288 个候选穷举与 MILP 一致：{best["objective"]}；下界 {model.ObjBound}')
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
