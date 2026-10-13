"""用可手算边界、损坏记录和小实例穷举验证模型规则。"""
import itertools
import random
import time
import unittest
from dataclasses import replace
from problem2.common.data import CaseData, m62_duration
from problem2.experiments.schedule import Evaluator, Solution
from problem2.experiments.search import SearchConfig, local_search, neighbors, reconstruct, search
from problem2.experiments.validate import validate_schedule


def tiny_data():
    return CaseData(0, ("J1", "J2", "J3"),
                    ((2, 3, 2, 4, 1, 8, 3, 2, 4, 1),
                     (4, 1, 3, 2, 5, 4, 2, 5, 1, 3),
                     (1, 5, 1, 3, 2, 6, 4, 1, 3, 2)),
                    ((999, 7, 2), (1, 999, 4), (6, 3, 999)))


class SchedulingTests(unittest.TestCase):
    def test_setup_waits_for_arrival(self):
        data = CaseData(0, ("J1", "J2"), ((1,)*10, (1, 1, 1, 1, 100, 5, 1, 1, 1, 1)),
                        ((999, 7), (2, 999)))
        schedule = Evaluator(data).schedule(Solution((0, 1), (0, 1), (), (0, 1)))
        op = next(o for o in schedule.operations if o.station == 6 and o.job == 1)
        self.assertEqual((op.arrival, op.setup_start, op.start), (140, 140, 147))
        validate_schedule(data, schedule)
        damaged = replace(op, setup_start=133, setup_end=140, start=140, end=145)
        with self.assertRaises(ValueError):
            validate_schedule(data, replace(schedule, operations=tuple(damaged if o == op else o for o in schedule.operations)))

    def test_queue_first_job_and_slow_machine(self):
        data = tiny_data()
        s = Evaluator(data).schedule(Solution((0, 1, 2), (0, 2), (1,), (0, 1, 2)))
        op = next(o for o in s.operations if o.machine == "6-2")
        self.assertIsNone(op.predecessor)
        self.assertEqual(op.setup_start, op.setup_end)
        self.assertEqual(op.processing, 5)
        self.assertEqual(m62_duration(9), 11)
        validate_schedule(data, s)

    def test_ties_can_change_objective(self):
        data = CaseData(0, ("J1", "J2"),
                        ((1, 1, 1, 1, 1, 7, 1, 100, 1, 1),
                         (1, 1, 1, 1, 1, 5, 100, 1, 1, 1)), ((999, 0), (0, 999)))
        evaluator = Evaluator(data)
        a = Solution((0, 1), (0,), (1,), (0, 1))
        b = replace(a, tie_priority=(1, 0))
        self.assertEqual(evaluator.cost(a), 116)
        self.assertEqual(evaluator.cost(b), 215)
        improved = local_search(b, evaluator, random.Random(3), SearchConfig(), time.perf_counter()+2)
        self.assertLess(evaluator.cost(improved), evaluator.cost(b))
        for solution in (a, b, improved):
            validate_schedule(data, evaluator.schedule(solution))

    def test_small_exhaustive_and_cache(self):
        data = tiny_data()
        evaluator = Evaluator(data)
        optimum = float("inf")
        count = 0
        for a in itertools.permutations(range(3)):
            for queues in itertools.permutations(range(3)):
                for split in range(4):
                    for tie in itertools.permutations(range(3)):
                        solution = Solution(a, queues[:split], queues[split:], tie)
                        schedule = evaluator.schedule(solution)
                        validate_schedule(data, schedule)
                        self.assertEqual(evaluator.cost(solution), schedule.makespan)
                        optimum = min(optimum, schedule.makespan)
                        count += 1
        self.assertEqual(count, 864)
        result = search(Evaluator(data), 11, SearchConfig(seconds=0.4))
        self.assertEqual(result.best_cost, optimum)
        print(f"小实例：穷举{count}个候选，递推规则下最优值={optimum}；搜索结果一致。")

    def test_search_operators_preserve_jobs(self):
        data = tiny_data()
        evaluator = Evaluator(data)
        rng = random.Random(4)
        solution = Solution((0, 1, 2), (0, 1), (2,), (0, 1, 2))
        for kind in ("front_insert", "front_swap", "queue_insert", "queue_swap", "tie_swap"):
            for candidate in neighbors(solution, kind, evaluator, rng, 100):
                validate_schedule(data, evaluator.schedule(candidate))
        for _ in range(30):
            solution = reconstruct(solution, evaluator, rng, SearchConfig(), time.perf_counter()+2)
            validate_schedule(data, evaluator.schedule(solution))

    def test_missing_operation_is_rejected(self):
        data = tiny_data()
        s = Evaluator(data).schedule(Solution((0, 1, 2), (0,), (1, 2), (0, 1, 2)))
        with self.assertRaises(ValueError):
            validate_schedule(data, replace(s, operations=s.operations[:-1]))


if __name__ == "__main__":
    unittest.main()
