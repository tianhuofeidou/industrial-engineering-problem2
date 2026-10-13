"""固定宽度不自动改变；区间穷举与全部允许编码一致。"""
import itertools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from problem2.common.encoding import Chromosome, decode, evaluate
from problem2.experiments.stage1_width_comparison import enumerate_window
from problem2.stage1.neighborhoods import window_constraints
from problem2.stage1.windows import refine_windows
from problem2.tests.test_exact_case1 import small_data


class WidthComparisonTests(unittest.TestCase):
    def test_enumeration_is_all_allowed_codes_with_overlapping_windows(self):
        data = small_data()
        ref = Chromosome((0, 1, 2), (2, 0, 1), (0, 1, 0))
        restriction = window_constraints(ref, 0, 1, 2)
        allowed = [c for a in itertools.permutations(range(3))
                   for b in itertools.permutations(range(3))
                   for m in itertools.product((0, 1), repeat=3)
                   if restriction.satisfies(c := Chromosome(a, b, m))]
        result, stats = enumerate_window(data, ref, 0, 1, 2)
        self.assertEqual(stats['evaluations'], len(allowed))
        self.assertEqual(evaluate(data, result), min(evaluate(data, c) for c in allowed))
        self.assertTrue(restriction.satisfies(result))

    def test_width_one_still_considers_each_free_machine(self):
        data = small_data()
        ref = Chromosome((0, 1, 2), (2, 0, 1), (0, 1, 0))
        result, stats = enumerate_window(data, ref, 0, 0, 1)
        self.assertEqual(stats['evaluations'], 4)
        self.assertEqual(result.a, ref.a)
        self.assertEqual(result.b, ref.b)

    def test_fixed_width_disables_both_expansion_and_shrinkage(self):
        from problem2.common.data import CaseData
        data = CaseData(2, tuple(f'J{i+1}' for i in range(10)),
                        ((1,)*10,)*10, tuple((0,)*10 for _ in range(10)))
        ref = Chromosome(tuple(range(10)), tuple(range(10)), (0,)*10)
        def fake_solve(data, reference, restriction, folder, *args, **kwargs):
            folder.mkdir(parents=True)
            result = decode(data, reference)
            result['proof'] = {'optimal': optimal, 'reduction': {'binary_variables': 0},
                               'runtime': 0, 'status': 2 if optimal else 9}
            return result
        for optimal in (True, False):
            with self.subTest(optimal=optimal), tempfile.TemporaryDirectory() as temp:
                with patch('problem2.stage1.windows.optimize_once', fake_solve), \
                     patch('problem2.stage1.windows.print'):
                    fixed = refine_windows(data, ref, {}, Path(temp)/'fixed', budget=10,
                        max_rounds=8, width=5, cache_enabled=False, adaptive_width=False)
                    default = refine_windows(data, ref, {}, Path(temp)/'default', budget=10,
                        max_rounds=8, width=5, cache_enabled=False)
                self.assertEqual({r['width'] for r in fixed['refinement']['records']}, {5})
                self.assertEqual({r['width'] for r in default['refinement']['records']},
                                 {5, 7} if optimal else {5, 3})

    def test_fixed_width_stops_on_exhaustion(self):
        data = small_data()
        ref = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        with tempfile.TemporaryDirectory() as temp, \
             patch('problem2.stage1.windows.choose_window', return_value=None) as chooser:
            result = refine_windows(data, ref, {}, Path(temp), budget=10, max_rounds=8,
                                    width=1, cache_enabled=False, adaptive_width=False)
            self.assertEqual(chooser.call_count, 1)
            self.assertEqual(result['refinement']['records'], [])


if __name__ == '__main__':
    unittest.main()
