"""起点筛选、原初始化兼容、统一截止与完整调度的验证。"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from problem2.common.encoding import Chromosome, evaluate, decode
from problem2.common.validation import validate_exact
from problem2.experiments.four_methods import initialize, ComparisonConfig
from problem2.stage2.multistart import (differences, select_starts, from_dict, worker,
                              collect_worker, read_json_if_ready)
from problem2.tests.test_exact_case1 import small_data


class MultistartTests(unittest.TestCase):
    def setUp(self):
        self.data = small_data()
        self.code = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 1))

    def test_retention_does_not_change_original_search(self):
        for seed in (11, 23, 37):
            first, old = initialize(self.data, seed, ComparisonConfig(constructions=3))
            second, new = initialize(self.data, seed, ComparisonConfig(constructions=3), retain_candidates=True)
            self.assertEqual(first, second)
            for key in ('trace', 'evaluations', 'cache_hits', 'code', 'local_best'):
                self.assertEqual(old[key], new[key])
            self.assertNotIn('candidates', old)
            self.assertIn(first, [from_dict(r['code']) for r in new['candidates']])
            for record in new['candidates']:
                code = from_dict(record['code'])
                self.assertEqual(evaluate(self.data, code), record['objective'])
                validate_exact(self.data, decode(self.data, code))

    def test_pair_order_and_machine_differences(self):
        other = Chromosome((2, 1, 0), (1, 0, 2), (1, 0, 0))
        self.assertEqual(differences(self.code, other), (3, 1, 2))
        self.assertEqual(differences(other, self.code), (3, 1, 2))
        self.assertEqual(differences(self.code, self.code), (0, 0, 0))

    def test_selection_retains_best_and_diversity_within_quality_bound(self):
        near = Chromosome((1, 0, 2), self.code.b, self.code.machines)
        far = Chromosome((2, 1, 0), (2, 1, 0), (1, 1, 0))
        bad = Chromosome((1, 2, 0), self.code.b, self.code.machines)
        records = [{'code': c.as_dict(), 'objective': value}
                   for c, value in ((near, 101), (bad, 120), (far, 109), (self.code, 100), (far, 109))]
        selected, info = select_starts(records, 2, 0.10)
        self.assertEqual([from_dict(r['code']) for r in selected], [self.code, far])
        self.assertEqual(info['unique_candidates'], 4)
        self.assertEqual(info['eligible_candidates'], 3)
        self.assertEqual(select_starts(records, 4, 0)[1]['actual_workers'], 1)

    def test_expired_initialization_returns_valid_fallback(self):
        code, info = initialize(self.data, 11, ComparisonConfig(), deadline=time.perf_counter()-1,
                                retain_candidates=True)
        self.assertFalse(info['complete'])
        self.assertFalse(info['candidates'][0]['descent_complete'])
        validate_exact(self.data, decode(self.data, code))

    def test_shared_expired_deadline_does_not_grant_another_budget(self):
        started = time.perf_counter()-5
        deadline = started+1
        with tempfile.TemporaryDirectory(prefix='problem2-multistart-') as directory:
            for number in (1, 2):
                folder = Path(directory)/str(number)
                worker(self.data, self.code, folder, deadline, started, number, 2, 3, 1)
                code, row, history = collect_worker(self.data, folder, self.code, number, started)
                self.assertEqual(code, self.code)
                self.assertEqual(row['enumerations'], 0)
                self.assertTrue(row['complete'])
                self.assertTrue(row['validation']['valid'])
                self.assertEqual(row['solver_calls'], 0)
                self.assertEqual(history, [])

    def test_truncated_checkpoint_is_retried_and_forged_value_rejected(self):
        with tempfile.TemporaryDirectory(prefix='problem2-multistart-check-') as directory:
            folder = Path(directory)
            path = folder/'checkpoint.json'
            path.write_text('{', encoding='utf-8')
            self.assertIsNone(read_json_if_ready(path))
            path.write_text(json.dumps({'best': -1, 'code': self.code.as_dict()}), encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, '目标值'):
                collect_worker(self.data, folder, self.code, 1, time.perf_counter())


if __name__ == '__main__':
    unittest.main()
