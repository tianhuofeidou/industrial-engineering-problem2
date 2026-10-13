"""四算法共用初始化、完整局部最优、终止规则和范围轮换测试。"""
import itertools
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from problem2.common.data import CaseData
from problem2.common.encoding import Chromosome, evaluate, decode
from problem2.common.validation import validate_exact
from problem2.experiments.genetic import Evaluator, SearchResult
from problem2.experiments.four_methods import ComparisonConfig, initialize, run_method, run_annealing, tabu_allowed
from problem2.common.local_search import all_neighbors, descend, changed_attributes, random_neighbor
from problem2.tests.test_exact_case1 import small_data
from problem2.experiments.hybrid import refine_until_stable


class ComparisonTests(unittest.TestCase):
    def test_complete_local_optimum_from_all_small_codes(self):
        data, evaluator = small_data(), Evaluator(small_data())
        for a in itertools.permutations(range(3)):
            for b in itertools.permutations(range(3)):
                for machines in itertools.product(range(2), repeat=3):
                    initial = Chromosome(a, b, machines)
                    best = descend(initial, evaluator)
                    score = evaluate(data, best)
                    self.assertLessEqual(score, evaluate(data, initial))
                    self.assertTrue(all(evaluate(data, c) >= score for c in all_neighbors(best)))
                    validate_exact(data, decode(data, best))

    def test_neighborhoods_and_random_sampling_keep_codes(self):
        code = Chromosome(tuple(range(7)), tuple(reversed(range(7))), (0,)*7)
        candidates = list(all_neighbors(code))
        self.assertEqual(len(candidates), 133)
        self.assertTrue(all(c != code for c in candidates))
        rng = random.Random(17)
        for _ in range(500):
            candidate = random_neighbor(code, rng)
            candidate.check(7)
            self.assertIn(candidate, candidates)

    def test_tabu_undo_and_aspiration(self):
        initial = Chromosome((0, 1, 2), (2, 1, 0), (0, 0, 1))
        for candidate in all_neighbors(initial):
            request, undo = changed_attributes(initial, candidate)
            reverse_request, reverse_undo = changed_attributes(candidate, initial)
            self.assertEqual(set(undo), set(reverse_request))
            self.assertEqual(set(request), set(reverse_undo))
            tabu = {key: 8 for key in undo}
            self.assertFalse(tabu_allowed(reverse_request, tabu, 1, 101, 100))
            self.assertTrue(tabu_allowed(reverse_request, tabu, 1, 99, 100))
            self.assertTrue(tabu_allowed(reverse_request, tabu, 8, 101, 100))

    def test_shared_start_repeatability_and_stop(self):
        cfg = ComparisonConfig(constructions=2, vns_failures=2, tabu_stall=5,
                               sa_moves=3, sa_cooling=0.5, sa_ratio=0.125,
                               generations=12, population=6, archive_size=4)
        initial, info = initialize(small_data(), 11, cfg)
        self.assertTrue(all(evaluate(small_data(), c) >= info['local_best'] for c in all_neighbors(initial)))
        for method in ('vns', 'tabu', 'annealing', 'genetic'):
            first = run_method(method, small_data(), initial, 11, cfg)
            second = run_method(method, small_data(), initial, 11, cfg)
            self.assertEqual((first.search.best, first.search.best_cost, first.termination),
                             (second.search.best, second.search.best_cost, second.termination))
            self.assertLessEqual(first.search.best_cost, info['local_best'])
            validate_exact(small_data(), decode(small_data(), first.search.best))
            self.assertIn(first.search.best, first.search.archive)
            if method == 'genetic':
                self.assertEqual(first.search.generations, 12)
            elif method == 'tabu':
                self.assertEqual(first.termination['stall'], 5)
            elif method == 'annealing':
                self.assertEqual(first.termination['levels'], 4)
                self.assertEqual(first.termination['iterations'], 12)

    def test_rotation_covers_all_combinations_before_stopping(self):
        data = CaseData(1, tuple(f'J{i+1}' for i in range(7)), ((1,)*10,)*7, ((0,)*7,)*7)
        code = Chromosome(tuple(range(7)), tuple(range(7)), (0,)*7)
        search = SearchResult(code, evaluate(data, code), [code], 0, 0, 0, 0, 0, [], [])
        calls = []

        def fake_refine(data, reference, folder, **kwargs):
            self.assertIsNone(kwargs['seconds'])
            calls.append(tuple(kwargs['free_jobs']))
            result = decode(data, reference.best)
            result['proof'] = {'optimal': True, 'solution_source': 'solver'}
            return result

        with tempfile.TemporaryDirectory(prefix='problem2-rotation-test-') as directory:
            output = Path(directory)/'new'
            with patch('problem2.experiments.hybrid.refine', side_effect=fake_refine):
                final = refine_until_stable(data, search, output)
            self.assertEqual(calls, list(itertools.combinations(range(7), 3)))
            self.assertEqual(final['rotation']['passes'], 1)
            self.assertTrue(json.loads((output/'rotation.json').read_text(encoding='utf-8'))['complete'])
            self.assertFalse(final['rotation']['original_optimality_proven_by_this_run'])

    def test_invalid_parameters(self):
        for cfg in (ComparisonConfig(generations=0), ComparisonConfig(tabu_stall=0),
                    ComparisonConfig(sa_cooling=1), ComparisonConfig(sa_ratio=0)):
            with self.assertRaises(ValueError):
                cfg.check()

    def test_high_temperature_trace_and_deadline(self):
        import time
        from dataclasses import replace
        data = small_data()
        code = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
        cfg = ComparisonConfig(sa_moves=5, sa_cooling=0.5, sa_ratio=0.125)
        ordinary = run_annealing(data, code, 11, cfg)
        events = []
        hot = run_annealing(data, code, 11, replace(cfg, sa_temperature_multiplier=2),
                            on_event=lambda kind, code, row: events.append((kind, row)))
        self.assertEqual(hot.termination['initial_temperature'], 2*ordinary.termination['initial_temperature'])
        self.assertEqual(hot.termination['calibrated_temperature'], ordinary.termination['calibrated_temperature'])
        self.assertGreater(hot.termination['levels'], ordinary.termination['levels'])
        self.assertEqual(len([e for e in events if e[0] == 'temperature_level']), hot.termination['levels'])
        stopped = run_annealing(data, code, 11, cfg, deadline=time.perf_counter()-1)
        self.assertEqual(stopped.termination['reason'], 'time_budget')
        self.assertEqual(stopped.termination['iterations'], 0)
        validate_exact(data, decode(data, stopped.search.best))
        for multiplier in (0, float('inf')):
            with self.assertRaises(ValueError):
                replace(cfg, sa_temperature_multiplier=multiplier).check()

    def test_rotation_rechecks_after_improvement(self):
        processing = ((1, 1, 1, 1, 1, 10, 1, 1, 1, 1),)*7
        data = CaseData(1, tuple(f'J{i+1}' for i in range(7)), processing, ((0,)*7,)*7)
        code = Chromosome(tuple(range(7)), tuple(range(7)), (1,)*7)
        better = Chromosome(code.a, code.b, (0, 1, 1, 1, 1, 1, 1))
        self.assertLess(evaluate(data, better), evaluate(data, code))
        search = SearchResult(code, evaluate(data, code), [code], 0, 0, 0, 0, 0, [], [])
        references = []

        def fake_refine(data, reference, folder, **kwargs):
            references.append(reference.best)
            result = decode(data, better if len(references) == 1 else reference.best)
            result['proof'] = {'optimal': True, 'solution_source': 'solver'}
            return result

        with tempfile.TemporaryDirectory(prefix='problem2-rotation-improve-') as directory:
            with patch('problem2.experiments.hybrid.refine', side_effect=fake_refine):
                final = refine_until_stable(data, search, Path(directory)/'new')
            self.assertEqual(final['rotation']['passes'], 2)
            self.assertEqual(len(references), 70)
            self.assertTrue(all(reference == better for reference in references[1:]))
            self.assertEqual(final['objective'], evaluate(data, better))


if __name__ == '__main__':
    unittest.main()
