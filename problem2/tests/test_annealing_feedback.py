"""观察器保持退火轨迹；区间评分只使用实际开放的关系。"""
from pathlib import Path
import random
import unittest

from problem2.common.encoding import Chromosome, evaluate
from problem2.experiments.annealing_feedback import FeedbackObserver, relation_weights, score_window, FeedbackSelector
from problem2.stage1.annealing import run_annealing
from problem2.stage1.config import ComparisonConfig
from problem2.stage1.neighborhoods import window_constraints
from problem2.tests.test_exact_case1 import small_data


class AnnealingFeedbackTests(unittest.TestCase):
    def test_recording_preserves_trajectory_and_acceptance(self):
        data = small_data()
        ref = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        cfg = ComparisonConfig(sa_moves=30, sa_cooling=.5, sa_ratio=.001, sa_temperature_multiplier=2)
        plain = run_annealing(data, ref, 23, cfg)
        tracker = FeedbackObserver(ref, evaluate(data, ref), 23)
        tracked = run_annealing(data, ref, 23, cfg, observer=tracker)
        self.assertEqual(plain.search.best, tracked.search.best)
        self.assertEqual(plain.termination, tracked.termination)
        fields = ('iteration', 'temperature', 'accepted', 'current', 'uphill_accepted')
        self.assertEqual([[r[k] for k in fields] for r in plain.search.generation_history],
                         [[r[k] for k in fields] for r in tracked.search.generation_history])

    def test_relationship_needs_both_endpoints_free(self):
        ref = Chromosome(tuple(range(6)), tuple(range(6)), (0,)*6)
        weights = {('order', 'A', 0, 5): 1.0}
        for a in range(5):
            self.assertEqual(score_window(ref, a, 0, 2, weights), 0)
        self.assertEqual(score_window(ref, 0, 0, 6, weights), 1)

    def test_machine_union_is_not_double_counted(self):
        ref = Chromosome(tuple(range(3)), tuple(range(3)), (0,)*3)
        self.assertEqual(score_window(ref, 0, 0, 2, {('machine', 0): 1}), 1)
        self.assertEqual(score_window(ref, 1, 1, 2, {('machine', 0): 1}), 0)

    def test_weights_recomputed_against_current_reference(self):
        ref = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        flipped = Chromosome(ref.a, ref.b, (1, 0, 0))
        report = {'samples': [{'code': ref.as_dict(), 'objective': 100}],
                  'near_relations': [{'key': ['machine', 0], 'attempts': [10, 10], 'small_delta': [8, 2]}]}
        w, _ = relation_weights(ref, 100, report, 'trials')
        other, _ = relation_weights(flipped, 100, report, 'trials')
        self.assertEqual(w['machine', 0], .8)
        self.assertEqual(other['machine', 0], .2)
        w, _ = relation_weights(flipped, 100, report, 'disagreement')
        self.assertEqual(w['machine', 0], 1)
        self.assertFalse(relation_weights(ref, 90, report, 'disagreement')[0])

    def test_selector_skips_repeated_ranges_and_constraints_keep_reference(self):
        data = small_data()
        ref = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        report = {'samples': [{'code': ref.as_dict(), 'objective': evaluate(data, ref)}], 'near_relations': []}
        selector = FeedbackSelector(data, report, 'disagreement')
        seen, rng = set(), random.Random(23)
        for iteration in range(4):
            choice = selector(data, ref, 2, {}, seen, iteration, rng)
            self.assertIsNotNone(choice)
            a, b, _ = choice
            self.assertTrue(window_constraints(ref, a, b, 2).satisfies(ref))
        self.assertIsNone(selector(data, ref, 2, {}, seen, 4, rng))


if __name__ == '__main__':
    unittest.main()
