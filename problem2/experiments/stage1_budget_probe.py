"""停止条件四组重复对照及宽度32试探的三个新种子对照。"""
import argparse
from dataclasses import asdict
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from problem2.common.annealing_records import as_code
from problem2.common.data import load_case
from problem2.common.encoding import BatchEvaluator, code_from_result, decode, evaluate
from problem2.common.export import export, write_json, write_csv
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.solver_utils import optimize_once
from problem2.common.stable_constraints import StableConstraints
from problem2.common.validation import validate_exact
from problem2.experiments.stage1_adaptive_time import probe
from problem2.experiments.stage1_free_jobs import CONFIG, prepare, read
from problem2.stage1.windows import refine_windows
from problem2.stage2.joint_search import free_job_constraints

CELLS = {'s110_r80': (110,80), 's110_r200': (110,200),
         's180_r80': (180,80), 's180_r200': (180,200)}
NEW_SEEDS = (41,53,71)
METHODS = ('interval','probe32','probe32_exact')
REPEATS = (1,2,3)


def pair_pool(n, reference, seen, rng, size=24):
    available = [p for p in itertools.combinations(range(n),2) if (reference,p) not in seen]
    jobs = rng.sample(available,min(size,len(available)))
    seen.update((reference,p) for p in jobs)
    return jobs


def choose_exact(rows,rng):
    if not rows:
        return None
    return min(range(len(rows)), key=lambda i:(rows[i]['rank_value'],-rows[i]['near_count'],rng.random()))


def window_branch(base,seed,label,budget,max_rounds):
    folder=base/label
    folder.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    data=load_case(PROJECT_ROOT/'问题2数据.xlsx',2)
    initial=code_from_result(read(base/f'prefix_seed{seed}/annealing/result.json'),data.n)
    cost=evaluate(data,initial)
    improvements=[]
    def accepted(code,row):
        nonlocal cost
        value=evaluate(data,code)
        if value<cost:
            cost=value
            improvements.append({'objective':value,'elapsed_seconds':time.perf_counter()-started,
                'round':row['round'],'code':code.as_dict(),'source':'interval'})
            export(folder/'best',decode(data,code))
    result=refine_windows(data,initial,{},folder/'window',budget=max(.1,budget-(time.perf_counter()-started)),
        per_round=5,max_rounds=max_rounds,width=5,seed=seed,threads=8,compact=True,reuse_env=True,
        cache_enabled=False,deadline=started+budget,on_round=accepted)
    current=code_from_result(result,data.n)
    export(folder/'final',decode(data,current))
    elapsed=time.perf_counter()-started
    records=result['refinement']['records']
    reason='time_budget' if elapsed>=budget-.1 else ('round_cap' if records and records[-1]['round']>=max_rounds else 'ranges_exhausted')
    summary={'seed':seed,'label':label,'before':evaluate(data,initial),'after':evaluate(data,current),
        'budget_seconds':budget,'max_rounds':max_rounds,'additional_seconds':elapsed,'rounds':records,
        'round_count':len(records),'termination':reason,'improvements':improvements,
        'first_improvement_seconds':improvements[0]['elapsed_seconds'] if improvements else None,
        'start_code':initial.as_dict(),'complete':True,'scope':'restricted','original_optimality_proven':False}
    write_json(folder/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ('label','seed','after','additional_seconds','round_count','termination')}),flush=True)


