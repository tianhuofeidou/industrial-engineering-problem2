# 测试索引与运行说明

[项目总索引](../../项目索引.md) · [运行说明](../README.md) · [实验记录索引](../docs/实验记录索引.md)

完整单元测试命令，从项目根目录执行：

```powershell
python -B -m unittest discover -s problem2/tests -t .
```

部分测试读取原始课程PDF/Excel，未准备输入时不能声称全部可运行。基础人工小实例检查可用`python -B -m unittest problem2.tests.test_exact_case1 problem2.tests.test_batch`。

实际调用Gurobi的集成对照需另行执行并使用正常用户许可证，例如`python -B -m problem2.tests.test_exact_case1 --integration`或`python -B -m problem2.tests.test_research --integration --compact`；并非每个测试都支持同一参数，执行前核对文件中的参数处理。不要把集成模型、长实验或154项历史测试计数当作本次自动验收。`python -B -m problem2.tests`只转发早期测试，不等价于discover。

本索引列出当前工作区实际文件。标记“仅本地”的新增研究模块或测试尚未提交，不保证下载公开仓库后存在；“已跟踪”也不代表本地修改已推送。历史命令与参数只适用于对应实验，不自动成为正式默认值。

## 编码、模型、评分及正式流程

|文件|职责|使用方式|Git跟踪状态|
|---|---|---|---|
|[test_batch.py](test_batch.py)|批量完整评分、缓存与截止时间边界；不借用课程算例已知最优值。|独立入口；运行前核对参数与预算|已跟踪|
|[test_exact_case1.py](test_exact_case1.py)|一般模型的边界测试；可选小实例穷举与 Gurobi 精确模型对照。|独立入口；运行前核对参数与预算|已跟踪|
|[test_improvements.py](test_improvements.py)|范围缓存、限时初始化和建模后剩余预算的正确性验证。|独立入口；运行前核对参数与预算|已跟踪|
|[test_joint.py](test_joint.py)|联合成组枚举的准确范围、一般模型评分及停止条件。|独立入口；运行前核对参数与预算|已跟踪|
|[test_multistart.py](test_multistart.py)|起点筛选、原初始化兼容、统一截止与完整调度的验证。|独立入口；运行前核对参数与预算|已跟踪|
|[test_research.py](test_research.py)|强化时间界、相邻弧排除及区间范围的完整小实例核验。|独立入口；运行前核对参数与预算|已跟踪|
|[test_stage1.py](test_stage1.py)|检查独立一阶段入口的完整调度、截止处理及拒绝覆盖。|独立入口；运行前核对参数与预算|已跟踪|

## 早期方法与受限模型

|文件|职责|使用方式|Git跟踪状态|
|---|---|---|---|
|[test_four_methods.py](test_four_methods.py)|四算法共用初始化、完整局部最优、终止规则和范围轮换测试。|独立入口；运行前核对参数与预算|已跟踪|
|[test_genetic.py](test_genetic.py)|新编码、遗传操作和受限模型的测试；集成测试用穷举核对受限最优值。|独立入口；运行前核对参数与预算|已跟踪|
|[test_legacy.py](test_legacy.py)|用可手算边界、损坏记录和小实例穷举验证模型规则。|独立入口；运行前核对参数与预算|已跟踪|
|[test_stable.py](test_stable.py)|关系证据、固定约束与缩小模型验证；--integration 对照小实例穷举。|独立入口；运行前核对参数与预算|已跟踪|

## 退火记录、候选约束与因子分析

