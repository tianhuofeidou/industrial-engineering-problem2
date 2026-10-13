"""联合成组枚举的准确范围、一般模型评分及停止条件。"""
import itertools
import json
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path
from problem2.common.data import CaseData
from problem2.common.encoding import BatchEvaluator, Chromosome, decode, evaluate
from problem2.common.validation import validate_exact
from problem2.stage2.joint_search import enumerate_block, choose_groups, free_job_constraints
from problem2.stage2.main import run
from problem2.tests.test_exact_case1 import small_data
from problem2.tests.test_stable import codes


class JointTests(unittest.TestCase):
    def setUp(self):
        self.data = small_data()
        self.reference = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))

    def allowed(self, code, jobs):
        for sequence, reference in ((code.a, self.reference.a), (code.b, self.reference.b)):
            positions = sorted(sequence.index(j) for j in jobs)
            if positions[-1]-positions[0] != len(jobs)-1:
                return False
            if tuple(j for j in sequence if j not in jobs) != tuple(j for j in reference if j not in jobs):
                return False
        return all(code.machines[j] == self.reference.machines[j] for j in range(self.data.n) if j not in jobs)

    def test_all_two_and_three_job_scopes_equal_exhaustive_codes(self):
        for size in (2, 3):
            for jobs in itertools.combinations(range(3), size):
                allowed = [c for c in codes(3) if self.allowed(c, jobs)]
                best, info = enumerate_block(self.data, self.reference, jobs)
                self.assertTrue(info['complete'])
                self.assertEqual(info['evaluations'], len(allowed))
                self.assertEqual(info['after'], min(evaluate(self.data, c) for c in [self.reference]+allowed))
                self.assertEqual(evaluate(self.data, best), info['after'])
                validate_exact(self.data, decode(self.data, best))

    def test_prepared_batch_matches_all_fixed_front_small_codes_and_is_copied(self):
        scorer = BatchEvaluator(self.data)
        selected = [c for c in codes(3) if c.a == self.reference.a]
        b, m = [list(c.b) for c in selected], [list(c.machines) for c in selected]
        batch = scorer.prepare(b, m)
        b[0][0], m[0][0] = 999, 9
        self.assertEqual(batch.evaluate(self.reference.a).tolist(), [evaluate(self.data, c) for c in selected])
        with self.assertRaises(ValueError):
            scorer.prepare([[0, 0, 2]], [[0, 1, 0]])
        with self.assertRaises(TypeError):
            scorer.prepare([[0., 1., 2.]], [[0, 1, 0]])

    def test_four_jobs_match_all_9216_codes(self):
        p = self.data.processing+(self.data.processing[0],)
        setup = tuple(tuple(0 if i == j else (3*i+5*j) % 9 for j in range(4)) for i in range(4))
        data = CaseData(0, ('J1', 'J2', 'J3', 'J4'), p, setup)
        ref = Chromosome((0, 1, 2, 3), (0, 1, 2, 3), (0, 1, 0, 1))
        best, info = enumerate_block(data, ref, (0, 1, 2, 3))
        self.assertEqual(info['evaluations'], 9216)
        self.assertEqual(info['after'], min(evaluate(data, c) for c in codes(4)))
        validate_exact(data, decode(data, best))

    def test_expired_enumeration_retains_reference_without_proof(self):
        best, info = enumerate_block(self.data, self.reference, (0, 1), time.perf_counter()-1)
        self.assertEqual(best, self.reference)
        self.assertFalse(info['complete'])
        self.assertEqual(info['evaluations'], 0)
        self.assertFalse(info['original_optimality_proven_by_this_run'])

    def test_free_job_scope_preserves_reference_and_all_group_candidates(self):
        for jobs in itertools.combinations(range(3), 2):
            r = free_job_constraints(self.reference, jobs)
            self.assertTrue(r.satisfies(self.reference))
            for c in codes(3):
                if self.allowed(c, jobs):
                    self.assertTrue(r.satisfies(c))
        with self.assertRaises(ValueError):
            free_job_constraints(self.reference, (0, 1, 2))

    def test_selection_is_deterministic_and_no_duplicate_groups(self):
        selected = choose_groups(self.data, self.reference, 2, 100)
        self.assertEqual(selected, choose_groups(self.data, self.reference, 2, 100))
        self.assertEqual(len(selected), len(set(selected)))
        self.assertEqual(set(selected), set(itertools.combinations(range(3), 2)))

    def test_entry_without_solver_finishes_and_retains_best(self):
        with tempfile.TemporaryDirectory(prefix='joint-search-') as tmp:
            result = run(self.data, self.reference, Path(tmp), seconds=10, size=2, groups=3,
                         solver_rounds=0, solver_period=2)
            validate_exact(self.data, result)
            self.assertLessEqual(result['objective'], evaluate(self.data, self.reference))
            self.assertEqual(result['joint_search']['termination'], 'selected_ranges_exhausted')

    def test_solver_requires_new_search_and_does_not_discard_worse_reference(self):
        best = min(codes(3), key=lambda c: evaluate(self.data, c))
        worse = self.reference
        self.assertGreater(evaluate(self.data, worse), evaluate(self.data, best))
        references = []
        def scan(data, reference, jobs, deadline, scorer):
            references.append(reference)
            cost = evaluate(data, reference)
            return reference, {'before': cost, 'after': cost, 'jobs': list(jobs), 'complete': True}
        solved = decode(self.data, best)
        solved['proof'] = {'optimal': False, 'scope': 'restricted'}
        cache = Mock()
        cache.solve.return_value = solved
        cache.summary.return_value = {}
        with tempfile.TemporaryDirectory(prefix='joint-solver-') as tmp, \
                patch.dict('sys.modules', {'gurobipy': SimpleNamespace(Env=lambda **kw: Mock())}), \
                patch('problem2.stage2.main.ExactCache', return_value=cache), \
                patch('problem2.stage2.main.choose_groups', return_value=[(0,1), (0,2), (1,2)]), \
                patch('problem2.stage2.main.enumerate_block', side_effect=scan), \
                patch('problem2.stage2.main.descend', return_value=worse):
            result = run(self.data, best, Path(tmp), seconds=10, size=2, groups=3,
                         solver_rounds=4, solver_period=2, explore=True, perturbations=1)
            summary = json.loads((Path(tmp)/'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(references, [best, best, best, worse, worse, worse])
        phases = [row['phase'] for row in summary['records']]
        self.assertEqual(phases, ['enumeration','enumeration','gurobi','enumeration','gurobi','perturbation',
                                  'enumeration','enumeration','gurobi','enumeration'])
        self.assertEqual(result['objective'], evaluate(self.data, best))
        self.assertEqual(cache.solve.call_count, 3)


if __name__ == '__main__':
    unittest.main()
