"""根据已核验数据生成可编辑SVG图表和算法示意；不运行搜索。"""
from pathlib import Path
import csv
import html
import json
import math
import colorsys

OUT=Path(__file__).resolve().parents[1]
IMG=OUT/'图片'
NAVY='#16324f'; BLUE='#2369a8'; TEAL='#087f8c'; ORANGE='#bd5a14'; GRAY='#66717e'; LIGHT='#edf3f8'
def esc(s):return html.escape(str(s))
class SVG:
    def __init__(self,title,sub='',width=1600,height=900):
        self.w,self.h=width,height
        self.parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/><g font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif" fill="{NAVY}">']
        self.text(65,67,title,36,bold=True)
        if sub:self.text(65,111,sub,23,color=GRAY)
    def text(self,x,y,s,size=26,color=NAVY,anchor='start',bold=False):
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}"'+(' font-weight="700"' if bold else '')+f'>{esc(s)}</text>')
    def rect(self,x,y,w,h,fill=LIGHT,stroke='none',sw=1):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    def line(self,x,y,x2,y2,color=GRAY,sw=2,dash=None):
        self.parts.append(f'<line x1="{x}" y1="{y}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"'+(f' stroke-dasharray="{dash}"' if dash else '')+'/>')
    def arrow(self,x,y,x2,y2,color=BLUE):
        self.line(x,y,x2,y2,color,3)
        a=math.atan2(y2-y,x2-x)
        pts=[(x2,y2),(x2-14*math.cos(a-.45),y2-14*math.sin(a-.45)),(x2-14*math.cos(a+.45),y2-14*math.sin(a+.45))]
        self.parts.append('<polygon points="'+' '.join(f'{px},{py}' for px,py in pts)+f'" fill="{color}"/>')
    def save(self,name):
        (IMG/(name+'.svg')).write_text(''.join(self.parts)+'</g></svg>',encoding='utf-8')
def load(rel):return json.loads((OUT/rel).read_text(encoding='utf-8'))
def csvrows(rel):return list(csv.DictReader((OUT/rel).open(encoding='utf-8-sig')))
def sequence(g,label,seq,x,y,selected=(),cell=120):
    g.text(65,y+42,label,27,bold=True)
    for i,j in enumerate(seq):
        active=i in selected
        g.rect(x+i*cell,y,cell-8,62,'#dcedf9' if active else '#f1f3f5',BLUE if active else '#b8c1cb',2)
        g.text(x+i*cell+(cell-8)/2,y+41,str(j),27,anchor='middle')

# The encoding illustration uses a real seven-job schedule, displayed with one-based IDs.
case=load('数据/Case1最优5031_完整调度.json');q=case['queues']
g=SVG('三数组编码与完整解码','示意采用Case 1已验证编码，工件编号从J1开始显示')
sequence(g,'A：工位1～5',[f'J{j+1}' for j in q['A']],400,165,cell=145)
sequence(g,'B：工位6完工全序',[f'J{j+1}' for j in q['B']],400,270,cell=145)
sequence(g,'机器：按工件编号',['6-1' if j in q['6-1'] else '6-2' for j in range(7)],400,375,cell=145)
for i in range(7):g.text(400+i*145+68,365,f'J{i+1}',20,anchor='middle',color=GRAY)
g.text(65,518,'按B与机器归属筛选队列',28,bold=True)
g.text(450,518,'6-1：'+'、'.join(f'J{j+1}' for j in q['6-1']),27)
g.text(450,566,'6-2：'+'、'.join(f'J{j+1}' for j in q['6-2']),27)
g.text(65,656,'非首件：S ≥ max（前驱完成，本件到达）＋方向换模时间',31,bold=True)
g.text(65,716,'工位6必要时继续等待，使实际完工顺序符合B；工位7～10沿用B',27)
g.text(65,774,'评分始终计算全部10道工序；目标为最后一个工件在工位10的完成时间',26)
g.text(65,838,'每条队列首件换模为0；6-2加工时长采用整数四舍五入',22,color=GRAY)
g.save('01_编码与解码')

