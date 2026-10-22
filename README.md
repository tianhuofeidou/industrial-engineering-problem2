# 工业工程综合实验：题目2

2026-10-22结果与状态更新（仅本地）：项目已验证最好可行解为**[10454](problem2/results/stage2_overnight_hybrid/run01/final/result.json)**，来自十小时夜间二阶段混合搜索，350工序独立核验通过，全部Gurobi范围受限，不构成原题全局最优证明；一阶段从原始数据的最好结果为**[10592](problem2/results/stage1_sa_allocation/run01/main/final/result.json)**（1200秒、种子2026102101、退火480秒配置）。历史10702、10873等数字各自对应当时配置与预算，不是算法能力上限。详见[一阶段退火分配](problem2/results/stage1_sa_allocation/run02/实验记录.md)与[夜间二阶段](problem2/results/stage2_overnight_hybrid/run01/实验记录.md)。

2026-10-21双工件短对照补充（仅本地，未提交）：从10650出发原搜索/双工件为10628/10650，从10628出发为10628/10627；同种子23、每份180秒，两个相关起点不算独立多实例。本批最好10627，达到低于10628的本轮目标，不证明稳定胜出或全局最优。 见[完整报告](problem2/results/pair_quality/run01/实验记录.md)与[二阶段入口说明](problem2/stage2/README.md)。原正式默认保持原样。


2026-10-21质量研究补充（仅本地，未提交）：从已有10650追加搜索已得到并独立验证[10628完整调度](problem2/results/iterated_quality/run02/seed23/final/result.json)。[本轮报告](problem2/results/iterated_quality/run02/实验记录.md)区分三个固定种子与修复回归；它不是正式默认600秒流程结果，也没有全局最优证明。


本项目用Python求解带两台并行机和序列相关换模时间的十工位流水车间调度问题。Case 1有7个工件，Case 2有35个工件；目标是最小化全部工件在工位10的最终完成时间，并输出完整调度供复核。

本仓库保留源码、测试、文字文档，以及筛选后的实验报告、汇总、运行参数、历史轨迹和曲线。课程原题、Excel输入、逐轮模型及求解器许可证不随仓库上传，运行输入由使用者自行准备。

目录入口见[项目总索引](项目索引.md)；研究结论见[实验记录索引](problem2/docs/实验记录索引.md)，原始批次见[结果归档索引](problem2/results/README.md)。课程汇报素材见[PPT制作交接入口](PPT制作/README.md)。

2026-10-21开发补充（仅本地，尚未提交）：新增[二阶段区间/自由工件切换与续跑](problem2/stage2/README.md)，[正确性门禁](problem2/results/stage2_neighborhoods_gate/run02/实验记录.md)通过；从此前保存的10650短时验证仍为10650，尚无长预算收益结论。下方10月14日课程状态与10702属于历史记录，正式一阶段默认未变，夜间实验未启动。

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
| Case 2历史最好可行调度 | 10454秒 | 2026-10-22十小时夜间二阶段混合搜索得到，350工序独立核验通过；全部Gurobi范围受限，未证明全局最优 |
| Case 2一阶段最好可行调度 | 10592秒 | 2026-10-22，1200秒、种子2026102101、退火480秒/降温0.998配置；不是正式默认600秒结果 |
| Case 2旧历史最好（已被超过） | 10702秒 | 来自不限时宽度9追加求解，首次找到约7小时3分钟；保留为历史记录，不再代表当前最好值 |
| 二阶段联合重排 | 历史从10890改善到10847秒 | 成组枚举、局部Gurobi及扰动的组合；稳定性仍需测试 |
| 利用退火记录缩小约束 | 已完成对照实验 | 未证明优于现有区间限制；自动固定机器出现排除更好编码的反例 |
| 候选前驱、后继集合 | 本机独立接口及32组合全因子试验已完成 | 未显示整体收益；部分受限最优值比原区间已有可行值更差，当前规则不采用 |
| 课程项目正式方案 | 构造与下降 → 退火 → 区间搜索 | 保留初始宽5、每轮5秒和宽度自适应；结束本轮算法扩展实验 |
| 区间宽度与单轮时间 | 八个新种子、56组已完成 | 延长时限未显示整体优势；固定宽5也未稳定优于自动调整 |

