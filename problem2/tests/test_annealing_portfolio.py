"""分组不改变退火，保留不同后段，不把机器归属随排列移动。"""
import unittest
from problem2.common.encoding import Chromosome, evaluate
from problem2.experiments.annealing_portfolio import GroupObserver, select_starts, distance
from problem2.stage1.annealing import run_annealing
from problem2.stage1.config import ComparisonConfig
from problem2.tests.test_exact_case1 import small_data


class PortfolioTests(unittest.TestCase):
    def test_best_front_per_group_and_distinct_back(self):
        a = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
        other_a = Chromosome((1, 0, 2), a.b, a.machines)
        other_b = Chromosome(a.a, (1, 0, 2), a.machines)
        tracker = GroupObserver(a, 100)
        tracker.sample(other_a, 99)
        tracker.sample(other_b, 101)
        self.assertEqual(len(tracker.rows()), 2)
        self.assertEqual(tracker.groups[(a.b, a.machines)], (99, other_a))
        selected = select_starts(other_a, 99, tracker.rows())
        self.assertEqual([c.b for _, c in selected], [a.b, other_b.b])
        self.assertEqual(distance(a, other_b), 1)

    def test_same_complete_search_and_acceptance(self):
        data = small_data()
        code = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        cfg = ComparisonConfig(sa_moves=30, sa_cooling=.5, sa_ratio=.001, sa_temperature_multiplier=2)
        plain = run_annealing(data, code, 23, cfg)
        tracker = GroupObserver(code, evaluate(data, code))
        tracked = run_annealing(data, code, 23, cfg, observer=tracker)
        self.assertEqual(plain.search.best, tracked.search.best)
        self.assertEqual(plain.termination, tracked.termination)
        fields = ('iteration', 'temperature', 'accepted', 'current', 'uphill_accepted')
        self.assertEqual([[r[k] for k in fields] for r in plain.search.generation_history],
                         [[r[k] for k in fields] for r in tracked.search.generation_history])
        for value, candidate in tracker.rows():
            self.assertEqual(evaluate(data, candidate), value)


if __name__ == '__main__':
    unittest.main()
