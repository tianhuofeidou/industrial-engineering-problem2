"""Optional interval-width cap: preserve default transitions and enforce explicit caps."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from problem2.common.data import CaseData
from problem2.common.encoding import Chromosome,decode
import problem2.stage1.windows as windows

def fake_run(module,cap='omitted',exhaust=False,timeout_at_seven=False,rounds=24):
    data=CaseData(2,tuple(f'J{i+1}' for i in range(12)),((1,)*10,)*12,tuple((0,)*12 for _ in range(12)))
    ref=Chromosome(tuple(range(12)),tuple(range(12)),(0,)*12)
    seen=[]
    def choose(data,ref,width,*args):
        seen.append(width)
        return None if exhaust else (0,0,'test')
    def solve(data,ref,restriction,folder,*args,**kw):
        folder.mkdir(parents=True)
        optimal=not(timeout_at_seven and seen[-1]>=7)
        result=decode(data,ref)
        result['proof']={'optimal':optimal,'reduction':{'binary_variables':0},'runtime':0,'status':2 if optimal else 9}
        return result
    options={} if cap=='omitted' else {'max_width':cap}
    with tempfile.TemporaryDirectory() as temp,patch.object(module,'optimize_once',solve),patch.object(module,'print'):
        result=module.refine_windows(data,ref,{},Path(temp)/'run',budget=20,max_rounds=rounds,width=5,
            cache_enabled=False,selector=choose,**options)
    return seen,result

class WidthCapTests(unittest.TestCase):
    def test_default_expands_through_nine(self):
        widths,_=fake_run(windows)
        self.assertEqual(set(widths),{5,7,9})
    def test_explicit_cap_blocks_growth_at_seven(self):
        widths,result=fake_run(windows,7)
        self.assertEqual(set(widths),{5,7})
        self.assertEqual(result['refinement']['max_width'],7)
    def test_exhaustion_respects_explicit_cap(self):
        self.assertEqual(fake_run(windows,7,exhaust=True)[0],[5,7])
        self.assertEqual(fake_run(windows,exhaust=True)[0],[5,7,9])
    def test_shrink_is_retained(self):
        widths,_=fake_run(windows,7,timeout_at_seven=True)
        self.assertIn((7,5),list(zip(widths,widths[1:])))
        self.assertLessEqual(max(widths),7)
    def test_explicit_nine_matches_default(self):
        a,ra=fake_run(windows);b,rb=fake_run(windows,9)
        self.assertEqual(a,b)
        self.assertEqual(ra['objective'],rb['objective'])
    def test_invalid_cap_rejected(self):
        for cap in (0,-1,True,7.5,'7'):
            with self.subTest(cap=cap),self.assertRaises(ValueError):fake_run(windows,cap)

if __name__=='__main__':unittest.main()
