"""只读取已有运行，核验并摘录PPT数据；不调用求解器，不启动搜索。"""
from pathlib import Path
import csv
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'PPT制作'
sys.path.insert(0, str(ROOT))
from problem2.common.data import load_case
from problem2.common.validation import validate_exact
from problem2.common.encoding import code_from_result, evaluate

sources = {}
def read(rel):
    p = ROOT / rel
    sources[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return json.loads(p.read_text(encoding='utf-8-sig'))

def write(rel, value):
    p = OUT / rel
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\r\n')

def table(rel, rows):
    with (OUT / rel).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def excerpt(rel):
    p = ROOT / rel
    sources[rel] = hashlib.sha256(p.read_bytes()).hexdigest()

data = {c: load_case(ROOT/'问题2数据.xlsx', c) for c in (1, 2)}
audits = []
schedule_refs = {
    '当前方案10873': (2, 'problem2/results/reproduce_10890/multiple_seeds_run01/seed23/final/result.json'),
    '历史最好10702': (2, 'problem2/results/overnight_windows/run01/width9/seed23/best/result.json'),
    'Case1最优5031': (1, 'problem2/results/exact_case1/run01/gurobi/result.json'),
}
for label, (case, rel) in schedule_refs.items():
    d = read(rel)
    v = validate_exact(data[case], d)
    assert evaluate(data[case], code_from_result(d, data[case].n)) == d['objective']
    write(f'数据/{label}_完整调度.json', d)
    rows = []
    for r in d['operations']:
        rows.append({'工件':f"J{r['job']+1}", '工位':r['station'], '机器':r['machine'],
                     '到达秒':r['arrival'], '换模开始秒':r['setup_start'], '换模结束秒':r['setup_finish'],
                     '加工开始秒':r['start'], '完成秒':r['finish']})
    table(f'数据/{label}_工序表.csv', rows)
    audits.append({'name':label, 'source':rel, 'validation':v, 'encoding_recalculated':True})

table('数据/展示数据.csv', [
    {'结果':'Case1完整精确模型','工件数':7,'目标秒':5031,'时间秒':59.83189989998937,'时间口径':'该次完整模型完整时间','证明范围':'full，已证明全局最优','主展示位置':'第7页小字或备查'},
    {'结果':'当前默认配置代表运行','工件数':35,'目标秒':10873,'时间秒':141.0955321000656,'时间口径':'含初始化的独立完整流程','证明范围':'restricted，可行，未证明全局最优','主展示位置':'第7页'},
    {'结果':'历史最好可行值','工件数':35,'目标秒':10702,'时间秒':25397.50210490008,'时间口径':'已有10952起点后的累计追加至首次找到，历史准备另计','证明范围':'restricted，第109轮受限最优，未证明原题最优','主展示位置':'第8页'},
])

prefix = 'problem2/results/reproduce_10890/multiple_seeds_run01/seed23/'
summary = read(prefix+'summary.json')
config = read(prefix+'config.json')
history = read(prefix+'history.json')
assert (summary['initial'],summary['annealing'],summary['final']) == (11086,10952,10873)
assert config['solver_seconds']==110 and config['max_rounds']==80 and config['range_cache'] is False
write('证据/当前方案运行摘要.json', {k:v for k,v in summary.items() if k not in ('refinement','improvements')})
write('证据/当前方案参数.json', {k:config[k] for k in ('case','seed','seconds','annealing_seconds','solver_seconds','per_round','max_rounds','width','threads','batch_descent','range_cache','uses_saved_reference','includes_initialization','search','scope')})
events = [{'阶段':r['phase'], '事件':r['event'], '累计运行秒':r['elapsed_seconds'], '最好目标秒':r['global_best']} for r in history['events']]
table('数据/当前方案10873_改善曲线.csv',events)
table('数据/当前方案10873_阶段结果.csv',[
    {'阶段':'初始化完成','目标秒':summary['initial'],'阶段实际秒':summary['initialization_seconds']},
    {'阶段':'退火完成','目标秒':summary['annealing'],'阶段实际秒':summary['annealing_seconds']},
    {'阶段':'最终区间搜索完成','目标秒':summary['final'],'阶段实际秒':summary['refinement']['seconds']},
])
rep=[]
for seed in (11,23,37):
    rel=f'problem2/results/reproduce_10890/multiple_seeds_run01/seed{seed}/summary.json'
    d=read(rel)
    rep.append({'种子':seed,'初始化目标秒':d['initial'],'退火目标秒':d['annealing'],'最终目标秒':d['final'],
                '完整实际运行秒':d['total_seconds'],'证明范围':'restricted','来源':rel})
table('数据/当前配置三个种子.csv',rep)

night='problem2/results/overnight_windows/run01/width9/seed23/'
cp=read(night+'checkpoint.json')
p=ROOT/(night+'rounds.jsonl');excerpt(night+'rounds.jsonl')
rounds=[json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s]
first=next(r for r in rounds if r['after']==10702)
assert first['round']==109 and first['before']==10711 and cp['status']=='stopped_by_user'
rr=read(night+'round000109/result.json')
write('证据/10702来源摘要.json',{'seed':23,'width':9,'threads':cp['threads'],'initial_objective':cp['initial_objective'],
    'first_10702':first,'stopped_elapsed_seconds':cp['elapsed_seconds'],'status':cp['status'],
    'completed_rounds':cp['completed_rounds'],'final_reference_checked_pairs':len(cp['checked_pairs']),
    'final_reference_pairs_required':cp['pairs_required'],'whole_width9_neighborhood_completed':False,
    'scope':'restricted','original_optimality_proven':False,
    'round109_proof':{k:rr['proof'][k] for k in ('scope','optimal','runtime','bound','gap','model_sha256','threads')},
    'time_excludes_historical_preparation':True,'concurrent_width_runs_not_fair_speed_comparison':True})
best=cp['initial_objective']; trace=[{'轮次':0,'累计追加秒':0,'最好目标秒':best}]
for r in rounds:
    if r['after']<best:
        best=r['after'];trace.append({'轮次':r['round'],'累计追加秒':r['elapsed_seconds'],'最好目标秒':best})
table('数据/10702_改善节点.csv',trace)

full=read('problem2/results/sa_start_full/run01/summary.json')
table('数据/完整模型180秒诊断.csv',[{'种子':r['seed'],'初始秒':r['initial'],'最终秒':r['final'],
       '实际求解秒':r['solver_seconds'],'全局下界秒':r['global_bound'],'gap':r['gap'],'状态':r['status'],'scope':'full'} for r in full['records']])
abl=read('problem2/results/annealing_ablation/run01/summary.json')
table('数据/是否保留退火_三种子.csv',[{'种子':r['seed'],'方法':r['method'],'初始秒':r['initial'],
    '进入求解器目标秒':r['solver_start_objective'],'最终秒':r['final'],'追加实际秒':r['additional_seconds'],
    '含初始化实际秒':r['full_seconds_including_initialization']} for r in abl['runs']])

interval=read('problem2/results/interval_width_time/run01/report_summary.json')
assert interval['complete'] and len(interval['runs'])==56
table('数据/宽度时间实验_56组.csv',[{k:r[k] for k in ('seed','method','width','per_round_seconds','adaptive_width','before','after','budget_seconds','additional_seconds','preparation_seconds','round_count','total_seconds_including_preparation','scope')} for r in interval['runs']])
comparisons=interval['analysis']['comparisons_to_adaptive_baseline']
rows=[]
for method in ['w5_t5','w5_t15','w5_t60','w7_t5','w7_t15','w7_t60','adaptive5_t5']:
    group=[r for r in interval['runs'] if r['method']==method]
    assert len(group)==8
    row={'组别':method,'种子数':8,'平均最终目标秒':sum(r['after'] for r in group)/8,
         '对基线平均差秒':0,'胜':0,'平':8,'负':0,'Holm校正p':1.0}
    if method!='adaptive5_t5':
        c=next(c for c in comparisons if c['method']==method)
        row.update({'对基线平均差秒':c['mean_seconds'],'胜':c['wins'],'平':c['ties'],'负':c['losses'],'Holm校正p':c['holm_adjusted_p']})
    rows.append(row)
table('数据/宽度时间实验_七组汇总.csv',rows)
write('证据/宽度时间分析摘要.json',{'groups':rows,'factor_contrasts':interval['analysis']['factor_contrasts'],
    'costs':interval['costs'],'verification':interval['verification'],'scope':'restricted',
    'fixed_width5_three_limits_same_final_per_seed':all(len({r['after'] for r in interval['runs'] if r['seed']==seed and r['width']==5 and not r['adaptive_width']})==1 for seed in interval['analysis']['complete_seeds'])})
for rel in ['problem2/results/sa_information_doe/run02/restriction_comparison.json',
            'problem2/results/sa_information_doe/run02/factorial_analysis.json']:
    d=read(rel)
    # Keep compact, self-contained evidence; these files contain aggregate statistics only.
    write('证据/'+Path(rel).name,d)

for rel in ['problem2/docs/算法设计.md','problem2/docs/实验记录索引.md',
            '问题2.pdf','问题2数据.xlsx',
            'problem2/results/abc_comparison/run01/实验记录.md',
            'problem2/results/stage1_budget_probe/run01/实验记录.md',
            'problem2/results/annealing_ablation/run01/实验记录.md',
            'problem2/results/interval_width_time/run01/实验记录.md',
            'problem2/results/sa_information_doe/run02/实验记录.md',
            'problem2/results/sa_start_full/run01/实验记录.md',
            'problem2/results/overnight_windows/run01/实验记录.md',
            'problem2/stage1/main.py','problem2/stage1/construction.py','problem2/stage1/annealing.py',
            'problem2/stage1/neighborhoods.py','problem2/stage1/windows.py','problem2/common/encoding.py',
            'problem2/common/local_search.py','problem2/common/validation.py','problem2/stage2/joint_search.py']:
    if (ROOT/rel).exists():excerpt(rel)
write('证据/来源SHA256.json',sources)
write('证据/完整调度复核.json',{'new_searches':0,'new_solver_calls':0,'schedules':audits,'total_operations':sum(x['validation']['operations'] for x in audits)})
print('数据摘录完成，独立验证',sum(x['validation']['operations'] for x in audits),'道工序；没有求解或搜索')
