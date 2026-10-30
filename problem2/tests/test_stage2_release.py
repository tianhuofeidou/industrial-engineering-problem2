"""公开二阶段调用条件、跳过候选与跨轮接受的回归检查；真实模型另跑集成门禁。"""
import json
from pathlib import Path
import random
import tempfile
import time
import unittest
from unittest.mock import patch
from problem2.published.stage2_10335 import pipeline as p
from problem2.published.stage2_10335 import hybrid_round as h
from problem2.tests.test_exact_case1 import small_data
from problem2.tests.test_stable import codes
from problem2.stage2.iterated_search import acceptance

class ReleaseTests(unittest.TestCase):
    def test_quality_gate_includes_ties(self):
        self.assertTrue(h.should_refine('gated',99,100))
        self.assertTrue(h.should_refine('gated',100,100))
        self.assertFalse(h.should_refine('gated',101,100))
        self.assertTrue(h.should_refine('always',101,100))
        with self.assertRaises(ValueError):h.should_refine('bad',100,100)

    def test_skip_keeps_worse_candidate_and_global_best(self):
        data=small_data();population=list(codes(3))
        best=min(population,key=lambda c:p.evaluate(data,c));worst=max(population,key=lambda c:p.evaluate(data,c))
        req=dict(round=1,seed=11,size=3,heuristic_seconds=2,repair_seconds=1,widths=[2,2,2],
            solver_seconds=[1,1,1],threads=6,refinement_policy='gated',global_best_before=p.evaluate(data,best))
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(h,'perturb_selected',return_value=worst),patch.object(h,'repair',return_value=(worst,{})),patch.object(h,'full_descent',return_value=(worst,{})),patch.object(h,'optimize_once',side_effect=AssertionError('Skipped GP executed')):
                r=h.execute(data,best,req,Path(temp)/'round',time.perf_counter()+10,None)
            self.assertEqual(r['candidate_code'],worst.as_dict())
            self.assertEqual(r['best_code'],best.as_dict())
            self.assertFalse(any(x['stage']=='gurobi' for x in r['phases']))

    def test_skip_does_not_replace_outer_acceptance(self):
        self.assertTrue(acceptance(100,101,100,100,.03,random.Random(2))['accepted'])
        self.assertFalse(acceptance(100,104,100,100,.03,random.Random(2))['accepted'])

    def test_availability_uses_observed_time(self):
        self.assertIsNone(p.availability([dict(elapsed_seconds=1801,objective=1)],[1800])['1800'])

    def test_public_data_pairs_and_scope(self):
        folder=Path(h.__file__).resolve().parent
        rows=json.loads((folder/'runs.json').read_text(encoding='utf-8'))
        self.assertEqual(len(rows),6)
        for start in (10445,10492,10520):
            pair=[x for x in rows if x['start']==start]
            self.assertEqual({x['method'] for x in pair},{'always','gated'})
            self.assertEqual(pair[0]['initial_code_sha256'],pair[1]['initial_code_sha256'])
            self.assertEqual(pair[0]['seed'],pair[1]['seed'])
        self.assertTrue(all(x['scope']=='restricted' for x in rows))
        self.assertEqual(min(x['objective'] for x in rows),10335)

if __name__=='__main__':unittest.main()
