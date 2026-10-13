"""检查独立一阶段入口的完整调度、截止处理及拒绝覆盖。"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from problem2.common.validation import validate_exact
from problem2.stage1.config import ComparisonConfig
from problem2.stage1.main import run
from problem2.tests.test_exact_case1 import small_data


class Stage1Tests(unittest.TestCase):
    def test_complete_pipeline_without_solver(self):
        data = small_data()
        config = ComparisonConfig(constructions=1, sa_moves=2, sa_cooling=0.5, sa_ratio=0.99)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'run'
            result = run(data, output, seed=11, seconds=10, max_rounds=0, config=config)
            validate_exact(data, result)
            summary = json.loads((output/'summary.json').read_text(encoding='utf-8'))
            self.assertTrue(summary['complete'])
            self.assertFalse(summary['uses_saved_reference'])
            self.assertEqual(summary['final'], result['objective'])
            self.assertEqual(summary['annealing_termination']['reason'], 'temperature_floor')
            self.assertTrue((output/'source/common/encoding.py').is_file())
            self.assertTrue((output/'source/stage1/main.py').is_file())

    def test_expired_budget_keeps_complete_feasible_schedule(self):
        data = small_data()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'run'
            result = run(data, output, seconds=1, started=time.perf_counter()-10)
            validate_exact(data, result)
            summary = json.loads((output/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['annealing_termination']['reason'], 'time_budget')
            self.assertIsNone(summary['refinement'])
            with self.assertRaises(FileExistsError):
                run(data, output, seconds=1)


if __name__ == '__main__':
    unittest.main()
