"""二阶段质量研究：全工件下降、当前解/最好解分离与受控较差解接受。"""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import time
import traceback

from problem2.common.data import load_case
from problem2.common.encoding import code_from_result, decode, evaluate
from problem2.common.evaluator import Evaluator, BudgetExpired
from problem2.common.export import export, write_json
from problem2.common.local_search import apply_move, descend
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.validation import validate_exact
from problem2.stage2.neighborhood_search import atomic_json
from problem2.stage2.perturb_rebuild import perturb_selected, repair, check_jobs


@dataclass(frozen=True)
class SearchConfig:
    sizes: tuple = (5, 7, 9)
    seed: int = 23
    batch_size: int = 1024
    cache_limit: int = 50000
    startup_seconds: float = 15
    round_seconds: float = 15
    temperature_scale: float = .005
    cooling: float = .98
    worse_cap: float = .03
    restart_stall: int = 6

    def check(self,n):
        if n<2 or not self.sizes or any(type(k) is not int or k<1 for k in self.sizes):
            raise ValueError('至少两个工件，组数必须为正整数')
        if type(self.seed) is not int or type(self.restart_stall) is not int or self.restart_stall<1:
            raise ValueError('种子或重启间隔错误')
        if type(self.batch_size) is not int or not 0<=self.batch_size<=4096:
            raise ValueError('批大小必须为0到4096整数')
        if type(self.cache_limit) is not int or self.cache_limit<1:
            raise ValueError('缓存必须为正整数')
        if not math.isfinite(self.startup_seconds) or self.startup_seconds<0:
            raise ValueError('起点下降时间错误')
        if any(not math.isfinite(v) or v<=0 for v in (self.round_seconds,self.temperature_scale)):
            raise ValueError('时间和温度比例必须有限且为正')
        if not math.isfinite(self.cooling) or not 0<self.cooling<=1 or not math.isfinite(self.worse_cap) or self.worse_cap<0:
            raise ValueError('降温或较差解限幅错误')


def acceptance(current,candidate,best,temperature,cap,rng):
    """限幅相对全程最好值；概率由候选相对当前搜索解的增量决定。"""
    if temperature<=0 or not math.isfinite(temperature) or cap<0 or not math.isfinite(cap):
        raise ValueError('接受参数错误')
    if candidate>best*(1+cap):
        return dict(accepted=False,reason='outside_best_cap',probability=0,draw=None)
    if candidate<=current:
        return dict(accepted=True,reason='nonworsening_current',probability=1,draw=None)
    probability=math.exp(-(candidate-current)/temperature)
    draw=rng.random()
    return dict(accepted=draw<probability,reason='annealed' if draw<probability else 'rejected',
                probability=probability,draw=draw)


def perturb(reference,jobs,mode,rng):
    jobs=check_jobs(reference,jobs)
    if mode=='strong':return perturb_selected(reference,jobs,rng)
    current=reference
    if mode=='machines':
        for job in jobs:current=apply_move(current,('flip',job,job))
    elif mode in ('mild_a','mild_b'):
        for job in jobs:
            sequence=current.a if mode=='mild_a' else current.b
            source=sequence.index(job)
            offsets=[i for i in range(max(0,source-3),min(len(sequence),source+4)) if i!=source]
            current=apply_move(current,('insert_a' if mode=='mild_a' else 'insert_b',source,rng.choice(offsets)))
    else:raise ValueError('未知扰动方式')
    if current==reference:current=apply_move(current,('flip',jobs[0],jobs[0]))
    return current


class PhaseEvaluator:
    """跟踪本次下降的最好候选；全程评分器仍另行保留历史最好。"""
    def __init__(self,base,initial):
        self.base,self.best=base,initial
        # 入口已有完整候选，收尾时也应登记这一个候选；不在截止后展开新邻域。
        saved_deadline=base.deadline
        base.deadline=float('inf')
        try:self.best_cost=base.cost(initial)
        finally:base.deadline=saved_deadline
        self.data=base.data

    @property
    def evaluations(self):return self.base.evaluations

    def track(self,code,value):
        if value<self.best_cost:self.best,self.best_cost=code,value
        return value

    def cost(self,code):return self.track(code,self.base.cost(code))

    def costs(self,codes):
        for code,value in self.base.costs(codes):
            self.track(code,value)
            yield code,value


