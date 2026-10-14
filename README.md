# 工业工程综合实验：题目2

本项目用Python求解带两台并行机和序列相关换模时间的十工位流水车间调度问题。Case 1有7个工件，Case 2有35个工件；目标是最小化全部工件在工位10的最终完成时间，并输出完整调度供复核。

本仓库保留源码、测试、文字文档，以及筛选后的实验报告、汇总、运行参数、历史轨迹和曲线。课程原题、Excel输入、逐轮模型及求解器许可证不随仓库上传，运行输入由使用者自行准备。

## 算法流程

一阶段从原始Excel出发，执行“多次贪心构造与完整局部下降 → 模拟退火 → Gurobi区间重排”，得到完整可行调度。精确阶段每轮只放开前后段各一段连续工件和相关机器归属，固定其余关系，求解后再选择其他区间。

二阶段读取一阶段的完整结果，选择少量工件联合重排，并有限次调用Gurobi允许这些工件跨位置插入；可选扰动后继续搜索。二阶段仍在研究，不保证每次都改善。

两阶段共用三数组编码：前段排列、工位6完工全序、按工件编号的机器归属。解码完整计算十工位的加工、换模、排队和必要等待。详见[算法设计](problem2/docs/算法设计.md)和[运行说明](problem2/README.md)。

## 快速上手

在项目根目录执行以下命令。代码使用Python 3.10及以上语法，本机已验证的环境为Python 3.14；求解器接口还须与所用Python环境兼容。

### 1. 准备课程输入

自行取得以下两个原始文件，放到与本README同一级的目录：

```text
项目根目录/
├── 问题2.pdf
├── 问题2数据.xlsx
└── problem2/
```

Excel必须保留原始“表2”“表4”及其布局。PDF是题意依据，运行入口还会读取它计算输入哈希，因此不能只放Excel。程序只读这些文件，不修改原始输入。

### 2. 安装依赖

```powershell
python -m pip install -r problem2/requirements.txt
python -m pip install gurobipy
```

Gurobi的Python包与有效许可证都需要准备。基础依赖文件只包含openpyxl和NumPy；COPT仅用于Case 1精确复核，按需安装 `coptpy`，同样需要有效许可证。许可证留在各自本机，不放入仓库。

### 3. 运行一阶段

```powershell
python -B -m problem2.stage1.main --case 1 --seed 11 --seconds 600 --output problem2/results/case1_run01
python -B -m problem2.stage1.main --case 2 --seed 2026101114 --seconds 600 --output problem2/results/case2_run01
```

每次使用新的输出目录；入口拒绝覆盖已有目录。默认退火最多90秒、精确阶段最多110秒且最多80轮，总预算600秒包含初始化。600秒是上限，不表示每次都会用满；建模和导出等操作可能造成少量超时，查看真实用时。

没有Gurobi时，可加入 `--max-rounds 0` 仅运行贪心、下降和退火。这会跳过精确阶段，结果不能当作完整混合流程的性能。

### 4. 从结果继续运行二阶段

```powershell
python -B -m problem2.stage2.main --case 2 --reference problem2/results/case2_run01/final/result.json --seconds 600 --explore --output problem2/results/case2_stage2_run01
```

这里的600秒是追加预算，不包含参考解的历史计算成本。输出的 `final/result.json`、`final/schedule.csv` 和 `final/gantt.svg` 分别保存完整调度、工序时间表和甘特图。

## 当前状态（2026-10-14）

| 项目 | 已完成的结果 | 说明 |
| --- | --- | --- |
| Case 1完整精确模型 | 最优值5031秒 | Gurobi和COPT均验证全局最优；COPT使用Gurobi可行解作为初始解 |
| 一阶段独立运行 | 历史种子2026101114复现10890秒 | 当次首次发现37.41秒，完整流程141.12秒；其他种子及运行条件可能不同 |
| Case 2历史最好可行调度 | 10702秒 | 来自不限时宽度9追加求解，首次找到约7小时3分钟；未证明全局最优，不是默认600秒结果 |
| 二阶段联合重排 | 历史从10890改善到10847秒 | 成组枚举、局部Gurobi及扰动的组合；稳定性仍需测试 |
| 利用退火记录缩小约束 | 已完成对照实验 | 未证明优于现有区间限制；自动固定机器出现排除更好编码的反例 |
| 候选前驱、后继集合 | 本机独立接口及32组合全因子试验已完成 | 未显示整体收益；部分受限最优值比原区间已有可行值更差，当前规则不采用 |
| 当前研究主线 | 区间搜索 | 研究宽度、区间选择及时间分配；没有启动新实验 |

