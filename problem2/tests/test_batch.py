"""批量完整评分、缓存与截止时间边界；不借用课程算例已知最优值。"""
import itertools
import time
import unittest
from dataclasses import replace
from unittest.mock import patch
from problem2.common.encoding import BatchEvaluator, Chromosome, decode, evaluate
from problem2.common.validation import validate_exact
from problem2.experiments.genetic import Evaluator, BudgetExpired
from problem2.common.local_search import descend
from problem2.tests.test_exact_case1 import small_data
from problem2.tests.test_stable import codes


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.data = small_data()
        self.codes = list(codes(self.data.n))

    def test_every_small_code_matches_scalar_and_validated_schedule(self):
        actual = BatchEvaluator(self.data).evaluate(self.codes)
        self.assertEqual(actual, [evaluate(self.data, c) for c in self.codes])
        for code, value in zip(self.codes, actual):
            result = decode(self.data, code)
            validate_exact(self.data, result)
            self.assertEqual(value, result['objective'])

    def test_invalid_code_and_empty_batch(self):
        scorer = BatchEvaluator(self.data)
        self.assertEqual(scorer.evaluate([]), [])
        with self.assertRaises(ValueError):
            scorer.evaluate([Chromosome((0, 0, 2), (0, 1, 2), (0, 0, 0))])
        with self.assertRaises(TypeError):
            scorer.evaluate([Chromosome((0.0, 1, 2), (0, 1, 2), (0, 0, 0))])

    def test_unused_diagonal_does_not_affect_score_or_overflow_check(self):
        data = replace(self.data, setup=tuple(tuple(10**100 if i == j else value for j, value in enumerate(row))
                                              for i, row in enumerate(self.data.setup)))
        self.assertEqual(BatchEvaluator(data).evaluate(self.codes), [evaluate(self.data, c) for c in self.codes])

    def test_time_overflow_is_explicitly_rejected(self):
        data = replace(self.data, processing=((2**62,)*10,)*3)
        with self.assertRaises(OverflowError):
            BatchEvaluator(data)

    def test_order_cache_eviction_and_best_match_scalar_requests(self):
        requests = self.codes[:17]+self.codes[:7]+self.codes[20:31]
        scalar, batch = Evaluator(self.data, cache_limit=3), Evaluator(self.data, cache_limit=3, batch_size=8)
        expected = [scalar.cost(c) for c in requests]
        actual = list(batch.costs(iter(requests)))
        self.assertEqual([c for c, _ in actual], requests)
        self.assertEqual([v for _, v in actual], expected)
        self.assertEqual((batch.best, batch.best_cost), (scalar.best, scalar.best_cost))
        self.assertTrue(all(type(v) is int for _, v in actual))

    def test_expired_batch_does_not_score_candidates(self):
        evaluator = Evaluator(self.data, batch_size=8)
        evaluator.deadline = time.perf_counter()-1
        with patch.object(evaluator.batch_evaluator, 'evaluate', side_effect=AssertionError('不应评分')):
            with self.assertRaises(BudgetExpired):
                list(evaluator.costs(self.codes))
        self.assertEqual(evaluator.evaluations, 0)

    def test_completed_batch_is_recorded_before_next_batch_expires(self):
        evaluator = Evaluator(self.data, batch_size=2)
        original = evaluator.batch_evaluator.evaluate
        def expire(selected):
            values = original(selected)
            evaluator.deadline = time.perf_counter()-1
            return values
        with patch.object(evaluator.batch_evaluator, 'evaluate', side_effect=expire):
            with self.assertRaises(BudgetExpired):
                list(evaluator.costs(self.codes[:3]))
        self.assertEqual(evaluator.evaluations, 2)
        self.assertEqual(evaluator.best_cost, min(evaluate(self.data, c) for c in self.codes[:2]))
        validate_exact(self.data, decode(self.data, evaluator.best))

    def test_full_descent_has_same_code_and_improvements(self):
        for code in itertools.islice(self.codes, 0, 80, 11):
            scalar, batch = Evaluator(self.data), Evaluator(self.data, batch_size=8)
            self.assertEqual(descend(code, scalar), descend(code, batch))
            self.assertEqual([r['best'] for r in scalar.progress], [r['best'] for r in batch.progress])


if __name__ == '__main__':
    unittest.main()