g=SVG('正式算法总体流程','从原始数据独立运行，最终输出完整调度与验证结果')
items=[('多次构造与局部下降','8次构造，五种邻域完整下降','保留最好完整编码'),('模拟退火','随机移动与概率接受','保留搜索中最好编码'),('Gurobi区间搜索','A、B各放开一个连续区间','严格改善才更新参考解'),('完整核验与导出','核查全部工序和工位6完工顺序','输出目标、甘特图与工序表')]
for i,(a,b,c) in enumerate(items):
    x=65+i*385;g.rect(x,240,325,240,'white',BLUE,2);g.text(x+20,290,a,27,bold=True);g.text(x+20,349,b,21);g.text(x+20,405,c,21)
    if i<3:g.arrow(x+330,360,x+375,360)
g.line(1015,485,1015,564,BLUE,3);g.line(1015,564,925,564,BLUE,3);g.arrow(925,564,925,485)
g.text(740,618,'区间未结束时继续选择范围',25,color=BLUE)
g.text(65,710,'预算上限：总600秒，退火90秒，精确阶段110秒／80轮',29,bold=True)
g.text(65,766,'实际运行可提前结束；区间初始宽5，每轮最多5秒，8线程',26)
g.text(65,836,'stage2保留为未来研究，未接入本页正式流程',23,color=GRAY)
g.save('02_算法总体流程')

g=SVG('模拟退火的移动与接受','当前编码与搜索中最好编码分别保存')
sequence(g,'当前A',['J1','J2','J3','J4','J5','J6','J7'],400,180,cell=145)
sequence(g,'插入后的A',['J1','J4','J2','J3','J5','J6','J7'],400,285,selected=(1,2,3),cell=145)
g.text(65,440,'五种移动',29,bold=True)
g.text(380,440,'A插入、B插入、单工件换机、A交换、B交换',28)
g.text(65,525,'完整评分',29,bold=True);g.text(380,525,'Δ = 候选最终完成时间 − 当前最终完成时间',28)
g.text(65,610,'接受规则',29,bold=True);g.text(380,610,'Δ ≤ 0直接接受；Δ > 0以 exp(−Δ / T) 概率接受',28)
g.text(65,695,'温度更新',29,bold=True);g.text(380,695,'每层1000次移动后 T ← 0.97T',28)
g.text(65,792,'较差候选可暂时成为当前解，输出始终保留已找到的最好解',27,color=TEAL)
g.save('03_退火移动与接受')

g=SVG('Gurobi区间重排的范围','用宽3说明位置限制，正式初始宽度为5；A、B可以选择不同位置')
sequence(g,'参考A',['J1','J2','J3','J4','J5','J6','J7'],400,170,selected=(2,3,4),cell=145)
sequence(g,'参考B',['J2','J1','J4','J3','J6','J5','J7'],400,275,selected=(2,3,4),cell=145)
g.arrow(940,355,940,430)
sequence(g,'允许的新A',['J1','J2','J5','J3','J4','J6','J7'],400,460,selected=(2,3,4),cell=145)
sequence(g,'允许的新B',['J2','J1','J6','J4','J3','J5','J7'],400,565,selected=(2,3,4),cell=145)
g.text(65,716,'A内只重排J3、J4、J5；B内只重排J4、J3、J6，工件不能移出各自区间',25)
g.text(65,765,'两个区间工件的并集J3、J4、J5、J6可换机；其他工件机器归属固定',25)
g.text(65,833,'时间仍允许等待，全部工序保留；本轮受限最优不能证明原题全局最优',23,color=GRAY)
g.save('04_区间调整示意')

rows=csvrows('数据/宽度时间实验_七组汇总.csv')
g=SVG('区间宽度与单轮时间对照','8个新种子，每组追加预算180秒；正差表示最终完成时间比自适应基线更长')
x0=360;scale=19
for i,r in enumerate(rows[:-1]):
    y=210+i*79;v=float(r['对基线平均差秒']);g.text(65,y+27,r['组别'],28)
    g.rect(x0+min(0,v)*scale,y,max(abs(v)*scale,2),40,ORANGE if v>0 else TEAL)
    g.text(x0+max(v,0)*scale+20,y+29,f'{v:+.2f}秒',26,color=ORANGE if v>0 else TEAL)
    g.text(1390,y+27,f"{r['胜']}/{r['平']}/{r['负']}",25)
