"""退火耗时必须占用统一预算；直接组不执行退火且不换初始编码。"""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from problem2.common.encoding import Chromosome, decode, evaluate
from problem2.common.export import export, write_json
from problem2.experiments.annealing_ablation import branch
from problem2.tests.test_exact_case1 import small_data


class Clock:
    def __init__(self):
        self.value = 100.0
    def __call__(self):
        return self.value


class AnnealingAblationTests(unittest.TestCase):
    def prepare(self, root):
        data = small_data()
        code = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        folder = root/'prefix_seed23'
        export(folder/'initial', decode(data, code))
        write_json(folder/'initialization.json', {'seconds': 7})
        return data, code

    def test_annealing_time_is_subtracted_from_gurobi_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, code = self.prepare(root)
            clock, calls = Clock(), []
            def anneal(*args, **kwargs):
                self.assertEqual(kwargs['deadline'], 280)
                clock.value += 30
                return SimpleNamespace(search=SimpleNamespace(best=code, generation_history=[]),
                                       termination={'reason': 'temperature_floor'})
            def refine(*args, **kwargs):
                calls.append(kwargs)
                self.assertEqual(args[1], code)
                clock.value += kwargs['budget']
                return decode(data, code) | {'refinement': {'records': []}}
            with patch('problem2.experiments.annealing_ablation.load_case', return_value=data), \
                 patch('problem2.experiments.annealing_ablation.run_annealing', anneal), \
                 patch('problem2.experiments.annealing_ablation.refine_windows', refine), \
                 patch('problem2.experiments.annealing_ablation.print'):
                result = branch(root, 23, 'annealing', 180, timer=clock)
            self.assertEqual(calls[0]['budget'], 150)
            self.assertEqual(calls[0]['deadline'], 280)
            self.assertEqual(result['additional_seconds'], 180)
            self.assertEqual(result['annealing_seconds'], 30)
            self.assertEqual(result['full_seconds_including_initialization'], 187)

    def test_direct_group_uses_entire_budget_without_annealing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, code = self.prepare(root)
            clock, calls = Clock(), []
            def refine(*args, **kwargs):
                calls.append(kwargs)
                self.assertEqual(args[1], code)
                clock.value += kwargs['budget']
                return decode(data, code) | {'refinement': {'records': []}}
            with patch('problem2.experiments.annealing_ablation.load_case', return_value=data), \
                 patch('problem2.experiments.annealing_ablation.run_annealing') as anneal, \
                 patch('problem2.experiments.annealing_ablation.refine_windows', refine), \
                 patch('problem2.experiments.annealing_ablation.print'):
                result = branch(root, 23, 'direct', 180, timer=clock)
            anneal.assert_not_called()
            self.assertEqual(calls[0]['budget'], 180)
            self.assertFalse(calls[0]['adaptive_width'])
            self.assertEqual(calls[0]['seed'], 23)
            self.assertEqual(result['initial_code'], result['solver_start_code'])
            self.assertEqual(result['annealing_seconds'], 0)


if __name__ == '__main__':
    unittest.main()
