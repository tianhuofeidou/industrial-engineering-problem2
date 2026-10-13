"""记录不改随机轨迹；没有试探不固定；解除关系后重新计算推论。"""
import itertools
import unittest
from problem2.common.encoding import Chromosome, evaluate
from problem2.common.annealing_records import model_counts
from problem2.common.stable_constraints import StableConstraints
from problem2.stage1.annealing import run_annealing
from problem2.stage1.config import ComparisonConfig
from problem2.stage1.neighborhoods import window_constraints
from problem2.tests.test_exact_case1 import small_data
from problem2.experiments.constraint_generation import (
    ConstraintObserver, evidence_for, release_job_orders, relax_adjacencies, generate)


class ConstraintGenerationTests(unittest.TestCase):
    def test_observer_preserves_every_temperature_level(self):
        data=small_data()
        code=Chromosome((0,1,2),(0,1,2),(0,0,0))
        config=ComparisonConfig(sa_moves=30,sa_cooling=.5,sa_ratio=.001,sa_temperature_multiplier=2)
        plain=run_annealing(data,code,23,config)
        observer=ConstraintObserver(code,evaluate(data,code))
        tracked=run_annealing(data,code,23,config,observer=observer)
        self.assertEqual(plain.search.best,tracked.search.best)
        self.assertEqual(plain.termination,tracked.termination)
        fields=('iteration','temperature','accepted','current','uphill_accepted')
        self.assertEqual([[r[k] for k in fields] for r in plain.search.generation_history],
                         [[r[k] for k in fields] for r in tracked.search.generation_history])
        self.assertGreater(observer.near_trials,0)

    def test_unexplored_and_equal_cost_opposite_are_not_fixed(self):
        code=Chromosome(tuple(range(6)),tuple(range(6)),(0,)*6)
        samples=[]
        for tail in itertools.permutations((2,3,4)):
            c=Chromosome((0,1)+tail+(5,),(0,1)+tail+(5,),code.machines)
            samples.append({'objective':100,'code':c.as_dict()})
        report={'front_samples':samples,'other_samples':samples,'statistics':[]}
        key=('adj','A',0,1)
        self.assertFalse(evidence_for(code,100,report)[key]['selected'])
        report['statistics']=[{'key':list(key),'value':1,'attempts':20,'small_delta':0,
                               'minimum_candidate_cost':101}]
        self.assertTrue(evidence_for(code,100,report)[key]['selected'])
        report['statistics'][0]['minimum_candidate_cost']=100
        self.assertFalse(evidence_for(code,100,report)[key]['selected'])

    def test_release_has_no_old_transitive_order(self):
        code=Chromosome(tuple(range(4)),tuple(range(4)),(0,)*4)
        base=window_constraints(code,0,0,1)
        self.assertIn(('A',0,3),base.decisions()[1])
        released=release_job_orders(base,'A',0)
        orders=released.decisions()[1]
        self.assertNotIn(('A',0,3),orders)
        moved=Chromosome((1,2,3,0),code.b,code.machines)
        self.assertTrue(released.satisfies(moved))
        self.assertTrue(released.satisfies(code))

    def test_relax_adjacencies_recomputes_all_constants(self):
        code=Chromosome((0,1,2),(0,1,2),(0,0,0))
        r=StableConstraints(code,[{'key':['adj','A',0,1],'value':1,'agreement':.99,'attempts':20}])
        relaxed=relax_adjacencies(r)
        self.assertEqual(relaxed.records,[])
        self.assertGreater(model_counts(relaxed)['binary_variables'],model_counts(r)['binary_variables'])

    def test_generated_constraints_keep_reference(self):
        code=Chromosome(tuple(range(4)),tuple(range(4)),(0,)*4)
        base=window_constraints(code,0,0,2)
        evidence={}
        for method in ('record','random'):
            restriction,info=generate(base,evidence,'A',method,23)
            self.assertTrue(restriction.satisfies(code))
            self.assertEqual(info['generated_binaries'],model_counts(restriction)['binary_variables'])


if __name__=='__main__':
    unittest.main()
