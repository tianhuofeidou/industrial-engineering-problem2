"""运行10335所用二阶段策略；提供相同参数，不保证相同目标值。"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
BUNDLE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start',type=int,choices=(10445,10492,10520),default=10520)
    parser.add_argument('--policy',choices=('always','gated'),default='gated')
    parser.add_argument('--seed',type=int)
    parser.add_argument('--seconds',type=float,default=5400)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--portable',action='store_true',help='不绑定Windows物理核，记录资源差异')
    args=parser.parse_args()
    if args.seconds<=240:parser.error('预算须大于240秒，含60秒核验导出预留')
    folder=args.output.resolve()
    if folder.exists():parser.error('输出目录必须不存在')
    if os.name!='nt' and not args.portable:parser.error('非Windows请显式使用--portable')
    started=time.time()
    for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[key]='1'
    if args.portable:
        actual=dict(gurobi_threads=6,affinity_applied=False,priority_applied=False,mode='portable')
    else:
        rspec=importlib.util.spec_from_file_location('stage2_10335_resources',BUNDLE/'resources.py')
        resources=importlib.util.module_from_spec(rspec);rspec.loader.exec_module(resources)
        actual=resources.apply(resources.select())
    from problem2.published.stage2_10335 import pipeline as p
    params=p.read(BUNDLE/'parameters.json')
    for filename,expected in params['input_sha256'].items():
        if hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()!=expected:
            raise ValueError('原始输入SHA不匹配：'+filename)
    starts=p.read(BUNDLE/'starts.json')['starts']
    item=next(x for x in starts if x['objective']==args.start)
    data=p.load_case(ROOT/'问题2数据.xlsx',2)
    reference=p.code(item['code']);result=p.decode(data,reference);p.validate_exact(data,result)
    assert p.evaluate(data,reference)==args.start
    digest=hashlib.sha256(json.dumps(reference.as_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert digest==item['code_sha256']
    seed=args.seed if args.seed is not None else item['paired_seed']
    spec=dict(id=f'start{args.start}_{args.policy}',method=args.policy,objective=args.start,seed=seed,
        started_epoch=started,seconds=args.seconds,audit_reserve_seconds=60,code_sha256=digest)
    folder.mkdir(parents=True,exist_ok=False)
    p.write(folder/'resources.json',actual);p.write(folder/'spec.json',spec)
    cell=p.Cell(data,result,folder/'main',spec,{},notify=False)
    try:
        cell.hybrid(seed)
        summary=cell.finish()
    except BaseException:
        cell.finish(p.traceback.format_exc());raise
    elapsed=time.time()-started
    p.write(folder/'reproduction.json',dict(start=args.start,policy=args.policy,seed=seed,
        nominal_seconds=args.seconds,audit_reserve_seconds=60,actual_seconds=elapsed,resources=actual,
        scope='restricted',original_optimality_proven=False,exact_objective_reproduction_guaranteed=False,
        historical_start_generation_seconds_included=False,
        instrumentation='Standalone Cell wrapper; batch-controller hashing and aggregate status writes omitted'))
    print(json.dumps(dict(objective=summary['objective'],seconds=elapsed,scope='restricted')))

if __name__=='__main__':main()