g.line(x0,170,x0,690,NAVY,2);g.text(1360,166,'胜／平／负',23)
for t in (0,10,20,30,40,50):g.text(x0+t*scale,725,t,23,anchor='middle')
g.text(65,795,'宽5三个时限逐种子同值；固定宽5对基线2胜4平2负',27)
g.text(65,846,'预定义Holm校正后均未显著，不能写成“延长时间无效”或“自适应已证明最好”',23,color=GRAY)
g.save('05_宽度时间对照')

def trajectory(name,title,sub,rows,tx,ty,maxx,miny,maxy,xlabel,marks=()):
    g=SVG(title,sub);left,top,w,h=160,180,1320,500
    def px(x):return left+x/maxx*w
    def py(y):return top+h-(y-miny)/(maxy-miny)*h
    for v in range(int(math.ceil(miny/50))*50,int(maxy)+1,50):
        y=py(v);g.line(left,y,left+w,y,'#dfe5eb',1);g.text(left-20,y+8,v,23,anchor='end')
    for x in tx:g.text(px(x),top+h+43,round(x,1),23,anchor='middle')
    pts=[];last=None
    for x,y in rows:
        if last is not None:pts.append((px(x),py(last)))
        pts.append((px(x),py(y)));last=y
    g.parts.append('<polyline points="'+' '.join(f'{x:.2f},{y:.2f}' for x,y in pts)+f'" fill="none" stroke="{BLUE}" stroke-width="5"/>')
    g.line(left,top+h,left+w,top+h,NAVY,2);g.text(820,top+h+90,xlabel,26,anchor='middle')
    g.text(65,155,'目标／秒',24)
    for x,y,label,dx,dy in marks:
        g.parts.append(f'<circle cx="{px(x)}" cy="{py(y)}" r="7" fill="{TEAL}"/>');g.text(px(x)+dx,py(y)+dy,label,26,color=TEAL)
    g.text(65,850,ty,23,color=GRAY);g.save(name)
hist=csvrows('数据/当前方案10873_改善曲线.csv')
s=load('证据/当前方案运行摘要.json')
curve=[(float(r['累计运行秒']),float(r['最好目标秒'])) for r in hist]
ends=[r for r in hist if r['事件']=='end' and r['阶段'] in ('initialization','annealing','final')]
trajectory('06_当前方案改善曲线','当前方案代表运行：11086降至10873','Case 2，种子23，同一次运行；横轴为包含初始化的真实运行时间',curve,[0,30,60,90,120,150],
           '完整实际耗时141.10秒；退火约24.53秒，预算上限不等于实际用满',150,10850,11120,'累计运行时间／秒',
           [(float(r['累计运行秒']),float(r['最好目标秒']),r['最好目标秒'],10,-20 if i!=1 else 35) for i,r in enumerate(ends)])
night=csvrows('数据/10702_改善节点.csv');cp=load('证据/10702来源摘要.json')
curve=[(float(r['累计追加秒'])/3600,float(r['最好目标秒'])) for r in night]
curve.append((cp['stopped_elapsed_seconds']/3600,10702))
trajectory('09_长时间搜索改善曲线','历史最好10702的发现过程','宽度9、种子23，从10952出发；历史准备时间不计入横轴',curve,[0,2,4,6,8],
           '第109轮首次得到10702，累计追加约7小时3分；停止时未完成宽9邻域检查',9,10680,10980,'累计追加时间／小时',
           [(cp['first_10702']['elapsed_seconds']/3600,10702,'10702：约7.05小时',-340,-25)])

