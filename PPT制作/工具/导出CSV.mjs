// 使用Node从已有JSON生成PPT表格，不读取旧CSV，不运行搜索或求解器。
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const output=path.join(root,'PPT制作/数据/Node导出');
assert(!fs.existsSync(output),'输出目录已存在，请另存已有产物后再运行，禁止覆盖。');
assert(process.env.CODEX_NODE_MODULES,'请将CODEX_NODE_MODULES设为已有工作区运行库目录。');
const entry=createRequire(import.meta.url).resolve('@oai/artifact-tool',{paths:[process.env.CODEX_NODE_MODULES]});
const {Workbook}=await import(pathToFileURL(entry).href);
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const sources={};
function read(rel){
  assert(/\.jsonl?$/.test(rel),'只读取已有JSON或JSONL');
  const b=fs.readFileSync(path.join(root,rel));
  assert(!b.subarray(0,16).toString('ascii').startsWith('%TSD-Header-###%'),'输入不是可读JSON：'+rel);
  sources[rel]=sha(b);
  const text=b.toString('utf8').replace(/^\uFEFF/,'');
  return rel.endsWith('.jsonl')?text.trim().split(/\r?\n/).map(s=>JSON.parse(s)):JSON.parse(text);
}
const tables=[];
function table(name,rows){assert(rows.length);tables.push({name:name+'.csv',rows});}
const schedules=[['当前方案10873',350],['历史最好10702',350],['Case1最优5031',70]];
for(const [label,count] of schedules){
  const d=read(`PPT制作/数据/${label}_完整调度.json`);
  assert.equal(d.operations.length,count);assert.equal(d.validation.valid,true);
  table(label+'_工序表',d.operations.map(r=>({'工件':`J${r.job+1}`,'工位':r.station,'机器':r.machine,
    '到达秒':r.arrival,'换模开始秒':r.setup_start,'换模结束秒':r.setup_finish,'加工开始秒':r.start,'完成秒':r.finish})));
}
const prefix='problem2/results/reproduce_10890/multiple_seeds_run01/seed23/';
const summary=read(prefix+'summary.json');
assert.deepEqual([summary.initial,summary.annealing,summary.final],[11086,10952,10873]);
const night='problem2/results/overnight_windows/run01/width9/seed23/';
const checkpoint=read(night+'checkpoint.json');const rounds=read(night+'rounds.jsonl');
const first=rounds.find(r=>r.after===10702);assert.equal(first.round,109);assert.equal(first.before,10711);
const case1=read('PPT制作/数据/Case1最优5031_完整调度.json');
table('展示数据',[
  {'结果':'Case1完整精确模型','工件数':7,'目标秒':5031,'时间秒':case1.proof.total_seconds,'时间口径':'该次完整模型完整时间','证明范围':'full，已证明全局最优','主展示位置':'第7页小字或备查'},
  {'结果':'当前默认配置代表运行','工件数':35,'目标秒':summary.final,'时间秒':summary.total_seconds,'时间口径':'含初始化的独立完整流程','证明范围':'restricted，可行，未证明全局最优','主展示位置':'第7页'},
  {'结果':'历史最好可行值','工件数':35,'目标秒':10702,'时间秒':first.elapsed_seconds,'时间口径':'已有10952起点后的累计追加至首次找到，历史准备另计','证明范围':'restricted，第109轮受限最优，未证明原题最优','主展示位置':'第8页'},
]);
const history=read(prefix+'history.json');
table('当前方案10873_改善曲线',history.events.map(r=>({'阶段':r.phase,'事件':r.event,'累计运行秒':r.elapsed_seconds,'最好目标秒':r.global_best})));
table('当前方案10873_阶段结果',[
  {'阶段':'初始化完成','目标秒':summary.initial,'阶段实际秒':summary.initialization_seconds},
  {'阶段':'退火完成','目标秒':summary.annealing,'阶段实际秒':summary.annealing_seconds},
  {'阶段':'最终区间搜索完成','目标秒':summary.final,'阶段实际秒':summary.refinement.seconds},
]);
table('当前配置三个种子',[11,23,37].map(seed=>{
  const rel=`problem2/results/reproduce_10890/multiple_seeds_run01/seed${seed}/summary.json`;const d=read(rel);
  return {'种子':seed,'初始化目标秒':d.initial,'退火目标秒':d.annealing,'最终目标秒':d.final,'完整实际运行秒':d.total_seconds,'证明范围':'restricted','来源':rel};
}));
let best=checkpoint.initial_objective;const trace=[{'轮次':0,'累计追加秒':0,'最好目标秒':best}];
for(const r of rounds){if(r.after<best){best=r.after;trace.push({'轮次':r.round,'累计追加秒':r.elapsed_seconds,'最好目标秒':best});}}
table('10702_改善节点',trace);
const full=read('problem2/results/sa_start_full/run01/summary.json');
table('完整模型180秒诊断',full.records.map(r=>({'种子':r.seed,'初始秒':r.initial,'最终秒':r.final,'实际求解秒':r.solver_seconds,'全局下界秒':r.global_bound,'gap':r.gap,'状态':r.status,'scope':'full'})));
const ablation=read('problem2/results/annealing_ablation/run01/summary.json');
table('是否保留退火_三种子',ablation.runs.map(r=>({'种子':r.seed,'方法':r.method,'初始秒':r.initial,'进入求解器目标秒':r.solver_start_objective,'最终秒':r.final,'追加实际秒':r.additional_seconds,'含初始化实际秒':r.full_seconds_including_initialization})));
const interval=read('problem2/results/interval_width_time/run01/report_summary.json');
assert(interval.complete);assert.equal(interval.runs.length,56);
const keys=['seed','method','width','per_round_seconds','adaptive_width','before','after','budget_seconds','additional_seconds','preparation_seconds','round_count','total_seconds_including_preparation','scope'];
table('宽度时间实验_56组',interval.runs.map(r=>Object.fromEntries(keys.map(k=>[k,r[k]]))));
table('宽度时间实验_七组汇总',['w5_t5','w5_t15','w5_t60','w7_t5','w7_t15','w7_t60','adaptive5_t5'].map(method=>{
  const group=interval.runs.filter(r=>r.method===method);assert.equal(group.length,8);
  const c=interval.analysis.comparisons_to_adaptive_baseline.find(c=>c.method===method);
  return {'组别':method,'种子数':8,'平均最终目标秒':group.reduce((a,r)=>a+r.after,0)/8,
    '对基线平均差秒':c?.mean_seconds??0,'胜':c?.wins??0,'平':c?.ties??8,'负':c?.losses??0,'Holm校正p':c?.holm_adjusted_p??1};
}));
assert.equal(tables.length,12);
const workbook=Workbook.create();
for(const t of tables){
  t.headers=Object.keys(t.rows[0]);t.matrix=[t.headers,...t.rows.map(r=>t.headers.map(k=>r[k]))];
  for(const row of t.matrix)for(const value of row)assert(value!==undefined && (typeof value!=='number'||Number.isFinite(value)));
  t.sheet=workbook.worksheets.add(t.name.slice(0,-4));
  t.range=t.sheet.getRangeByIndexes(0,0,t.matrix.length,t.headers.length);t.range.values=t.matrix;
}
workbook.recalculate();
for(const t of tables)assert.deepEqual(t.range.values,t.matrix,'表格数据回读不一致：'+t.name);
await workbook.inspect({kind:'table',range:"'展示数据'!A1:G4",include:'values',tableMaxRows:4,tableMaxCols:7,maxChars:2000});
// CSV保持原表的单行列名和原始数值，不附加工作簿样式或公式。
function value(v){if(typeof v==='boolean')return v?'True':'False';return String(v);}
function field(v){const s=value(v);return /[",\r\n]/.test(s)?'"'+s.replaceAll('"','""')+'"':s;}
fs.mkdirSync(output,{recursive:false});
const files=[];
for(const t of tables){
  const bytes=Buffer.from('\uFEFF'+t.range.values.map(row=>row.map(field).join(',')).join('\r\n')+'\r\n','utf8');
  fs.writeFileSync(path.join(output,t.name),bytes,{flag:'wx'});
  const actual=fs.readFileSync(path.join(output,t.name));
  assert(!actual.subarray(0,16).toString('ascii').startsWith('%TSD-Header-###%'),'输出受到自动保护，停止：'+t.name);
  assert.deepEqual(actual,bytes,'Node回读不一致：'+t.name);
  files.push({name:t.name,rows:t.rows.length,columns:t.headers.length,headers:t.headers,sha256:sha(bytes),bytes:bytes.length});
}
const metadata={writer:'Node.js',node_version:process.version,encoding:'UTF-8 BOM',line_ending:'CRLF',
  source_sha256:sources,files,new_searches:0,new_solver_calls:0,old_csv_read:false,old_csv_overwritten:false,git_commit_or_push:false,
  artifact_table_values_reconciled:true,independent_readback:'pending'};
fs.writeFileSync(path.join(output,'导出记录.json'),JSON.stringify(metadata,null,2)+'\n',{encoding:'utf8',flag:'wx'});
console.log(JSON.stringify({csv_files:files.length,total_data_rows:files.reduce((n,f)=>n+f.rows,0),sources:Object.keys(sources).length,output:path.relative(root,output)}));
