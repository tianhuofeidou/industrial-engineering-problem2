"""候选集合统计、原题边界及小实例全编码穷举对照。"""
import importlib.util
import itertools
import os
import sys
import tempfile
import unittest
from pathlib import Path

from problem2.common.candidate_arcs import CandidateArcs, QUEUES, generate_candidates
from problem2.common.encoding import Chromosome, decode, evaluate, code_from_result
from problem2.common.relation_tracking import queues
from problem2.common.solver import build_model
from problem2.common.solver_utils import optimize_once
from problem2.common.validation import validate_exact
from problem2.tests.test_exact_case1 import small_data
from problem2.tests.test_stable import codes


def report_for(data, samples):
    return {'front_samples': [{'code': c.as_dict(), 'objective': evaluate(data, c)} for c in samples],
            'other_samples': []}


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.data = small_data()
        self.all_codes = list(codes(3))
        self.reference = min(self.all_codes, key=lambda c: evaluate(self.data, c))

    def test_frequency_deduplicates_queue_orders_not_complete_codes(self):
        report = report_for(self.data, self.all_codes)
        chosen, evidence = generate_candidates(self.data, self.reference, report, 1, 10)
        duplicate = {'front_samples': report['front_samples'] * 5, 'other_samples': report['front_samples']}
        repeated, second = generate_candidates(self.data, self.reference, duplicate, 1, 10)
        self.assertEqual(chosen.edges, repeated.edges)
        self.assertEqual(evidence['queue_statistics'], second['queue_statistics'])
        for q in ('A', 'B'):
            row = evidence['queue_statistics'][q]
            self.assertEqual(row['distinct_queue_orders'], 6)
            self.assertTrue(all(r['count'] == 2 for r in row['frequencies']))
        self.assertTrue(chosen.satisfies(self.reference))

    def test_quality_filter_and_invalid_record(self):
        bad = max(self.all_codes, key=lambda c: evaluate(self.data, c))
        report = report_for(self.data, [self.reference, bad])
        _, evidence = generate_candidates(self.data, self.reference, report, 1, 1)
        self.assertEqual(evidence['distinct_eligible_codes'], 1)
        report['front_samples'][0]['objective'] += 1
        with self.assertRaisesRegex(ValueError, '评分'):
            generate_candidates(self.data, self.reference, report)

    def test_all_observed_arcs_allow_full_small_encoding_space(self):
        chosen, _ = generate_candidates(self.data, self.reference,
                                        report_for(self.data, self.all_codes), 2, 10)
        self.assertTrue(all(chosen.satisfies(code) for code in self.all_codes))
        self.assertTrue(all(len(chosen.edges[q]) == 6 for q in QUEUES))

    def test_only_reference_and_empty_parallel_queue(self):
        ref = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
        chosen, _ = generate_candidates(self.data, ref, report_for(self.data, [ref]), 1)
        self.assertTrue(chosen.satisfies(ref))
        self.assertEqual(chosen.edges['6-2'], frozenset())
        self.assertTrue(chosen.permits('6-2', -1, 3))
        for q in QUEUES:
            for job in range(3):
                self.assertTrue(chosen.permits(q, -1, job))
                self.assertTrue(chosen.permits(q, job, 3))
        self.assertFalse(chosen.satisfies(Chromosome((1, 0, 2), ref.b, ref.machines)))

    def test_reference_mismatch_and_invalid_candidates_fail(self):
        worse = max(self.all_codes, key=lambda c: evaluate(self.data, c))
        with self.assertRaisesRegex(ValueError, '最好编码'):
            generate_candidates(self.data, worse, report_for(self.data, [self.reference]))
        invalid = CandidateArcs(3, {q: frozenset({(0, 0)}) for q in QUEUES})
        with self.assertRaises(ValueError):
            invalid.check(3)
        for k in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                generate_candidates(self.data, self.reference, report_for(self.data, [self.reference]), k)


def integration(output=None, original_solver=None):
    data = small_data()
    all_codes = list(codes(3))
    reference = Chromosome((2, 0, 1), (1, 2, 0), (0, 1, 0))
    full_edges = frozenset(itertools.permutations(range(3), 2))
    full = CandidateArcs(3, {q: full_edges for q in QUEUES})
    limited, _ = generate_candidates(data, reference, report_for(data, [reference]), 1)
    empty_ref = Chromosome((0, 1, 2), (0, 1, 2), (0, 0, 0))
    empty, _ = generate_candidates(data, empty_ref, report_for(data, [empty_ref]), 1)
    cases = [('default_full', reference, None), ('all_candidates', reference, full),
             ('reference_candidates', reference, limited), ('empty_parallel_queue', empty_ref, empty)]
    records = []
    import gurobipy as gp
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag', 0)
        env.start()
        def solve(root):
            for name, ref, candidate in cases:
                allowed = [c for c in all_codes if candidate is None or candidate.satisfies(c)]
                expected = min(evaluate(data, c) for c in allowed)
                result = optimize_once(data, ref, None, root / name, 20, 2,
                                       strengthen=True, compact=False, solver_env=env,
                                       candidate_arcs=candidate)
                proof = result['proof']
                assert proof['status'] == 2 and proof['optimal']
                assert abs(proof['bound'] - expected) <= 1e-4
                assert abs(result['objective'] - expected) <= 1e-4
                assert proof['scope'] == ('full' if candidate is None else 'restricted')
                assert proof['original_optimality_proven_by_this_run'] == (candidate is None)
                validate_exact(data, result)
                if candidate is not None:
                    assert candidate.satisfies(code_from_result(result, data.n))
                records.append({'case': name, 'encodings_enumerated': len(all_codes),
                                'allowed_encodings': len(allowed), 'optimum': expected,
                                'scope': proof['scope'], 'binary_variables': proof['reduction']['binary_variables']})
            if original_solver is not None:
                spec = importlib.util.spec_from_file_location('original_solver_for_candidate_check', original_solver)
                old = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(old)
                folder = root / 'original_default'
                folder.mkdir()
                cwd = Path.cwd()
                model = None
                try:
                    os.chdir(folder)
                    _, model = old.build_model(data, decode(data, reference), folder, 20, 2,
                                               strengthen=True, compact=False, solver_env=env)
                    assert (folder / 'model.mps').read_bytes() == (root / 'default_full/model.mps').read_bytes()
                    records.append({'case': 'default_model_matches_original', 'mps_bytes_identical': True})
                finally:
                    if model is not None:
                        model.dispose()
                    os.chdir(cwd)
        if output is None:
            with tempfile.TemporaryDirectory(prefix='problem2-candidates-') as temp:
                solve(Path(temp))
        else:
            Path(output).mkdir(parents=True, exist_ok=False)
            solve(Path(output).resolve())
    return records


if __name__ == '__main__':
    if '--integration' in sys.argv:
        import argparse
        import json
        parser = argparse.ArgumentParser()
        parser.add_argument('--integration', action='store_true')
        parser.add_argument('--output', type=Path)
        parser.add_argument('--original-solver', type=Path)
        args = parser.parse_args()
        rows = integration(args.output, args.original_solver)
        if args.output is not None:
            (args.output / 'verification.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(rows, ensure_ascii=False))
    else:
        unittest.main()