历史结果的完整证据保存在本机 `problem2/results/`；仓库只包含筛选后的报告和过程记录，以及Case 1、Case 2最好结果各一份完整调度。逐轮模型和大部分逐轮调度不包含在仓库内。文档中的历史结果用于说明已有研究，不承诺相同种子在不同机器、时限或求解器版本下返回相同调度。受限模型达到OPTIMAL只证明本轮附加条件下最优。

## 当前正式方案

课程项目正式方案已确定：贪心构造＋完整局部下降 → 模拟退火 → Gurobi区间搜索。保留模拟退火，区间初始宽度5、每轮求解最多5秒，沿用当前宽度自适应规则；二阶段作为可选追加改善方法。当前候选相邻约束不采用，不统一延长到15或60秒。结束本轮算法扩展实验，后续工作转为模型、代码、参数、结果验证和课程报告的一致性整理，没有安排新的求解任务。定版不代表不存在优化空间，也不构成Case 2全局最优证明。

区间宽度与单轮时间的[56组实验报告](problem2/results/interval_width_time/run01/实验记录.md)及[因子分析](problem2/results/interval_width_time/run01/factorial_analysis.json)显示：宽5在5/15/60秒下八种子的最终值逐项相同；宽7/60秒虽有个别收益，平均比原自动调整差42秒。固定宽5比基线平均好3.25秒，但仅2胜4平2负，尚无稳定优势，不直接替换自动调整。154项测试、14个三工件门禁通过，4639模型和9331份350工序调度验证通过；结果仅对应本次八个新种子、180秒追加预算和受限范围。

五类退火信息的主效应与交互作用见[全因子报告](problem2/results/sa_information_doe/run02/实验记录.md)及[因子分析](problem2/results/sa_information_doe/run02/factorial_analysis.json)。24个固定范围共816模型；所有主效应的探索性区间包含0，未完成独立新种子确认，不能将信息本身判为普遍有效或无效。部分候选模型已求到受限最优，仍差于原区间已有可行值；这证明当前附加限制在这些范围内排除了达到该更好值的全部方案，详见[范围对照](problem2/results/sa_information_doe/run02/restriction_comparison.json)。

公开仓库同步正式方案说明和精简实验分析证据。新增退火记录、候选约束、区间宽度与时间实验模块及对应测试仍保留在本机，未随本次文档提交上传；相关实验入口、源码快照及测试/门禁计数描述本机已完成的对应实验，不表示公开仓库当前源码已包含全部研究接口。

## 收录的实验记录

`problem2/results/`采用允许文件清单：实验报告Markdown、`summary.json`、`config.json`、`*history*.json`、`events.jsonl`、`rounds.jsonl`、过程及对照CSV，以及5张下降或温度曲线。历史源码快照、逐轮MPS、解文件、求解日志、其他甘特图和时间表均不收录。一般规则见[.gitignore](.gitignore)；本次另明确收录全因子试验的`report_summary.json`、`factorial_analysis.json`、三个独立核验JSON、`restriction_comparison.json`及`task_completion.json`，另收录区间宽度/时间试验的`config.json`、`report_summary.json`、`factorial_analysis.json`、`verification.json`、`final_review.json`及`task_completion.json`，其余模型、完整调度和记录仍留在本机。

以下两份调度各保留`result.json`、`schedule.csv`和`gantt.svg`：

- [Case 1的5031秒调度](problem2/results/exact_case1/run01/gurobi/result.json)。
- [Case 2的10702秒调度](problem2/results/overnight_windows/run01/width9/seed23/best/result.json)。

它们便于查看和核对工序安排，但独立复核仍需原始Excel。原MPS未收录，仓库不能单独重放全部历史最优证明。

## 代码和文档

| 路径 | 内容 |
| --- | --- |
| [problem2/common](problem2/common/README.md) | 数据、编码解码、评分、精确模型、验证及导出 |
| [problem2/stage1](problem2/stage1/README.md) | 构造、局部下降、退火、区间求解及正式一阶段入口 |
| [problem2/stage2](problem2/stage2/README.md) | 联合重排、扰动和并行多起点研究 |
| [problem2/tests](problem2/tests/README.md) | 单元测试；集成对照以小实例穷举核验求解器 |
| [problem2/experiments](problem2/experiments/README.md) | 历史方法和独立对照入口 |
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