历史结果的完整证据保存在本机 `problem2/results/`；仓库只包含筛选后的报告和过程记录，以及Case 1、Case 2最好结果各一份完整调度。逐轮模型和大部分逐轮调度不包含在仓库内。文档中的历史结果用于说明已有研究，不承诺相同种子在不同机器、时限或求解器版本下返回相同调度。受限模型达到OPTIMAL只证明本轮附加条件下最优。

## 当前研究方向

当前研究主线为区间搜索：重点比较区间宽度、区间选择和单轮时间分配，在相同完整预算下评价改善幅度与多种子稳定性。当前退火候选相邻约束未显示整体优势，且存在限制后最优值更差的固定范围，不加入正式默认流程。退火信息可作为区间选择的研究输入，但收益须单独验证。尚未安排新的求解任务。

五类退火信息的主效应与交互作用见[全因子报告](problem2/results/sa_information_doe/run02/实验记录.md)及[因子分析](problem2/results/sa_information_doe/run02/factorial_analysis.json)。24个固定范围共816模型；所有主效应的探索性区间包含0，未完成独立新种子确认，不能将信息本身判为普遍有效或无效。部分候选模型已求到受限最优，仍差于原区间已有可行值；这证明当前附加限制在这些范围内排除了达到该更好值的全部方案，详见[范围对照](problem2/results/sa_information_doe/run02/restriction_comparison.json)。

本次文档提交同步研究结论和精简分析证据。新增退火记录、候选约束实验模块及对应测试仍保留在本机，未随本次提交上传；文档中的相关入口、149项测试及68个模型门禁是本机已完成实验的记录，不表示公开仓库当前源码已包含全部实验接口。

## 收录的实验记录

`problem2/results/`采用允许文件清单：实验报告Markdown、`summary.json`、`config.json`、`*history*.json`、`events.jsonl`、`rounds.jsonl`、过程及对照CSV，以及5张下降或温度曲线。历史源码快照、逐轮MPS、解文件、求解日志、其他甘特图和时间表均不收录。一般规则见[.gitignore](.gitignore)；本次另明确收录全因子试验的`report_summary.json`、`factorial_analysis.json`、三个独立核验JSON、`restriction_comparison.json`及`task_completion.json`，其余模型、完整调度和记录仍留在本机。

以下两份调度各保留`result.json`、`schedule.csv`和`gantt.svg`：

- [Case 1的5031秒调度](problem2/results/exact_case1/run01/gurobi/result.json)。
- [Case 2的10702秒调度](problem2/results/overnight_windows/run01/width9/seed23/best/result.json)。

它们便于查看和核对工序安排，但独立复核仍需原始Excel。原MPS未收录，仓库不能单独重放全部历史最优证明。

## 代码和文档

| 路径 | 内容 |
| --- | --- |
| [problem2/common](problem2/common) | 数据、编码解码、评分、精确模型、验证及导出 |
| [problem2/stage1](problem2/stage1) | 构造、局部下降、退火、区间求解及正式一阶段入口 |
| [problem2/stage2](problem2/stage2) | 联合重排、扰动和并行多起点研究 |
| [problem2/tests](problem2/tests) | 单元测试；集成对照以小实例穷举核验求解器 |
| [problem2/experiments](problem2/experiments) | 历史方法和独立对照入口 |
| [文档索引](problem2/docs/README.md) | 推荐阅读顺序与实验说明分类 |

想快速读懂代码，先看运行说明，再沿 `stage1/main.py → common/encoding.py → stage1/windows.py → common/solver.py` 阅读。用AI辅助时可以让它沿这个调用顺序解释编码、时间递推、每轮固定条件，并核对算法设计文档；不要只让它总结所有历史文件。

## 验证

只使用人工小实例、无需课程数据和求解器的基础检查：

```powershell
python -B -m unittest problem2.tests.test_exact_case1 problem2.tests.test_batch
```

准备课程输入后运行完整单元测试：

```powershell
python -B -m unittest discover -s problem2/tests -t .
```

需要实际调用Gurobi的小实例穷举对照，另见[运行说明](problem2/README.md)。本项目不默认启动Case 2完整精确模型；日常入口使用受限模型。
