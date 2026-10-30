"""二阶段范围、切换、重试、限时与续跑正确性；不以改善目标值作为门禁。"""
from dataclasses import replace
import json
import os
from pathlib import Path
import random
import tempfile
import time
import unittest

from problem2.common.data import CaseData
from problem2.common.encoding import Chromosome, decode, evaluate
from problem2.stage1.neighborhoods import window_constraints
from problem2.stage2.joint_search import free_job_constraints
from problem2.stage2.neighborhood_search import Planner, SearchConfig, job_groups, run
from problem2.tests.test_exact_case1 import small_data
from problem2.tests.test_stable import codes


class NeighborhoodTests(unittest.TestCase):
    def setUp(self):
        self.data = small_data()
        self.code = Chromosome((0, 1, 2), (0, 1, 2), (0, 1, 0))
        self.config = SearchConfig(widths=(1, 2), group_sizes=(1, 2),
            groups_per_size=3, window_stall=1, free_batch=1, window_seconds=.1, free_seconds=.1)

    def solved(self, reference, optimal=True, candidate=None):
        result = decode(self.data, candidate or reference)
        result['proof'] = dict(scope='restricted', optimal=optimal,
                               original_optimality_proven_by_this_run=False)
        return result

    def fake(self, calls, optimal=True):
        def solve(data, reference, restriction, folder, seconds, threads, **kwargs):
            self.assertTrue(folder.is_absolute())
            self.assertTrue(restriction.satisfies(reference))
            calls.append((reference, restriction, seconds))
            return self.solved(reference, optimal)
        return solve

    def test_free_scope_equals_independent_filter_over_288_codes(self):
        for jobs in ((0,), (2,), (0, 2)):
            restriction = free_job_constraints(self.code, jobs)
            for c in codes(3):
                expected = all(tuple(j for j in q if j not in jobs) ==
                    tuple(j for j in ref if j not in jobs)
                    for q, ref in ((c.a, self.code.a), (c.b, self.code.b))) and all(
                    c.machines[j] == self.code.machines[j] for j in range(3) if j not in jobs)
                self.assertEqual(restriction.satisfies(c), expected)

    def test_free_scope_allows_remote_move_that_window_excludes(self):
        data = CaseData(0, tuple('J'+str(j) for j in range(5)), ((1,)*10,)*5,
                        tuple(tuple(0 for _ in range(5)) for _ in range(5)))
        ref = Chromosome(tuple(range(5)), tuple(range(5)), (0,)*5)
        candidate = Chromosome((4, 1, 2, 3, 0), ref.b, ref.machines)
        self.assertTrue(free_job_constraints(ref, (0, 4)).satisfies(candidate))
        self.assertFalse(window_constraints(ref, 0, 0, 2).satisfies(candidate))
        groups = job_groups(data, ref, 2, 8, 23)
        self.assertIn((0, 4), groups)
        self.assertEqual(groups, job_groups(data, ref, 2, 8, 23))
        self.assertEqual(len(groups), len(set(groups)))

    def test_switches_window_free_window_without_perturbation(self):
        state = Planner(self.data, self.code, self.config)
        kinds = []
        for _ in range(4):
            req = state.next_request(); kinds.append(req['kind'])
            state.begin(req); state.accept(req, self.solved(state.reference), 0)
        self.assertEqual(kinds, ['window', 'free', 'window', 'free'])

    def test_optimal_ranges_not_retried_and_timeout_retries_bounded(self):
        state = Planner(self.data, self.code, self.config)
        req = state.next_request(); state.begin(req)
        state.accept(req, self.solved(state.reference), 0)
        self.assertTrue(state.exhausted(req['key']))
        free = state.next_request(); state.begin(free)
        state.accept(free, self.solved(state.reference, False), 0)
        self.assertFalse(state.exhausted(free['key']))
        state.mode = 'free'
        retry = state.next_request()
        self.assertEqual(retry['key'], free['key'])
        self.assertEqual(retry['seconds'], 2*free['seconds'])
        state.begin(retry); state.accept(retry, self.solved(state.reference, False), 0)
        self.assertTrue(state.exhausted(free['key']))

    def test_improvement_restarts_windows_and_keeps_old_range_identity(self):
        state = Planner(self.data, self.code, self.config)
        state.mode = 'free'
        req = state.next_request(); restriction = state.restriction(req)
        possible = [c for c in codes(3) if restriction.satisfies(c)]
        best = min(possible, key=lambda c: evaluate(self.data, c))
        if evaluate(self.data, best) == evaluate(self.data, self.code):
            self.skipTest('This fixed scope has no improving candidate')
        state.begin(req); state.accept(req, self.solved(self.code, candidate=best), 0)
        self.assertEqual(state.mode, 'window')
        self.assertEqual(state.reference, best)
        self.assertNotEqual(state.next_request()['key'], req['key'])

    def test_equal_objective_does_not_change_reference(self):
        state = Planner(self.data, self.code, self.config)
        req = state.next_request(); state.begin(req)
        state.accept(req, self.solved(self.code), 0)
        self.assertEqual(state.reference, self.code)

    def test_checkpoint_preserves_rng_ledger_and_next_choice(self):
        state = Planner(self.data, self.code, self.config)
        req = state.next_request(); state.begin(req); state.accept(req, self.solved(self.code), 0)
        saved = json.loads(json.dumps(state.checkpoint(2, {})))
        restored = Planner.restore(self.data, self.config, saved)
        self.assertEqual(restored.next_request(), state.next_request())
        self.assertEqual(restored.prior_reported_seconds, 2)

    def test_interrupted_pending_attempt_and_corrupt_checkpoint(self):
        state = Planner(self.data, self.code, self.config)
        req = state.next_request(); state.begin(req)
        saved = json.loads(json.dumps(state.checkpoint(2, {})))
        restored = Planner.restore(self.data, self.config, saved)
        self.assertTrue(restored.interruption_cost_unknown)
        self.assertEqual(restored.ledger[req['key']]['attempts'], 1)
        saved['best_value'] += 1
        with self.assertRaises(ValueError): Planner.restore(self.data, self.config, saved)

    def test_expired_budget_exports_full_reference_without_call(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'expired'
            result = run(self.data, self.code, path, self.config, seconds=0,
                         solve=self.fake(calls), save_source=False)
            summary = json.loads((path/'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(result['objective'], evaluate(self.data, self.code))
        self.assertEqual(calls, [])
        self.assertEqual(summary['termination'], 'time_budget')
        self.assertEqual(len(result['operations']), 30)

    def test_resume_uses_new_output_and_retains_prior_records(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'one'
            run(self.data, self.code, path, self.config, seconds=5, max_rounds=2,
                solve=self.fake(calls), save_source=False)
            saved = json.loads((path/'checkpoint.json').read_text(encoding='utf-8'))
            two = Path(temp)/'two'
            run(self.data, self.code, two, self.config, seconds=5, max_rounds=2, saved=saved,
                solve=self.fake(calls), save_source=False)
            summary = json.loads((two/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['new_solver_calls'], 2)
            self.assertEqual(summary['total_recorded_rounds'], 4)
            self.assertEqual(summary['perturbations'], 0)
            with self.assertRaises(FileExistsError):
                run(self.data, self.code, path, self.config, solve=self.fake(calls), save_source=False)

    def test_relative_output_is_absolute_before_solver_changes_directory(self):
        original = Path.cwd()
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                run(self.data, self.code, Path('relative'), self.config, seconds=5, max_rounds=1,
                    solve=self.fake(calls), save_source=False)
                self.assertTrue(Path('relative/final/result.json').exists())
            finally:
                os.chdir(original)
        self.assertEqual(len(calls), 1)

    def test_worse_or_outside_scope_candidate_rejected(self):
        state = Planner(self.data, self.code, self.config)
        req = state.next_request()
        restriction = state.restriction(req)
        worse = next(c for c in codes(3) if evaluate(self.data, c) > evaluate(self.data, self.code))
        outside = next(c for c in codes(3) if not restriction.satisfies(c)
                       and evaluate(self.data, c) <= evaluate(self.data, self.code))
        for candidate in (worse, outside):
            state.begin(req)
            with self.assertRaises(AssertionError):
                state.accept(req, self.solved(self.code, candidate=candidate), 0)
            self.assertEqual(state.reference, self.code)
            self.assertEqual(state.records, [])

    def test_solver_error_preserves_best_and_failure_checkpoint(self):
        best = min(codes(3), key=lambda c: evaluate(self.data, c))
        def fail(*args, **kwargs): raise RuntimeError('intentional solver error')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'failure'
            with self.assertRaises(RuntimeError):
                run(self.data, best, path, self.config, seconds=5, solve=fail, save_source=False)
            self.assertTrue((path/'checkpoint.json').exists())
            final = json.loads((path/'final/result.json').read_text(encoding='utf-8'))
            self.assertEqual(final['objective'], evaluate(self.data, best))
            self.assertFalse(json.loads((path/'summary.json').read_text(encoding='utf-8'))['complete'])

    def test_invalid_settings_and_changed_resume_parameters_rejected(self):
        for cfg in (replace(self.config, window_seconds=float('nan')),
                    replace(self.config, group_sizes=(7,)), replace(self.config, attempts_per_range=0)):
            with self.assertRaises(ValueError): cfg.check(3)
        state = Planner(self.data, self.code, self.config)
        with self.assertRaises(ValueError):
            Planner.restore(self.data, replace(self.config, seed=99), state.checkpoint(0, {}))


if __name__ == '__main__': unittest.main()