COLORS=['#'+''.join(f'{round(c*255):02x}' for c in colorsys.hls_to_rgb((j*0.61803398875)%1,0.37,0.48)) for j in range(35)]
def gantt(label,name,m6=False):
    d=load(f'数据/{label}_完整调度.json');n=len(d['queues']['A']);obj=d['objective']
    g=SVG(f'{label}：'+('工位6两台机器' if m6 else '完整调度'),f'{n}个工件，最终完成时间{obj:g}秒；灰色为换模，白色为空闲或等待')
    machines=['6-1','6-2'] if m6 else ['1','2','3','4','5','6-1','6-2','7','8','9','10']
    left,top,w=130,178,1390;rh=180 if m6 else 42
    for i,m in enumerate(machines):
        y=top+i*rh;g.rect(left,y,w,rh-9,'#fafbfc');g.text(95,y+(rh-9)/2+7,m,24,anchor='end')
    for t in range(0,int(obj)+1,1000):
        x=left+t/obj*w;g.line(x,top-10,x,top+len(machines)*rh,'#dce3eb',1)
        if (obj-t)/obj*w >= 130:g.text(x,top+len(machines)*rh+35,t,21,anchor='middle')
    g.text(left+w,top+len(machines)*rh+35,f'{obj:g}',21,anchor='end',color=TEAL)
    for r in d['operations']:
        m=r['machine']
        if m not in machines:continue
        i=machines.index(m);y=top+i*rh;h=rh-10
        a,b,c=r['setup_start'],r['start'],r['finish'];x=left+b/obj*w;bw=(c-b)/obj*w
        if b>a:g.rect(left+a/obj*w,y,(b-a)/obj*w,h,'#bcc3cc')
        g.rect(x,y,bw,h,COLORS[r['job']%len(COLORS)],'white',.8)
        if bw>(42 if m6 else 32):g.text(x+bw/2,y+h/2+5,f"J{r['job']+1}",16 if not m6 else 21,color='white',anchor='middle')
    legend_y=top+len(machines)*rh+100
    for j in range(n):
        x=70+(j%12)*126;y=legend_y+(j//12)*43;g.rect(x,y-18,21,21,COLORS[j%len(COLORS)]);g.text(x+29,y,f'J{j+1}',20)
    g.text(65,862,'横轴单位：秒。较窄工序省略条内标签，完整数值和工件身份见配套工序表。',22,color=GRAY)
    g.save(name)
gantt('当前方案10873','07_当前方案10873_甘特图')
gantt('历史最好10702','08_历史最好10702_甘特图')
gantt('Case1最优5031','10_Case1最优5031_甘特图')
gantt('当前方案10873','11_当前方案10873_工位6详图',True)
gantt('历史最好10702','12_历史最好10702_工位6详图',True)

abl=csvrows('数据/是否保留退火_三种子.csv')
g=SVG('是否保留前置模拟退火','三个种子，同初始化起点；退火计入180秒追加预算，区间固定宽5')
for i,seed in enumerate((23,53,71)):
    x=260+i*490;g.text(x,210,f'种子{seed}',30,anchor='middle',bold=True)
    pair=[next(r for r in abl if int(r['种子'])==seed and r['方法']==method) for method in ('direct','annealing')]
    for j,r in enumerate(pair):
        val=float(r['最终秒']);y=310+j*145;g.text(x,y,'直接区间' if j==0 else '退火后区间',25,anchor='middle',color=GRAY)
        g.text(x,y+60,f'{val:g}',45,anchor='middle',color=BLUE if j==0 else TEAL,bold=True)
    diff=float(pair[1]['最终秒'])-float(pair[0]['最终秒'])
    g.text(x,655,'退火组'+('更好' if diff<0 else '更差' if diff>0 else '同值'),30,anchor='middle',color=TEAL if diff<0 else ORANGE if diff>0 else GRAY)
g.text(65,772,'退火有利、直接求解有利、最终同值各一组',30,bold=True)
g.text(65,835,'保留退火是当前选择；三组结果不能证明退火必需，也不能证明可以普遍删除',24,color=GRAY)
g.save('13_退火消融对照_备查')
print('已生成',len(list(IMG.glob('*.svg'))),'份SVG图源')
