"""公开单次二阶段串联；搜索逻辑来自已验证夜间控制器，独立于批次归档路径。"""
import os,sys,importlib.util,json,time,hashlib,random,shutil,subprocess,traceback,math
from pathlib import Path
from datetime import datetime,timezone
OUT=Path(__file__).resolve().parent
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(OUT));sys.path.insert(0,str(ROOT))
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'
from problem2.common.data import load_case
from problem2.common.encoding import Chromosome,decode,evaluate,code_from_result
from problem2.common.export import export
from problem2.common.validation import validate_exact
from problem2.common.paths import source_files,source_relative
from problem2.stage1.windows import refine_windows
from problem2.stage1.neighborhoods import window_constraints
from problem2.stage2.iterated_search import acceptance

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def write(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)
def code(raw):return Chromosome(**{k:tuple(v) for k,v in raw.items()})
def hybrid_module():
    spec=importlib.util.spec_from_file_location('archived_hybrid_round',OUT/'hybrid_round.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def checked(data,p):
    r=read(p);validate_exact(data,r);c=code_from_result(r,data.n)
    assert len(r['operations'])==10*data.n and evaluate(data,c)==r['objective']
    return c,r
def availability(events,limits):
    return {str(t):min((e['objective'] for e in events if e['elapsed_seconds']<=t),default=None) for t in limits}

class Cell:
    def __init__(self,data,reference,folder,spec,m,notify=True):
        self.data=data;self.folder=Path(folder);self.spec=spec;self.m=m;self.notify=notify
        self.folder.mkdir(parents=True,exist_ok=False)
        self.epoch=spec['started_epoch'];self.tick=time.perf_counter()
        self.deadline=self.tick+max(0,self.epoch+spec['seconds']-spec.get('audit_reserve_seconds',60)-time.time())
        self.best=code_from_result(reference,data.n);self.value=evaluate(data,self.best);self.events=[];self.records=[]
        self.first=0.;export(self.folder/'reference',reference);self.observe(decode(data,self.best),force=True)
    def elapsed(self):return time.time()-self.epoch
    def status(self,**extra):
        write(self.folder/'progress.json',dict(best=self.value,elapsed_seconds=self.elapsed(),updated_utc=now(),**extra))
    def observe(self,result,force=False):
        validate_exact(self.data,result);candidate=code_from_result(result,self.data.n);v=evaluate(self.data,candidate)
        assert v==result['objective']
        if force or v<self.value:
            self.best,self.value=candidate,v
            export(self.folder/'best',decode(self.data,self.best))
            event=dict(elapsed_seconds=self.elapsed(),objective=v,kind='verified_best_available')
            self.events.append(event);self.first=event['elapsed_seconds']
            write(self.folder/'availability.json',self.events)
        self.status()
    def hybrid(self,seed,max_rounds=100000,short=False):
        h=hybrid_module();original=h.export
        def measured(folder,result):
            original(folder,result)
            if Path(folder).name=='best':self.observe(result)
        h.export=measured
        rng=random.Random(seed);current=self.best;temperature=max(1,self.value*.005);stall=size_index=0;ledger={}
        import gurobipy as gp
        self.termination='remaining_time_below_180_seconds'
        try:
            with gp.Env(empty=True) as env:
                env.setParam('OutputFlag',0);env.start()
                for number in range(1,max_rounds+1):
                    remaining=self.deadline-time.perf_counter()
                    if remaining<(3 if short else 180):break
                    if shutil.disk_usage(ROOT).free<15*1024**3:raise RuntimeError('Disk reserve below 15 GiB')
                    before=self.value;before_current=evaluate(self.data,current)
                    req=dict(round=number,seed=rng.getrandbits(31),size=(5,7,9)[size_index],
                        heuristic_seconds=.15 if short else 120,repair_seconds=.05 if short else 45,
                        widths=[5,7,9],solver_seconds=[1,1,1] if short else [90,120,180],threads=6,
                        refinement_policy=self.spec['method'],global_best_before=before,
                        proved_windows=list(ledger.values()),seconds=min(540,remaining-2))
                    folder=self.folder/'rounds'/f'round{number:05d}'
                    record=h.execute(self.data,current,req,folder,min(self.deadline,time.perf_counter()+req['seconds']),env)
                    assert record['complete'];self.observe(decode(self.data,code(record['best_code'])))
                    candidate=code(record['candidate_code']);improved=self.value<before
                    if improved:
                        current=self.best;decision=dict(accepted=True,reason='new_global_best',probability=1,draw=None)
                    else:
                        decision=acceptance(before_current,record['candidate'],self.value,temperature,.03,rng)
                        if decision['accepted']:current=candidate
                    stall=0 if improved else stall+1;size_index=0 if improved else (size_index+1)%3
                    restart=stall>=6
                    if restart:current=self.best;temperature=max(1,self.spec['objective']*.005);stall=0
                    else:temperature=max(1,temperature*.98)
                    for proof in record['proved_windows']:ledger[json.dumps(proof,sort_keys=True)]=proof
                    self.records.append(dict(round=number,size=req['size'],seed=req['seed'],before_best=before,
                        before_current=before_current,best=self.value,current=evaluate(self.data,current),candidate=record['candidate'],
                        improved=improved,acceptance=decision,restart=restart,folder=str(folder),elapsed_seconds=self.elapsed(),
                        refinement_trigger=next(p for p in record['phases'] if p['stage']=='refinement_trigger'),
                        gurobi_calls=sum(p['stage']=='gurobi' for p in record['phases']),
                        evaluations=record['evaluations'],round_evaluated_best=record['best']))
                    write(self.folder/'rounds.json',self.records)
                    write(self.folder/'checkpoint.json',dict(current=current.as_dict(),best=self.best.as_dict(),best_cost=self.value,
                        rng_state=rng.getstate(),temperature=temperature,stall=stall,size_index=size_index,
                        completed_rounds=len(self.records),proved_windows=list(ledger.values()),unconditional_resume_supported=False))
                    self.status(rounds=len(self.records),current=evaluate(self.data,current))
                else:self.termination='max_rounds'
        finally:h.export=original
    def finish(self,error=None):
        result=decode(self.data,self.best);validate_exact(self.data,result)
        result['run_info']=dict(scope='restricted',original_optimality_proven_by_this_run=False,
            initial_objective=self.spec['objective'],method=self.spec['method'],historical_preparation_included=False)
        export(self.folder/'final',result)
        write(self.folder/'availability.json',self.events)
        summary=dict(complete=error is None,id=self.spec['id'],method=self.spec['method'],start=self.spec['objective'],
            seed=self.spec['seed'],initial_code_sha256=self.spec['code_sha256'],objective=self.value,scope='restricted',
            original_optimality_proven_by_this_run=False,seconds=self.elapsed(),rounds=len(self.records),
            best_available_seconds=self.first,checkpoints=availability(self.events,[1800,3600,5400]),
            availability=self.events,termination=getattr(self,'termination','failure'),error=error)
        write(self.folder/'summary.json',summary);self.status(complete=error is None)
        return summary