def wide_branch(base,seed,method,budget=180):
    if method=='interval':
        window_branch(base,seed,method,budget,200)
        return
    folder=base/method
    folder.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    deadline=started+budget
    data=load_case(PROJECT_ROOT/'问题2数据.xlsx',2)
    initial=current=code_from_result(read(base/f'prefix_seed{seed}/annealing/result.json'),data.n)
    cost=evaluate(data,current)
    scorer=BatchEvaluator(data)
    rng,selection_rng=random.Random(seed+3000),random.Random(seed+4000)
    records,probes,improvements=[],[],[]
    seen=set()
    env=None
    if method=='probe32_exact':
        import gurobipy as gp
        env=gp.Env(empty=True)
        env.setParam('OutputFlag',0)
        env.start()
    def accept(code,source):
        nonlocal cost,current
        value=evaluate(data,code)
        if value<cost:
            current,cost=code,value
            result=decode(data,code)
            result['validation']=validate_exact(data,result)
            export(folder/'best',result)
            improvements.append({'objective':cost,'elapsed_seconds':time.perf_counter()-started,
                'source':source,'code':code.as_dict()})
            print(json.dumps({'seed':seed,'method':method,'best':cost,'source':source,
                'seconds':improvements[-1]['elapsed_seconds']}),flush=True)
    try:
        for batch in range(200):
            if time.perf_counter()>=deadline-.1:
                break
            reference=current
            jobs_list=pair_pool(data.n,reference,seen,rng)
            if not jobs_list:
                break
            rows,candidates=[],[]
            for jobs in jobs_list:
                if time.perf_counter()>=deadline:
                    break
                candidate,row=probe(data,reference,jobs,scorer,width=32,deadline=deadline)
                rows.append(row)
                candidates.append(candidate)
                probes.append(row|{'batch':batch+1,'reference_code':reference.as_dict(),
                    'elapsed_seconds':time.perf_counter()-started})
            if not rows:
                break
            best_index=min(range(len(rows)),key=lambda i:rows[i]['best_objective'])
            accept(candidates[best_index],'decoding_probe')
            # 每批同时从同一参考试探；只在整批结束后更新参考，再从当前解生成精确限制。
            if method=='probe32_exact' and time.perf_counter()<deadline-.5:
                index=best_index if rows[best_index]['best_objective']<evaluate(data,reference) else choose_exact(rows,selection_rng)
                jobs=tuple(rows[index]['jobs'])
                restriction=free_job_constraints(current,jobs)
                before=cost
                solved=optimize_once(data,current,restriction,folder/f'round{len(records)+1:03d}',
                    min(15,deadline-time.perf_counter()),8,strengthen=True,compact=True,solver_env=env,deadline=deadline)
                accept(code_from_result(solved,data.n),'gurobi')
                records.append({'round':len(records)+1,'batch':batch+1,'jobs':list(jobs),
                    'before':before,'after':cost,'proof':solved['proof'],
                    'selection':rows[index],'elapsed_seconds':time.perf_counter()-started})
            write_json(folder/'checkpoint.json',{'best':cost,'batches':batch+1,'rounds':records,
                'probes':probes,'improvements':improvements,'complete':False})
    finally:
        if env is not None:
            env.dispose()
    final=decode(data,current)
    final['validation']=validate_exact(data,final)
    export(folder/'final',final)
    summary={'seed':seed,'label':method,'before':evaluate(data,initial),'after':cost,
        'budget_seconds':budget,'additional_seconds':time.perf_counter()-started,'rounds':records,
        'round_count':len(records),'probes':probes,'improvements':improvements,'beam_width':32,'pool_size':24,
        'first_improvement_seconds':improvements[0]['elapsed_seconds'] if improvements else None,
        'start_code':initial.as_dict(),'termination':'time_budget' if time.perf_counter()>=deadline-.1 else 'ranges_exhausted',
        'complete':True,'original_optimality_proven':False}
    write_json(folder/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ('seed','label','after','additional_seconds','round_count')}),flush=True)


def worker(root,phase,deadline,repeat=None,seed=None,label=None):
    tag=f'{phase}_r{repeat}_s{seed}_{label or "prefix"}'
    cmd=[sys.executable,'-u','-B','-m','problem2.experiments.stage1_budget_probe','--output',str(root),'--phase',phase]
    for name,value in (('repeat',repeat),('seed',seed),('label',label)):
        if value is not None:
            cmd+=['--'+name,str(value)]
    required=190 if phase in ('grid','wide') else 100
    remaining=deadline-time.perf_counter()
    if remaining<required:
        return False
    print(json.dumps({'event':'start','run':tag}),flush=True)
    with (root/f'{tag}.log').open('w',encoding='utf-8') as log:
        done=subprocess.run(cmd,cwd=PROJECT_ROOT,stdout=log,stderr=subprocess.STDOUT,
            timeout=min(240,remaining),env=os.environ|{'PYTHONIOENCODING':'utf-8'})
    if done.returncode:
        raise RuntimeError(f'{tag} failed; inspect log')
    return True


def audit(root,grid,wide):
    config=read(root/'config.json')
    for name,digest in config['source_sha256'].items():
        assert hashlib.sha256((PROJECT_ROOT/name).read_bytes()).hexdigest()==digest
    for name,digest in config['code_sha256'].items():
        assert hashlib.sha256((root/'source'/name).read_bytes()).hexdigest()==digest
        assert hashlib.sha256((PROJECT_ROOT/'problem2'/name).read_bytes()).hexdigest()==digest
    data=load_case(PROJECT_ROOT/'问题2数据.xlsx',2)
    schedules=models=0
    for path in root.rglob('result.json'):
        result=read(path)
        validate_exact(data,result)
        decoded=evaluate(data,code_from_result(result,data.n))
        assert decoded<=result['objective']+1e-4
        if path.parent.name!='solver_schedule':
            assert abs(decoded-result['objective'])<=1e-4
        schedules+=1
        if not (path.parent/'model.mps').exists():
            continue
        p=result['proof']
        assert p['scope']=='restricted' and not p['original_optimality_proven_by_this_run']
        assert hashlib.sha256((path.parent/'model.mps').read_bytes()).hexdigest()==p['model_sha256']
        raw=read(path.parent/'restrictions.json')
        restriction=StableConstraints(as_code(raw['reference_code']),raw['selected_relations'])
        assert restriction.satisfies(restriction.reference) and restriction.satisfies(code_from_result(result,data.n))
        assert p['bound']<=result['objective']+1e-4
        if p['optimal']:
            assert abs(p['bound']-result['objective'])<=1e-4
        models+=1
    for repeat in REPEATS:
        starts=[r['start_code'] for r in grid if r['repeat']==repeat]
        assert len(starts)==4 and all(c==starts[0] for c in starts)
    for seed in NEW_SEEDS:
        starts=[r['start_code'] for r in wide if r['seed']==seed]
        assert len(starts)==3 and all(c==starts[0] for c in starts)
    return {'schedules_validated':schedules,'models_validated':models,'hashes_verified':True,
        'same_start_in_each_comparison':True,'original_optimality_proven':False}


