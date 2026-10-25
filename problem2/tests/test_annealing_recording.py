"""过程回调不得改变退火随机轨迹、温度终止或最好解。"""
import unittest
from problem2.common.encoding import Chromosome
from problem2.stage1.annealing import run_annealing
from problem2.stage1.config import ComparisonConfig
from problem2.tests.test_exact_case1 import small_data


class Observations:
    def __init__(self):
        self.trials = 0
        self.finished = None
    def start(self, *args):
        self.started = True
    def calibration(self, *args):
        self.calibrated = True
    def trial_result(self, *args):
        self.trials += 1
    def finish(self, outcome):
        self.finished = outcome


class RecordingCompatibilityTests(unittest.TestCase):
    def test_recording_preserves_complete_trajectory(self):
        data = small_data()
        initial = Chromosome((2, 0, 1), (1, 2, 0), (0, 1, 0))
        cfg = ComparisonConfig(sa_moves=30, sa_cooling=.5, sa_ratio=.01, sa_temperature_multiplier=.5)
        for seed in (11, 23, 53):
            with self.subTest(seed=seed):
                plain = run_annealing(data, initial, seed, cfg)
                observer = Observations()
                recorded = run_annealing(data, initial, seed, cfg, process=observer)
                self.assertEqual(plain.termination, recorded.termination)
                for key in ('best', 'best_cost', 'archive', 'evaluations', 'cache_hits', 'generations'):
                    self.assertEqual(getattr(plain.search, key), getattr(recorded.search, key))
                def without_time(rows):
                    return [{k:v for k,v in row.items() if k != 'seconds'} for row in rows]
                self.assertEqual(without_time(plain.search.generation_history), without_time(recorded.search.generation_history))
                self.assertEqual(observer.trials, plain.termination['iterations'])
                self.assertIs(observer.finished, recorded)


if __name__ == '__main__':
    unittest.main()
