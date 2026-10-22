# 二阶段目录索引

[项目总索引](../../项目索引.md) · [运行说明](../README.md) · [实验记录索引](../docs/实验记录索引.md)

二阶段是可选追加改善：少量工件在前后段成组联合重排，必要时有限次调用Gurobi允许自由插入，并可扰动后继续下降。它不属于一阶段默认600秒以内的固定组成，不保证每次改善。

入口`python -B -m problem2.stage2.main`；提供`--reference`时先验证参考调度，报告参考历史成本和本次追加成本。`python -B -m problem2.stage2.multistart`是多进程枚举与扰动，不调用Gurobi，不能把其墙钟与单进程算法当成相同CPU预算。

|文件|职责|使用方式|Git跟踪状态|
|---|---|---|---|
|[__init__.py](__init__.py)|题目2模块。|共用模块/兼容接口；按实际调用使用|已跟踪|
|[joint_search.py](joint_search.py)|少量工件同时在前后段成组重排；其余工件的相对顺序和机器保持。|共用模块/兼容接口；按实际调用使用|已跟踪|
|[main.py](main.py)|前后段联合重排、少量自由工件Gurobi及扰动后局部下降的研究入口。|独立入口；运行前核对参数与预算|已跟踪|
|[multistart.py](multistart.py)|保留不同局部最优起点，独立多进程联合重排；统一预算包含初始化。|独立入口；运行前核对参数与预算|已跟踪|