def orchestrate(root,global_seconds):
    root.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    deadline=started+global_seconds
    write_json(root/'config.json',{'case':2,'grid_seed':23,'repeats':REPEATS,'cells':CELLS,
        'new_seeds':NEW_SEEDS,'methods':METHODS,'wide_budget_seconds':180,'pool_size':24,'beam_width':32,
        'exact_seconds':15,'threads':8,'search':asdict(CONFIG),'global_seconds_after_launch':global_seconds,
        'default_algorithm_modified':False,'uses_historical_reference':False,'full_case2_model_allowed':False,
        'code_sha256':snapshot_source(root/'source'),'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (PROJECT_ROOT/'问题2.pdf',PROJECT_ROOT/'问题2数据.xlsx')}})
    grid,wide,prefixes=[],[],[]
    orders=(tuple(CELLS),('s180_r80','s180_r200','s110_r80','s110_r200'),
        ('s180_r200','s180_r80','s110_r200','s110_r80'))
    for repeat,order in zip(REPEATS,orders):
        base=root/'grid'/f'repeat{repeat}'
        base.mkdir(parents=True)
        if not worker(root,'grid_prepare',deadline,repeat=repeat,seed=23):
            raise TimeoutError('预算不足完成初始化')
        prefixes.append(read(base/'prefix_seed23/summary.json')|{'repeat':repeat,'phase':'grid'})
        for label in order:
            if not worker(root,'grid',deadline,repeat=repeat,seed=23,label=label):
                write_json(root/'partial_summary.json',{'complete':False,'grid':grid,'wide':wide,'prefixes':prefixes})
                return
            row=read(base/label/'summary.json')|{'repeat':repeat}
            grid.append(row)
            write_json(root/'partial_summary.json',{'complete':False,'grid':grid,'wide':wide,'prefixes':prefixes})
            print(json.dumps({k:row[k] for k in ('repeat','label','after','additional_seconds','round_count','termination')}),flush=True)
    for i,seed in enumerate(NEW_SEEDS):
        base=root/'wide'/f'seed{seed}'
        base.mkdir(parents=True)
        if not worker(root,'wide_prepare',deadline,seed=seed):
            raise TimeoutError('预算不足完成新种子准备')
        prefixes.append(read(base/f'prefix_seed{seed}/summary.json')|{'phase':'wide'})
        for label in METHODS[i:]+METHODS[:i]:
            if not worker(root,'wide',deadline,seed=seed,label=label):
                write_json(root/'partial_summary.json',{'complete':False,'grid':grid,'wide':wide,'prefixes':prefixes})
                return
            row=read(base/label/'summary.json')
            wide.append(row)
            write_json(root/'partial_summary.json',{'complete':False,'grid':grid,'wide':wide,'prefixes':prefixes})
            print(json.dumps({k:row[k] for k in ('seed','label','after','additional_seconds','round_count')}),flush=True)
    verification=audit(root,grid,wide)
    summary={'complete':True,'grid':grid,'wide':wide,'prefixes':prefixes,
        'wall_seconds':time.perf_counter()-started,'verification':verification,'original_optimality_proven':False}
    write_json(root/'summary.json',summary)
    write_json(root/'verification.json',verification)
    write_json(root/'status.json',{'complete':True,'verification':verification})
    print(json.dumps({'event':'all_complete','wall_seconds':summary['wall_seconds'],'verification':verification}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--phase',choices=('all','grid_prepare','grid','wide_prepare','wide'),default='all')
    parser.add_argument('--repeat',type=int,choices=REPEATS)
    parser.add_argument('--seed',type=int)
    parser.add_argument('--label',choices=tuple(CELLS)+METHODS)
    parser.add_argument('--global-seconds',type=float,default=4600)
    args=parser.parse_args()
    root=args.output.resolve()
    if args.phase=='all':
        orchestrate(root,args.global_seconds)
    elif args.phase in ('grid_prepare','grid'):
        if args.repeat is None:
            parser.error('停止条件实验需要重复编号')
        base=root/'grid'/f'repeat{args.repeat}'
        if args.phase=='grid_prepare':
            prepare(base,23)
        else:
            if args.label not in CELLS:
                parser.error('需要合法停止条件组合')
            window_branch(base,23,args.label,*CELLS[args.label])
    elif args.seed not in NEW_SEEDS:
        parser.error('评分对照需要新种子41/53/71')
    elif args.phase=='wide_prepare':
        prepare(root/'wide'/f'seed{args.seed}',args.seed)
    elif args.label not in METHODS:
        parser.error('需要合法评分方法')
    else:
        wide_branch(root/'wide'/f'seed{args.seed}',args.seed,args.label)


if __name__=='__main__': main()
