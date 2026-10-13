"""试探候选完整性、追加选择、受限会话和小实例穷举对照。"""
import itertools
from pathlib import Path
import random
import sys
import tempfile
import time
import unittest
from problem2.common.encoding import Chromosome, BatchEvaluator, evaluate
from problem2.common.restricted_session import RestrictedSession
from problem2.common.validation import validate_exact
from problem2.experiments.stage1_adaptive_time import coordinate, extend_index, probe
from problem2.stage2.joint_search import free_job_constraints
from problem2.tests.test_exact_case1 import small_data


class AdaptiveTests(unittest.TestCase):
    def test_coordinate_maintains_other_job_order_and_machine(self):
        ref=Chromosome((0,1,2,3),(3,2,1,0),(0,1,0,1))
        restriction=free_job_constraints(ref,(1,))
        for field in ('a','b','machines'):
            codes=list(coordinate(ref,1,field))
            self.assertEqual(len(codes),2 if field=='machines' else 4)
            for code in codes:
                code.check(4)
                self.assertTrue(restriction.satisfies(code))

    def test_probe_scores_only_complete_feasible_codes(self):
        data=small_data()
        ref=Chromosome((0,1,2),(0,1,2),(0,0,0))
        restriction=free_job_constraints(ref,(0,1))
        class CheckedScorer:
            count=0
            def evaluate(self,codes):
                for code in codes:
                    code.check(data.n)
                    assert restriction.satisfies(code)
                    validate_exact(data,__import__('problem2.common.encoding',fromlist=['decode']).decode(data,code))
                self.count+=len(codes)
                return [evaluate(data,c) for c in codes]
        scorer=CheckedScorer()
        best,details=probe(data,ref,(0,1),scorer)
        self.assertEqual(details['evaluations'],scorer.count)
        self.assertGreater(scorer.count,0)
        self.assertLessEqual(evaluate(data,best),evaluate(data,ref))
        batch,other=probe(data,ref,(0,1),BatchEvaluator(data))
        self.assertEqual(batch,best)
        self.assertEqual(other['rank_value'],details['rank_value'])

    def test_proved_range_is_never_extended_and_bound_does_not_rank(self):
        def entry(optimal,rank,near,bound):
            return {'result':{'proof':{'optimal':optimal,'bound':bound}},
                    'probe':{'rank_value':rank,'near_count':near}}
        rows=[entry(True,0,100,-100),entry(False,100,2,99),entry(False,101,10,-1000)]
        self.assertEqual(extend_index(rows,'adaptive_scored',random.Random(1)),1)
        for seed in range(10):
            self.assertIn(extend_index(rows,'adaptive_random',random.Random(seed)),(1,2))
        self.assertIsNone(extend_index([rows[0]],'adaptive_random',random.Random(1)))

    def test_probe_deadline_returns_valid_reference(self):
        data=small_data()
        ref=Chromosome((0,1,2),(0,1,2),(0,0,0))
        best,details=probe(data,ref,(0,1),deadline=time.perf_counter()-1)
        self.assertEqual(best,ref)
        self.assertFalse(details['complete'])
        self.assertEqual(details['evaluations'],0)


def integration():
    data=small_data()
    ref=Chromosome((0,1,2),(0,1,2),(0,0,0))
    restriction=free_job_constraints(ref,(0,1))
    expected=min(evaluate(data,c) for a in itertools.permutations(range(3))
        for b in itertools.permutations(range(3)) for m in itertools.product((0,1),repeat=3)
        if restriction.satisfies(c:=Chromosome(a,b,m)))
    with tempfile.TemporaryDirectory(prefix='adaptive-session-test-') as temp:
        session=RestrictedSession(data,ref,restriction,Path(temp)/'session',threads=2)
        try:
            first=session.run(.00001)
            if not first['proof']['optimal']:
                result=session.run(30)
                assert result['proof']['resumed_same_model']
            else:
                result=first
            assert result['proof']['optimal']
            assert abs(result['objective']-expected)<=1e-4
            assert all(p['model_sha256']==session.digest for p in session.phases)
            validate_exact(data,result)
            try:
                session.run(1)
            except ValueError:
                pass
            else:
                raise AssertionError('不允许重复求解已证明的模型')
            print({'phases':len(session.phases),'restricted_optimum':expected,'matches_exhaustive':True})
        finally:
            session.close()


if __name__=='__main__':
    if '--integration' in sys.argv: integration()
    else: unittest.main()