|文件|职责|使用方式|Git跟踪状态|
|---|---|---|---|
|[test_abc.py](test_abc.py)|持续记录不改变退火轨迹；筛选保留参考解；静态计数与小模型穷举核验。|独立入口；运行前核对参数与预算|已跟踪|
|[test_annealing_feedback.py](test_annealing_feedback.py)|观察器保持退火轨迹；区间评分只使用实际开放的关系。|独立入口；运行前核对参数与预算|已跟踪|
|[test_candidate_arcs.py](test_candidate_arcs.py)|候选集合统计、原题边界及小实例全编码穷举对照。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[test_candidate_trials.py](test_candidate_trials.py)|拒绝样本记录、最终质量筛选以及退火逐次决策不变的核查。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[test_constraint_generation.py](test_constraint_generation.py)|记录不改随机轨迹；没有试探不固定；解除关系后重新计算推论。|独立入口；运行前核对参数与预算|已跟踪|
|[test_information_doe.py](test_information_doe.py)|信息开关、记录内联合统计、参考解及相同弧数量的核查。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[test_m6_candidate_ablation.py](test_m6_candidate_ablation.py)|只限制前后段候选时不能额外限制工位6机器组合。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[test_process_experiment.py](test_process_experiment.py)|完整记录不改变搜索，候选强度包含关系及区间交集穷举。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[test_record_components.py](test_record_components.py)|区分提供的字段、顺序归一化与完整样本筛选。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[test_sa_guided_windows.py](test_sa_guided_windows.py)|退火统计去重、参考解变化、选择规则及保持区间模型范围。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|

## 区间、预算与参考解对照

|文件|职责|使用方式|Git跟踪状态|
|---|---|---|---|
|[test_adaptive_time.py](test_adaptive_time.py)|试探候选完整性、追加选择、受限会话和小实例穷举对照。|独立入口；运行前核对参数与预算|已跟踪|
|[test_annealing_ablation.py](test_annealing_ablation.py)|退火耗时必须占用统一预算；直接组不执行退火且不换初始编码。|独立入口；运行前核对参数与预算|已跟踪|
|[test_annealing_portfolio.py](test_annealing_portfolio.py)|分组不改变退火，保留不同后段，不把机器归属随排列移动。|独立入口；运行前核对参数与预算|已跟踪|
|[test_budget_probe.py](test_budget_probe.py)|新种子的候选范围抽样、完整评分及试探后精确求解的范围一致性。|独立入口；运行前核对参数与预算|已跟踪|
|[test_interval_width_time.py](test_interval_width_time.py)|区间宽度/时间全因子控制、种子内配对、求解观测和多重比较核查。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[test_overnight_windows.py](test_overnight_windows.py)|完整无改善扫描、改善后重查，以及失败范围不得作为最优证明。|独立入口；运行前核对参数与预算|已跟踪|
|[test_stage1_free_jobs.py](test_stage1_free_jobs.py)|核对全位置插入范围、信息选择及小实例的受限最优值。|独立入口；运行前核对参数与预算|已跟踪|
|[test_width_comparison.py](test_width_comparison.py)|固定宽度不自动改变；区间穷举与全部允许编码一致。|独立入口；运行前核对参数与预算|已跟踪|

`__init__.py`是包标识，`__main__.py`只提供历史命令兼容。测试替换函数时指向实际定义模块，避免只修改兼容转发模块。

## 二阶段区间/自由工件切换（2026-10-21新增，仅本地）

[test_stage2_neighborhoods.py](test_stage2_neighborhoods.py)有14项测试：自由工件可跨远距离移动、全部288编码的范围过滤、切换与严格改善、受限最优去重与超时重试、截止保留、检查点及续跑、拒绝覆盖、相对输出路径、错误结果拒绝和求解失败保留最好解。运行`python -B -m unittest problem2.tests.test_stage2_neighborhoods -v`。

本次完整discover为168项全部通过。真实Gurobi门禁另见[run02报告](../results/stage2_neighborhoods_gate/run02/实验记录.md)：10个三工件模型、Case2首段及续跑，不包含在上述单元测试计数中。run01保留路径问题的诊断产物，不替代修复后门禁；不得把短验证当作长预算性能实验。

## 自由工件选组诊断（2026-10-21新增，仅本地）