历史10890→10875→10862→10847是多个追加步骤的记录，不是默认一次运行结果。细节见[主设计](../docs/算法设计.md#66-10月11日联合重排与评分验证)及[并行多起点设计](../docs/并行多起点搜索.md)。

## 2026-10-21：区间与自由工件切换研究入口

新增独立入口`python -B -m problem2.stage2.neighborhood_main`，实现位于[neighborhood_search.py](neighborhood_search.py)，命令行位于[neighborhood_main.py](neighborhood_main.py)。这些新文件目前仅在本地，尚未提交；现有`main`、`multistart`和一阶段默认流程保持原样。

它读取并验证已有完整调度，再在两种邻域间切换：

1. 连续区间：A、B各放开一个连续区间，复用一阶段模型接口。
2. 自由工件：选少量工件，允许它们分别插入A、B的任意位置并换机；所选工件可以相隔很远，其余工件只保持相对顺序和机器归属。

窗口连续6轮无改善后转入自由工件；自由工件连续3轮无改善后回到窗口，并轮换宽度。任何严格改善都更新参考解、回到第一个宽度。候选工件组交替考虑关键工件权重和A/B中的位置跨度，受候选组数限制，未枚举全部工件组合。本版不启用扰动，不接受较差或同值的其他参考编码，也不从一阶段历史中导入已证明范围。

|参数|研究入口默认值|说明|
|---|---|---|
|`--widths`|5 7 9|轮换的连续区间宽度；小实例自动截为至多n−1并去重|
|`--group-sizes`|3 4|自由工件数量；小实例同样截为至多n−1|
|`--groups-per-size`|32|每种数量、每个参考解最多选择的候选组数|
|`--window-stall` / `--free-batch`|6 / 3|触发切换的连续无改善轮数|
|`--window-seconds` / `--free-seconds`|30 / 90秒|首次调用的基础求解上限；不是已证明最佳参数|
|`--attempts-per-range`|2|同参考解同范围最多尝试两次；第二次基础时限翻倍|
|`--threads` / `--seed`|8 / 23|线程与随机种子|
|`--seconds` / `--max-rounds`|600秒 / 10000|本次追加总预算和最多调用数，续跑时只约束新的一段|

已证明受限最优的同参考解范围不再求解；未完成的范围可以按上述次数重试。改变参考编码后必须重新判断范围。达到尝试上限或所选范围全部尝试过，都不代表整个邻域已证明最优。

```powershell
python -B -m problem2.stage2.neighborhood_main --case 2 --reference 你的结果目录/final/result.json --seconds 600 --output problem2/results/stage2_neighborhoods/new01
python -B -m problem2.stage2.neighborhood_main --case 2 --resume problem2/results/stage2_neighborhoods/new01/checkpoint.json --seconds 600 --output problem2/results/stage2_neighborhoods/new02
python -B -m problem2.stage2.neighborhood_main --help
```

`--reference`和`--resume`必须二选一，输出目录始终必须不存在。检查点记录最好编码、随机状态、范围尝试、切换状态与历史记录，求解前后均原子写入。续跑核对输入文件、核心源码哈希及邻域参数；改变源码或参数时应从保存的`result.json`新建运行。强制中止后可续跑，但检查点之后未报告的已用时间无法还原，会明确标记成本不完整；它不能恢复被中断的Gurobi搜索树。

输出包含`config.json`、准确源码快照、`checkpoint.json`、`progress.json`、`summary.json`、`reference/best/final`完整调度，以及逐轮限制、模型、原生日志和原始求解器时间表。本次追加成本与参考解历史成本分开；达到截止后不启动新轮次，无法即时中断的建模、核验和末尾导出仍须报告真实时间。全部Case2子模型标为`scope=restricted`，OPTIMAL只对该范围有效。

开发验证见[本地门禁报告](../results/stage2_neighborhoods_gate/run02/实验记录.md)：168项单元测试通过，10个三工件模型与各288编码穷举一致，Case2完成实际切换和新目录续跑，全部350道工序独立核验。短验证仍为10650；本次没有稳定收益结论，也未启动夜间长实验。

## 选组方式的小预算诊断（2026-10-21，仅本地）

独立[group_selection_study实验](../experiments/group_selection_study.py)未修改本目录任何Python函数。固定10650、同候选池，四规则各取3组，去重9范围，各最多30秒；四种规则各检查3组，去重后的9个范围均未改善，最好仍10650。其中0个范围已证明各自最优，另外9个尚未证明最优；本次没有证据选出胜者。这组30秒试验对四种选组规则没有产生区分，不能将同值解释为四种规则等效或均无用。 见[报告与限制](../results/free_job_selection/run01/实验记录.md)。本次没有将任何选组规则换成新的默认，也未启动夜间长跑。

## 大组扰动与联合插入重建（2026-10-21第一轮原型，仅本地）

[perturb_rebuild.py](perturb_rebuild.py)是独立启发式入口，不调用Gurobi。每轮从最好解随机选择5/7/9个工件扰动，再对所选工件逐件联合改变A插入位置、B插入位置和机器，完整评分至一遍无改善或预算结束；只有严格改善替换全程最好。默认批大小1024、缓存8192、最多50遍保护、单轮30秒、总60秒/3轮，支持`--batch-size 0`作逐个评分诊断。它尚未并入`neighborhood_main`或原二阶段入口。

命令：`python -B -m problem2.stage2.perturb_rebuild --case 2 --reference 你的结果目录/final/result.json --sizes 5 7 9 --seconds 60 --output problem2/results/rebuild_new01`。输出须新建；检查点只保存最好编码，不是完整状态续跑。新增核心文件会改变整体源码指纹，旧变邻域检查点若因此拒绝，需从完整结果JSON新建运行，保留核查。

见[run02开发报告](../results/perturb_rebuild_gate/run02/实验记录.md)：186项测试通过，5/7/9各一轮350工序核验通过，均未刷新10650；单评分样本批量约3.1倍，不能当端到端提速。run01因两遍保护过早退出而保留，修正后另存run02。尚未接精修、未验证长预算收益。

## 全工件下降与受控较差解接受（2026-10-21质量研究，仅本地）

[iterated_search.py](iterated_search.py)是独立入口，保留`perturb_rebuild`作前轮原型。温和A/B、机器、强扰动轮换，工件数5/7/9；所选工件一遍重建后释放全体工件下降，当前搜索解与历史最好分离，允许限幅3%与模拟退火概率下接受较差当前解，最终返回最好。初温为起点目标0.5%、降温0.98、6轮停滞重启、单轮/起点下降各15秒；这些是研究参数，非最优参数证明。

`python -B -m problem2.stage2.iterated_search --case 2 --reference 你的结果目录/final/result.json --seconds 120 --seed 23 --output problem2/results/iterated_new01`。输出必须新建，检查点尚无完整状态续跑；未接Gurobi精修，未更改已有入口默认。

[质量报告run02](../results/iterated_quality/run02/实验记录.md)：197项测试通过，A版三种子各120秒从同10650得到10628/10650/10650；边界修正B版同种子23回归得到同一10628调度，不算新增独立种子。首次改善在温和扰动后的全工件下降阶段，不能单独归功于较差解接受。历史参考成本另计，无全局最优证明，尚无长预算稳定收益结论。

## 双工件联合调整（2026-10-21研究入口，仅本地）

[pair_search.py](pair_search.py)复用`iterated_search.run`外层，只通过可选下降回调改变局部搜索。先用每段50%时间做原下降，再检查任意距离工件对的A/B交换与两件机器组合，以及允许较差中间解的两次联合插入。第一件保留8个候选（最好6个、前64名其余候选中随机2个），第二件全插入，两种工件顺序都试；不穷举Case2完整双工件范围。原入口不传回调仍沿用原下降，正式默认未改。

`python -B -m problem2.stage2.pair_search --case 2 --reference 你的结果目录/final/result.json --seconds 180 --seed 23 --output problem2/results/pair_new01`。支持`--beam-width 8 --ranked-width 6 --single-fraction 0.5`；这些是本次固定研究参数，非最佳参数证明。输出必须不存在，保存完整JSON/甘特图、源码和输入哈希；仍无完整状态续跑，不调用Gurobi。

从10650出发原搜索/双工件为10628/10650，从10628出发为10628/10627；同种子23、每份180秒，两个相关起点不算独立多实例。本批最好10627，达到低于10628的本轮目标，不证明稳定胜出或全局最优。 见[四份对照报告](../results/pair_quality/run01/实验记录.md)及[核验](../results/pair_quality/run01/independent_review.json)。
