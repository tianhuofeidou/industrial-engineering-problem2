"""单轮串联现有扰动、完整重建/下降、受限区间求解；不修改项目算法。"""
from pathlib import Path
import argparse, datetime, hashlib, json, os, random, sys, time, traceback
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from problem2.common.data import load_case
from problem2.common.encoding import Chromosome,code_from_result,decode,evaluate
from problem2.common.evaluator import Evaluator
from problem2.common.export import export,write_json
from problem2.common.solver_utils import optimize_once
from problem2.common.validation import validate_exact
from problem2.stage1.neighborhoods import choose_window,window_constraints
from problem2.stage2.iterated_search import PhaseEvaluator,full_descent
from problem2.stage2.perturb_rebuild import perturb_selected,repair
from problem2.stage2.neighborhood_search import atomic_json

def code_sha(code):
    return hashlib.sha256(json.dumps(code.as_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest()

def should_refine(policy,candidate_value,global_best_before):
    if policy not in ('always','gated'):raise ValueError('Unknown refinement policy')
    return policy=='always' or candidate_value<=global_best_before

def execute(data,parent,request,folder,deadline,solver_env):
    folder=Path(folder).resolve()
    folder.mkdir(parents=True,exist_ok=False)
    tick=time.perf_counter()
    rng=random.Random(request['seed'])
    evaluator=Evaluator(data,cache_limit=50000,batch_size=1024)
    evaluator.cost(parent)
    evaluator.deadline=deadline
    candidate=parent
    phases=[]
    proofs=[]
    error=None
    def save(name,code):
        result=decode(data,code)
        validate_exact(data,result)
        assert evaluate(data,code)==result['objective']
        assert len(result['operations'])==10*data.n
        result['original_optimality_proven_by_this_run']=False
        export(folder/name,result)
        return result
    def progress(stage):
        atomic_json(folder/'progress.json',dict(stage=stage,best=evaluator.best_cost,
            candidate=evaluate(data,candidate),seconds=time.perf_counter()-tick,complete=False))
        save('best',evaluator.best)
    write_json(folder/'request.json',request)
    save('reference',parent)
    save('best',parent)
    try:
        jobs=tuple(rng.sample(range(data.n),min(request['size'],data.n)))
        candidate=perturb_selected(parent,jobs,rng)
        trial=candidate
        heuristic_end=min(deadline,time.perf_counter()+request['heuristic_seconds'])
        evaluator.deadline=min(heuristic_end,time.perf_counter()+request['repair_seconds'])
        tracker=PhaseEvaluator(evaluator,candidate)
        _returned,repair_info=repair(candidate,jobs,tracker,max_passes=50)
        candidate=tracker.best
        save('perturbed',trial)
        save('repaired',candidate)
        phases.append(dict(stage='rebuild',selected=jobs,perturbed=evaluate(data,trial),
            repaired=evaluate(data,candidate),info=repair_info))
        evaluator.deadline=deadline
        progress('descent')
        candidate,descent_info=full_descent(candidate,evaluator,heuristic_end,rng)
        save('descended',candidate)
        phases.append(dict(stage='descent',objective=evaluate(data,candidate),info=descent_info))
        policy=request.get('refinement_policy','always')
        threshold=request.get('global_best_before',evaluate(data,parent))
        eligible=should_refine(policy,evaluate(data,candidate),threshold)
        phases.append(dict(stage='refinement_trigger',policy=policy,
            candidate_before_refinement=evaluate(data,candidate),global_best_before=threshold,
            eligible=eligible,rule='always OR candidate_after_descent <= frozen_best_at_round_start'))
        progress('gurobi' if eligible else 'gurobi_skipped')
        refinement_tick=time.perf_counter()
        for step,(width,limit) in enumerate(zip(request['widths'],request['solver_seconds']),1):
            if not eligible:break
            if time.perf_counter()>=deadline-2:break
            width=min(width,data.n-1)
            parent_ref=candidate
            digest=code_sha(parent_ref)
            seen={(parent_ref,int(v['width']),int(v['start_a']),int(v['start_b']))
                  for v in request.get('proved_windows',[]) if v['reference_sha256']==digest}
            choice=choose_window(data,parent_ref,width,{},seen,request['round']*3+step-1,rng)
            if choice is None:continue
            a,b,policy=choice
            restriction=window_constraints(parent_ref,a,b,width)
            assert restriction.satisfies(parent_ref)
            model_folder=folder/'gurobi'/f'step{step:02d}'
            model_deadline=min(deadline,time.perf_counter()+limit)
            result=optimize_once(data,parent_ref,restriction,model_folder,
                min(limit,max(0,deadline-time.perf_counter())),request['threads'],
                strengthen=True,compact=True,solver_env=solver_env,deadline=model_deadline)
            validate_exact(data,result)
            candidate=code_from_result(result,data.n)
            assert restriction.satisfies(candidate)
            assert evaluate(data,candidate)<=evaluate(data,parent_ref)
            assert result['proof']['scope']=='restricted'
            PhaseEvaluator(evaluator,candidate)  # 完成的完整候选即使恰好到时也登记。
            record=dict(stage='gurobi',step=step,width=width,start_a=a,start_b=b,policy=policy,
                before=evaluate(data,parent_ref),after=evaluate(data,candidate),
                reference_code=parent_ref.as_dict(),candidate_code=candidate.as_dict(),
                folder=str(model_folder),proof=result['proof'])
            phases.append(record)
            if result['proof']['optimal']:
                proofs.append(dict(reference_sha256=digest,width=width,start_a=a,start_b=b))
            progress('gurobi')
        phases.append(dict(stage='refinement_timing',seconds=time.perf_counter()-refinement_tick))
    except BaseException:
        error=traceback.format_exc()
        write_json(folder/'failure.json',dict(error=error,seconds=time.perf_counter()-tick))
        raise
    finally:
        save('candidate',candidate)
        best=save('best',evaluator.best)
        summary=dict(complete=error is None,before=evaluate(data,parent),candidate=evaluate(data,candidate),
            best=best['objective'],best_code=evaluator.best.as_dict(),candidate_code=candidate.as_dict(),
            phases=phases,proved_windows=proofs,seconds=time.perf_counter()-tick,
            evaluations=evaluator.evaluations,cache_hits=evaluator.cache_hits,
            improvements=evaluator.progress,original_optimality_proven_by_this_run=False)
        write_json(folder/'summary.json',summary)
        atomic_json(folder/'progress.json',dict(complete=error is None,stage='finished',
            best=best['objective'],candidate=evaluate(data,candidate),seconds=summary['seconds']))
    return summary

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',type=Path,required=True)
    args=parser.parse_args()
    started=time.perf_counter()
    req=json.loads(args.request.read_text(encoding='utf-8'))
    end=datetime.datetime.fromisoformat(req['work_deadline_utc'])
    remaining=(end-datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    deadline=started+min(req['seconds'],remaining)
    assert deadline>started
    for name,value in req['input_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value
    path=Path(req['reference'])
    assert hashlib.sha256(path.read_bytes()).hexdigest()==req['reference_sha256']
    data=load_case(ROOT/'问题2数据.xlsx',2)
    result=json.loads(path.read_text(encoding='utf-8-sig'))
    validate_exact(data,result)
    parent=code_from_result(result,data.n)
    import gurobipy as gp
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag',0)
        env.start()
        execute(data,parent,req,Path(req['output']),deadline,env)

if __name__=='__main__':main()