def full_descent(initial,evaluator,deadline,rng):
    """先全体工件五类基本邻域，再对全体工件做A/B/机器联合插入。"""
    started=time.perf_counter()
    tracker=PhaseEvaluator(evaluator,initial)
    saved_deadline=evaluator.deadline
    boundary=started+.5*max(0,deadline-started)
    evaluator.deadline=min(saved_deadline,boundary)
    basic_complete=False
    try:
        candidate=descend(initial,tracker)
        basic_complete=True
    except BudgetExpired:
        candidate=tracker.best
    evaluator.deadline=min(saved_deadline,deadline)
    order=list(range(evaluator.data.n))
    rng.shuffle(order)
    try:
        joint,joint_info=repair(candidate,order,tracker,max_passes=50)
        candidate=tracker.best
    finally:
        evaluator.deadline=saved_deadline
    return candidate,dict(basic_complete=basic_complete,all_jobs_joint=joint_info,
                          seconds=time.perf_counter()-started,all_jobs=True)


def run(data,reference,output,config=None,seconds=90,max_rounds=10000,
        started=None,metadata=None,save_source=True,descent_fn=None):
    search_descent=full_descent if descent_fn is None else descent_fn
    config=config or SearchConfig()
    config.check(data.n)
    reference.check(data.n)
    if not math.isfinite(seconds) or seconds<0 or type(max_rounds) is not int or max_rounds<0:
        raise ValueError('总时间或轮数错误')
    started=time.perf_counter() if started is None else started
    deadline=started+seconds
    output=Path(output).resolve()
    if output.exists():raise FileExistsError('输出目录必须不存在')
    output.mkdir(parents=True)
    source=snapshot_source(output/'source') if save_source else {}
    write_json(output/'config.json',dict(parameters=asdict(config),seconds=seconds,max_rounds=max_rounds,
        metadata=metadata or {},source_sha256=source,solver_calls=0,historical_reference_cost_included=False,
        original_optimality_proven_by_this_run=False))
    initial=decode(data,reference)
    initial['validation']=validate_exact(data,initial)
    export(output/'reference',initial)
    export(output/'best',initial)
    evaluator=Evaluator(data,cache_limit=config.cache_limit,batch_size=config.batch_size)
    evaluator.cost(reference)
    evaluator.deadline=deadline
    current,current_cost=reference,initial['objective']
    rng=random.Random(config.seed)
    sizes=tuple(dict.fromkeys(min(k,data.n) for k in config.sizes))
    modes=('mild_a','mild_b','machines','strong')
    temperature=max(1,initial['objective']*config.temperature_scale)
    size_index,stall,rows,error,reason=0,0,[],None,'max_rounds'
    startup=None

    def checkpoint():
        atomic_json(output/'checkpoint.json',dict(best=evaluator.best_cost,best_code=evaluator.best.as_dict(),
            current=current_cost,current_code=current.as_dict(),rng_state=rng.getstate(),
            rounds=len(rows),temperature=temperature,stall=stall,size_index=size_index,
            elapsed_seconds=time.perf_counter()-started,resumable_search_state=False))

    def save_best():
        result=decode(data,evaluator.best)
        result['validation']=validate_exact(data,result)
        result['original_optimality_proven_by_this_run']=False
        export(output/'best',result)

    checkpoint()
    try:
        if config.startup_seconds and time.perf_counter()<deadline:
            before=evaluator.best_cost
            refined,startup=search_descent(current,evaluator,min(deadline,time.perf_counter()+config.startup_seconds),rng)
            startup.update(before_best=before,after_best=evaluator.best_cost,
                           elapsed_end=time.perf_counter()-started,best_code=evaluator.best.as_dict())
            current,current_cost=evaluator.best,evaluator.best_cost
            if evaluator.best_cost<before:save_best()
            checkpoint()
        for number in range(1,max_rounds+1):
            if time.perf_counter()>=deadline:
                reason='time_budget'
                break
            tick=time.perf_counter()
            round_deadline=min(deadline,tick+config.round_seconds)
            base,before_current,before_best=current,current_cost,evaluator.best_cost
            jobs=tuple(rng.sample(range(data.n),sizes[size_index]))
            mode=modes[(number-1)%len(modes)]
            trial=perturb(current,jobs,mode,rng)
            evaluator.deadline=min(round_deadline,tick+.2*config.round_seconds)
            repaired,repair_info=repair(trial,jobs,evaluator,max_passes=1)
            evaluator.deadline=deadline
            candidate,descent_info=search_descent(repaired,evaluator,round_deadline,rng)
            candidate_cost=evaluate(data,candidate)
            improved=evaluator.best_cost<before_best
            if improved:
                candidate,candidate_cost=evaluator.best,evaluator.best_cost
                decision=dict(accepted=True,reason='new_best',probability=1,draw=None)
            else:
                decision=acceptance(current_cost,candidate_cost,evaluator.best_cost,temperature,config.worse_cap,rng)
            if decision['accepted']:current,current_cost=candidate,candidate_cost
            stall=0 if improved else stall+1
            if improved:size_index=0
            else:size_index=(size_index+1)%len(sizes)
            restart=False
            if stall>=config.restart_stall:
                current,current_cost=evaluator.best,evaluator.best_cost
                temperature=max(1,initial['objective']*config.temperature_scale)
                stall,restart=0,True
            else:temperature=max(1,temperature*config.cooling)
            if evaluate(data,evaluator.best)!=evaluator.best_cost:
                raise AssertionError('全程最好分数不一致')
            row=dict(round=number,mode=mode,selected=list(jobs),before_current=before_current,
                before_best=before_best,perturbed=evaluate(data,trial),repaired=evaluate(data,repaired),
                candidate=candidate_cost,current=current_cost,best=evaluator.best_cost,
                decision=decision,restart=restart,improved=improved,seconds=time.perf_counter()-tick,
                base_code=base.as_dict(),trial_code=trial.as_dict(),candidate_code=candidate.as_dict(),
                current_code=current.as_dict(),best_code=evaluator.best.as_dict(),
                repair=repair_info,descent=descent_info)
            rows.append(row)
            atomic_json(output/'rounds.json',rows)
            checkpoint()
            if improved:save_best()
            print(json.dumps(dict(round=number,mode=mode,candidate=candidate_cost,
                current=current_cost,best=evaluator.best_cost,accepted=decision['accepted'])),flush=True)
        else:reason='max_rounds'
    except BaseException:
        error,reason=traceback.format_exc(),'error'
        write_json(output/'failure.json',dict(error=error))
        raise
    finally:
        save_best()
        final=decode(data,evaluator.best)
        final['validation']=validate_exact(data,final)
        final['original_optimality_proven_by_this_run']=False
        export(output/'final',final)
        working=decode(data,current)
        working['validation']=validate_exact(data,working)
        export(output/'current',working)
        atomic_json(output/'rounds.json',rows)
        checkpoint()
        summary=dict(complete=error is None,termination=reason,initial=initial['objective'],
            best=evaluator.best_cost,current=current_cost,rounds=len(rows),startup=startup,
            seconds=time.perf_counter()-started,evaluations=evaluator.evaluations,
            cache_hits=evaluator.cache_hits,cached_codes=len(evaluator.cache),
            improvements=evaluator.progress,rows=rows,solver_calls=0,
            evaluator_offset_seconds=evaluator.started-started,
            accepted_worse=sum(r['decision']['accepted'] and r['candidate']>r['before_current'] for r in rows),
            original_optimality_proven_by_this_run=False,resumable_search_state=False)
        write_json(output/'summary.json',summary)
    return final


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',type=int,choices=(1,2),required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=90)
    parser.add_argument('--seed',type=int,default=23)
    parser.add_argument('--max-rounds',type=int,default=10000)
    args=parser.parse_args()
    started=time.perf_counter()
    if args.output.exists():parser.error('输出目录已存在')
    data=load_case(PROJECT_ROOT/'问题2数据.xlsx',args.case)
    raw=args.reference.read_bytes()
    result=json.loads(raw.decode('utf-8-sig'))
    if result['case']!=args.case:parser.error('参考算例错误')
    validate_exact(data,result)
    reference=code_from_result(result,data.n)
    metadata=dict(input_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (PROJECT_ROOT/'问题2.pdf',PROJECT_ROOT/'问题2数据.xlsx')},
        reference=str(args.reference.resolve()),reference_sha256=hashlib.sha256(raw).hexdigest())
    final=run(data,reference,args.output,SearchConfig(seed=args.seed),args.seconds,args.max_rounds,
              started=started,metadata=metadata)
    print(json.dumps(dict(final=final['objective'],seconds=time.perf_counter()-started)))


if __name__=='__main__':main()
