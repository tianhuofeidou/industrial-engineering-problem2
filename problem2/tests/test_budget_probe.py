"""新种子的候选范围抽样、完整评分及试探后精确求解的范围一致性。"""
import itertools
from pathlib import Path
import random
import sys
import tempfile
import unittest
from problem2.common.encoding import Chromosome,BatchEvaluator,evaluate,code_from_result
from problem2.common.solver_utils import optimize_once
from problem2.common.validation import validate_exact
from problem2.experiments.stage1_budget_probe import pair_pool,choose_exact
from problem2.experiments.stage1_adaptive_time import probe
from problem2.stage2.joint_search import free_job_constraints
from problem2.tests.test_exact_case1 import small_data


class BudgetProbeTests(unittest.TestCase):
    def test_pair_pool_no_repeat_for_same_reference(self):
        ref=Chromosome(tuple(range(5)),tuple(range(5)),(0,)*5)
        seen=set()
        rng=random.Random(11)
        first=pair_pool(5,ref,seen,rng,6)
        second=pair_pool(5,ref,seen,rng,6)
        self.assertEqual(len(first),6)
        self.assertEqual(len(second),4)
        self.assertFalse(set(first)&set(second))
        self.assertEqual(pair_pool(5,ref,seen,rng,6),[])
        changed=Chromosome(ref.a,ref.b,(1,0,0,0,0))
        self.assertEqual(len(pair_pool(5,changed,seen,rng,6)),6)

    def test_ranking_uses_full_feasible_score_not_bound(self):
        rows=[{'rank_value':101,'near_count':100,'bound':0},
              {'rank_value':100,'near_count':1,'bound':999},
              {'rank_value':100,'near_count':2,'bound':-100}]
        self.assertEqual(choose_exact(rows,random.Random(1)),2)
        self.assertIsNone(choose_exact([],random.Random(1)))

    def test_wider_probe_is_valid_and_deterministic(self):
        data=small_data()
        ref=Chromosome((0,1,2),(0,1,2),(0,0,0))
        a,ra=probe(data,ref,(0,1),BatchEvaluator(data),width=32)
        b,rb=probe(data,ref,(0,1),BatchEvaluator(data),width=32)
        self.assertEqual(a,b)
        self.assertEqual(ra['evaluations'],rb['evaluations'])
        self.assertTrue(ra['complete'])
        self.assertTrue(free_job_constraints(ref,(0,1)).satisfies(a))
        self.assertLessEqual(evaluate(data,a),evaluate(data,ref))

    def test_new_reference_rebuilds_fixed_conditions(self):
        ref=Chromosome((0,1,2,3),(0,1,2,3),(0,0,1,1))
        moved=Chromosome((3,0,1,2),(0,3,1,2),(0,0,1,0))
        old=free_job_constraints(ref,(0,1))
        new=free_job_constraints(moved,(0,1))
        self.assertFalse(old.satisfies(moved))
        self.assertTrue(new.satisfies(moved))
        self.assertEqual(new.decisions()[0][3],0)


def integration():
    data=small_data()
    ref=Chromosome((0,1,2),(0,1,2),(0,0,0))
    candidate,row=probe(data,ref,(0,1),BatchEvaluator(data),width=32)
    # 试探已改变编码，精确限制从该已验证编码重新生成，保留机器和相对顺序。
    restriction=free_job_constraints(candidate,(0,1))
    expected=min(evaluate(data,c) for a in itertools.permutations(range(3))
        for b in itertools.permutations(range(3)) for m in itertools.product((0,1),repeat=3)
        if restriction.satisfies(c:=Chromosome(a,b,m)))
    with tempfile.TemporaryDirectory(prefix='wide-probe-exact-test-') as temp:
        result=optimize_once(data,candidate,restriction,Path(temp)/'round',30,2,
            strengthen=True,compact=True)
        assert result['proof']['optimal']
        assert abs(result['objective']-expected)<=1e-4
        assert restriction.satisfies(code_from_result(result,data.n))
        validate_exact(data,result)
        print({'probe':row['best_objective'],'restricted_exact':result['objective'],
               'matches_exhaustive':True,'reference_is_probe_result':True})


if __name__=='__main__':
    if '--integration' in sys.argv: integration()
    else: unittest.main()
