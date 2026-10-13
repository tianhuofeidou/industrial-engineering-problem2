"""新编码、遗传操作和受限模型的测试；集成测试用穷举核对受限最优值。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
import itertools
import os
import random
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from problem2.common.data import load_case
from problem2.common.encoding import Chromosome, decode, evaluate, code_from_result
from problem2.common.solver import build_model, extract, export
from problem2.common.validation import validate_exact
from problem2.experiments.genetic import (SearchConfig, run_genetic, run_greedy, crossover, mutate,
                      diverse_archive, random_code, balanced_code)
from problem2.common.restrictions import make_restriction, satisfies, select_free_jobs
from problem2.tests.test_exact_case1 import small_data
from problem2.experiments.hybrid import refine


def all_codes(n):
    return (Chromosome(a, b, machines) for a in itertools.permutations(range(n))
            for b in itertools.permutations(range(n))
            for machines in itertools.product(range(2), repeat=n))


class GeneticTests(unittest.TestCase):
    def test_score_detail_and_feasibility(self):
        data = small_data()
        for code in all_codes(data.n):
            detail = decode(data, code)
            self.assertEqual(evaluate(data, code), detail['objective'])
            self.assertTrue(validate_exact(data, detail)['valid'])

    def test_operators_keep_jobs_and_parent(self):
        rng = random.Random(111)
        first, second = random_code(7, rng), random_code(7, rng)
        saved = (first.as_dict(), second.as_dict())
        for _ in range(200):
            child = mutate(crossover(first, second, rng), rng, 1.0)
            child.check(7)
        self.assertEqual(saved, (first.as_dict(), second.as_dict()))

    def test_invalid_code(self):
        with self.assertRaises(ValueError):
            Chromosome((0, 0), (0, 1), (0, 1)).check(2)
        with self.assertRaises(ValueError):
            Chromosome((0, 1), (0, 1), (0, 2)).check(2)

    def test_fixed_relations_allow_insertion(self):
        reference = Chromosome((0, 1, 2), (2, 1, 0), (0, 0, 1))
        restriction = make_restriction(reference, [1])
        trial = Chromosome((1, 0, 2), (1, 2, 0), (0, 1, 1))
        self.assertTrue(satisfies(reference, restriction))
        self.assertTrue(satisfies(trial, restriction))
        self.assertFalse(satisfies(Chromosome((2, 1, 0), trial.b, trial.machines), restriction))

    def test_fixed_all_jobs(self):
        reference = next(all_codes(3))
        restriction = make_restriction(reference, [])
        allowed = [code for code in all_codes(3) if satisfies(code, restriction)]
        self.assertEqual(allowed, [reference])

    def test_archive_quality_and_diversity(self):
        pool = list(all_codes(3))[:20]
        values = {code: 100+i for i, code in enumerate(pool)}
        archive = diverse_archive(pool, values, 5)
        self.assertIn(pool[0], archive)
        self.assertEqual(len(archive), len(set(archive)))
        self.assertTrue(all(values[code] <= 105 for code in archive))

    def test_free_selection_keeps_reference(self):
        reference = next(all_codes(3))
        others = [Chromosome((1, 0, 2), reference.b, reference.machines)]
        free, scores = select_free_jobs(reference, others, 1)
        self.assertEqual(free, (0,))
        self.assertGreater(scores[0], scores[2])
        self.assertTrue(satisfies(reference, make_restriction(reference, free)))

    def test_fixed_generations_repeatable(self):
        config = SearchConfig(seconds=60, population=12, generations=8, local_candidates=12)
        one = run_genetic(small_data(), 23, config)
        two = run_genetic(small_data(), 23, config)
        self.assertEqual(one.generations, 8)
        self.assertEqual((one.best, one.best_cost, one.archive), (two.best, two.best_cost, two.archive))
        self.assertEqual(one.best_cost, evaluate(small_data(), one.best))

    def test_tiny_budget_returns_complete_code(self):
        config = SearchConfig(seconds=1e-7, population=6)
        for search in (run_genetic, run_greedy):
            result = search(small_data(), 11, config)
            result.best.check(3)
            self.assertTrue(validate_exact(small_data(), decode(small_data(), result.best))['valid'])

    def test_known_case1_code(self):
        data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 1)
        code = Chromosome((4, 2, 0, 3, 1, 5, 6), (4, 2, 0, 1, 3, 5, 6), (0, 1, 1, 0, 0, 1, 0))
        self.assertEqual(evaluate(data, code), 5031)
        validate_exact(data, decode(data, code))

    def test_case2_refinement_forbidden(self):
        data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
        with self.assertRaisesRegex(ValueError, 'Case 2只运行启发式'):
            refine(data, None, None)

    def test_case2_export_complete_svg(self):
        data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
        schedule = decode(data, balanced_code(data))
        self.assertEqual(len(schedule['operations']), 350)
        self.assertTrue(validate_exact(data, schedule)['valid'])
        with tempfile.TemporaryDirectory(prefix='problem2-export-test-') as temporary:
            folder = Path(temporary)
            export(folder, schedule)
            svg = ET.parse(folder/'gantt.svg').getroot()
            labels = ''.join(svg.itertext())
            self.assertIn('Case 2 /', labels)
            self.assertIn('J1-J35', labels)
            self.assertEqual(len(svg.findall('{http://www.w3.org/2000/svg}rect')), 701)


def integration():
    data = small_data()
    reference = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
    warm = decode(data, reference)
    original = Path.cwd()
    for free in ((), (1,)):
        restriction = make_restriction(reference, free)
        candidates = [code for code in all_codes(data.n) if satisfies(code, restriction)]
        optimum = min(evaluate(data, code) for code in candidates)
        with tempfile.TemporaryDirectory(prefix='problem2-restricted-test-') as temporary:
            try:
                os.chdir(temporary)
                env, model = build_model(data, warm, Path(temporary), 60, 2, free_jobs=free)
                try:
                    model.optimize()
                    assert model.Status == 2
                    result = extract(data, lambda name: model.getVarByName(name).X)
                    validate_exact(data, result)
                    assert satisfies(code_from_result(result, data.n), restriction)
                    assert abs(result['objective']-optimum) <= 1e-4
                    assert abs(model.ObjBound-optimum) <= 1e-4
                    print(f'free={free}, candidates={len(candidates)}, MILP=enumeration={optimum}')
                finally:
                    model.dispose()
                    env.dispose()
            finally:
                os.chdir(original)


if __name__ == '__main__':
    if '--integration' in sys.argv:
        integration()
    else:
        unittest.main()