[test_group_selection_study.py](test_group_selection_study.py)新增8项，核查默认候选前缀、同池选择、随机状态、共享模型、固定参考、不覆盖、截止及失败保留。命令`python -B -m unittest problem2.tests.test_group_selection_study -v`。本轮完整discover为176项全部通过；真实Case2的9个不同范围另见[run01报告](../results/free_job_selection/run01/实验记录.md)，不把这些模型计入单元测试数。

## 大组扰动重建（2026-10-21新增，仅本地）

[test_perturb_rebuild.py](test_perturb_rebuild.py)新增10项，涵盖完整候选范围、非连续大组扰动、全工序批量/逐个评分与修复等价、缓存清理、已完成批次到时保留、异常/过期/拒绝覆盖及复现。完整discover在最终版本下186项全部通过；[run02门禁](../results/perturb_rebuild_gate/run02/实验记录.md)另含2450候选计时和5/7/9工件各一轮短验证，不调用Gurobi。

## 当前搜索解与历史最好解分离（2026-10-21新增，仅本地）

[test_iterated_search.py](test_iterated_search.py)新增11项，核查全工件候选范围、四类扰动、当前/最好分离、较差解限幅与接受、继续沿当前解探索、随机复现、到时/异常保留、已完整评分候选的截止登记、参数和拒绝覆盖。最终discover **197项全部通过**；A版196项与B版197项日志分别保留。[本轮报告](../results/iterated_quality/run02/实验记录.md)独立验证10628、每轮完整350工序及接受轨迹，不把小试当稳定收益证明。

## 双工件联合调整（2026-10-21，仅本地）

[test_pair_search.py](test_pair_search.py)新增10项，核查完整小实例范围、完整批量/逐个评分、远距离同时移动与换机、保留较差中间解、有限候选复现、截止已评分结果保留、当前阶段与全程最好分离、参数错误。`python -B -m unittest problem2.tests.test_pair_search -v`；本轮完整discover **207项通过**。

另有[独立小实例门禁](../results/pair_quality/run01/small_gate.json)：三工件288编码与四工件9216编码分别过滤9个两件范围，候选集合及最小值吻合；[真实单件停滞反例](../results/pair_quality/run01/real_small_barrier.json)为72→71。这些不替代[Case2短对照](../results/pair_quality/run01/实验记录.md)的质量结果。

## 宽度上限新增测试（2026-10-23开发，本次公开）

[test_width_cap.py](test_width_cap.py)核对显式上限、耗尽停止、保留缩小、无参默认和非法参数；本次discover共213项通过。独立[门禁](../results/width_cap_probe/run01/gate_report.json)另核对修改前备份默认轨迹和288编码/真实模型，并非单元测试自动运行长求解。

## 10465成果同步的公开测试

本次包含[test_candidate_arcs.py](test_candidate_arcs.py)、[test_width_cap.py](test_width_cap.py)和[test_annealing_recording.py](test_annealing_recording.py)：核查可选候选接口、宽度上限/默认兼容及过程记录不改变退火随机轨迹。精简公开源码的本次实际测试数量与真实小模型检查见[发布检查](../published/stage1_10465/release_checks.json)，不要将历史本机213项计数解释成公开仓库本次计数。

本次发布检查：精简公开文件树123项单元测试全部通过、0跳过，另6个真实小模型与288编码范围穷举一致；已重新核验10465和全部10个起点，未重跑Case2长时间搜索。

## 10335公开包回归检查

本次公开test_stage2_neighborhoods.py、test_perturb_rebuild.py、test_iterated_search.py及[test_stage2_release.py](test_stage2_release.py)。新增发布回归核查调用条件含等值、跳过GP保留较差候选和全程最好、外层接受不变、可用时间不回填和配对数据一致。仅公开文件树的实际测试计数与真实小模型等价门禁见[发布检查](../published/stage2_10335/release_checks.json)；历史214项是原实验源码的证据，不冒充本次公开测试数。
