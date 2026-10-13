"""范围缓存、限时初始化和建模后剩余预算的正确性验证。"""
import copy
import hashlib
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from problem2.common.encoding import Chromosome, decode, evaluate
from problem2.common.validation import validate_exact
from problem2.common.exact_cache import ExactCache
from problem2.experiments.four_methods import ComparisonConfig, initialize, run_annealing
from problem2.stage1.neighborhoods import window_constraints
from problem2.tests.test_exact_case1 import small_data
from problem2.experiments.stable_relations import optimize_once
from problem2.experiments.research_main import refine_windows


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        self.data = small_data()
        self.code = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
        self.restriction = window_constraints(self.code, 0, 1, 2)

    def test_key_requires_identical_input_reference_upper_and_conditions(self):
        cache = ExactCache()
        key = cache.key(self.data, self.code, self.restriction)
        self.assertNotEqual(key, cache.key(self.data, self.code, self.restriction, evaluate(self.data, self.code)+1))
        self.assertNotEqual(key, cache.key(self.data, self.code, window_constraints(self.code, 1, 0, 2)))
        p = list(self.data.processing)
        p[0] = (p[0][0]+1,)+p[0][1:]
        self.assertNotEqual(key, cache.key(replace(self.data, processing=tuple(p)), self.code, self.restriction))
        with self.assertRaises(ValueError):
            cache.key(self.data, self.code, None)
        other = Chromosome((1, 0, 2), self.code.b, self.code.machines)
        with self.assertRaises(ValueError):
            cache.key(self.data, other, self.restriction)

    def test_incomplete_result_is_not_certified(self):
        result = decode(self.data, self.code)
        result['proof'] = {'optimal': False}
        cache = ExactCache()
        self.assertFalse(cache.remember('unfinished', self.data, self.code, self.restriction, result, Path('not_created')))
        self.assertFalse(cache.entries)

    def test_invalid_proof_is_rejected(self):
        result = decode(self.data, self.code)
        result['proof'] = {'optimal': True, 'status': 9, 'scope': 'restricted'}
        with self.assertRaises(AssertionError):
            ExactCache().remember('bad', self.data, self.code, self.restriction, result, Path('not_created'))

    def test_expired_initialization_returns_complete_code_without_local_optimum_claim(self):
        code, info = initialize(self.data, 11, ComparisonConfig(), deadline=time.perf_counter()-1)
        code.check(self.data.n)
        validate_exact(self.data, decode(self.data, code))
        self.assertFalse(info['complete'])
        self.assertEqual(info['termination'], 'time_budget')
        self.assertEqual(info['local_optimum_kinds'], [])
        self.assertEqual(info['local_best'], evaluate(self.data, code))

    def test_expired_annealing_skips_calibration(self):
        result = run_annealing(self.data, self.code, 11, ComparisonConfig(), deadline=time.perf_counter()-1)
        self.assertEqual(result.termination['reason'], 'time_budget')
        self.assertEqual(result.termination['iterations'], 0)
        self.assertEqual(result.search.best, self.code)

    def test_normal_initialization_is_deterministic_and_completes_descent(self):
        a, info = initialize(self.data, 11, ComparisonConfig(constructions=2))
        b, other = initialize(self.data, 11, ComparisonConfig(constructions=2), deadline=time.perf_counter()+60)
        self.assertEqual(a, b)
        self.assertTrue(info['complete'] and other['complete'])


def integration():
    data = small_data()
    code = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
    cache = ExactCache()
    with tempfile.TemporaryDirectory(prefix='problem2-improvements-') as tmp:
        root = Path(tmp)
        # 两次独立阶段持有同一缓存；第二次不得调用求解器。
        first = refine_windows(data, code, {}, root/'first', budget=20, per_round=10,
                               max_rounds=1, width=1, exact_cache=cache, seed=11)
        with patch('problem2.stage1.windows.optimize_once', side_effect=AssertionError('重复建立模型')):
            second = refine_windows(data, code, {}, root/'second', budget=20, per_round=10,
                                    max_rounds=1, width=1, exact_cache=cache, seed=11)
        assert first['objective'] == second['objective']
        assert second['refinement']['cache_hits'] == 1
        assert not (root/'second/round001/model.mps').exists()
        validate_exact(data, second)
        # 证明文件被更改时拒绝复用，恢复后不影响后续核查。
        model = root/'first/round001/model.mps'
        raw = model.read_bytes()
        model.write_bytes(raw+b'\n')
        try:
            try:
                refine_windows(data, code, {}, root/'tampered', budget=20, max_rounds=1,
                               width=1, exact_cache=cache, seed=11)
            except AssertionError:
                pass
            else:
                raise AssertionError('接受了已更改的模型证明')
        finally:
            model.write_bytes(raw)
        # 建模后预算已过，TimeLimit应降为0；仍返回参考可行编码。
        r = window_constraints(code, 0, 1, 2)
        expired = optimize_once(data, code, r, root/'expired', 10, 2, deadline=time.perf_counter()-1)
        assert expired['proof']['solver_seconds_limit'] == 0
        assert not expired['proof']['optimal']
        validate_exact(data, expired)
        assert expired['objective'] <= evaluate(data, code)
        print('integration: cross-stage cache, model evidence and expired solver budget passed')


if __name__ == '__main__':
    if '--integration' in sys.argv:
        integration()
    else:
        unittest.main()
