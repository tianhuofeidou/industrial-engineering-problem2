# 实验代码索引

[项目总索引](../../项目索引.md) · [运行说明](../README.md) · [实验记录索引](../docs/实验记录索引.md)

独立对照、历史方法和审计工具集中于此；不是正式主入口集合。先在[实验记录索引](../docs/实验记录索引.md)明确比较条件、结论和预算，再查看对应脚本。完整32组合、12小时和夜间任务等带固定期限的旧入口不能照抄过去日期运行，必须另有当前授权和新的输出目录。

本索引列出当前工作区实际文件。标记“仅本地”的新增研究模块或测试尚未提交，不保证下载公开仓库后存在；“已跟踪”也不代表本地修改已推送。历史命令与参数只适用于对应实验，不自动成为正式默认值。

## 区间、预算与实现效率

|文件|职责|使用方式|Git跟踪状态|
|---|---|---|---|
|[interval_width_time.py](interval_width_time.py)|同退火起点比较区间宽度5/7、单轮5/15/60秒及原自动调整流程。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[performance_main.py](performance_main.py)|重复调用开销研究：回放相同范围，并从相同初始调度比较完整区间搜索。|独立入口；运行前核对参数与预算|已跟踪|
|[research_main.py](research_main.py)|多种子启发式、强化受限模型与区间重排研究；所有试验保留完整证据。|独立入口；运行前核对参数与预算|已跟踪|
|[stage1_adaptive_time.py](stage1_adaptive_time.py)|一阶段受限求解：四组相同180秒追加预算，短跑后随机或解码试探选择追加。|独立入口；运行前核对参数与预算|已跟踪|
|[stage1_budget_probe.py](stage1_budget_probe.py)|停止条件四组重复对照及宽度32试探的三个新种子对照。|独立入口；运行前核对参数与预算|已跟踪|
|[stage1_free_jobs.py](stage1_free_jobs.py)|一阶段对照：连续区间、按关键工序/退火档案选两个自由工件、随机选两个。|独立入口；运行前核对参数与预算|已跟踪|
|[stage1_round_time.py](stage1_round_time.py)|同模型5/15/30秒诊断；有效时三个种子相同总预算对照。|独立入口；运行前核对参数与预算|已跟踪|
|[stage1_width_comparison.py](stage1_width_comparison.py)|固定区间宽度与原自动调整规则对照；同范围穷举核对宽度3的Gurobi。|独立入口；运行前核对参数与预算|已跟踪|
|[width7_unlimited.py](width7_unlimited.py)|随机抽取未完成的宽度7范围，不设单轮时限，仅遵守实验总截止时间。|独立入口；运行前核对参数与预算|已跟踪|

## 退火是否必要、参考解与选区间

|文件|职责|使用方式|Git跟踪状态|
|---|---|---|---|
|[abc_comparison.py](abc_comparison.py)|ABC：共享三条前置退火轨迹，比较追加退火、区间求解、记录选约束。|独立入口；运行前核对参数与预算|已跟踪|
|[annealing_ablation.py](annealing_ablation.py)|同起点、同总预算比较直接区间求解与先退火后区间求解。|独立入口；运行前核对参数与预算|已跟踪|
|[annealing_feedback.py](annealing_feedback.py)|用退火的优质编码分歧或近优试探选择实际可以改变这些关系的区间。|独立入口；运行前核对参数与预算|已跟踪|
|[annealing_portfolio.py](annealing_portfolio.py)|按后段排列与机器归属保存退火样本，同预算比较一个与三个参考解。|独立入口；运行前核对参数与预算|已跟踪|
|[sa_guided_windows.py](sa_guided_windows.py)|原区间选择与退火分歧指导选择，各180秒追加预算的独立对照。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[sa_record_components.py](sa_record_components.py)|逐项提供退火信息并比较混合权重，六组各180秒追加预算。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|

## 退火完整记录、候选约束及全因子

|文件|职责|使用方式|Git跟踪状态|
|---|---|---|---|
|[annealing_trace.py](annealing_trace.py)|完整退火过程：编码去重、压缩逐次记录、接受核查及确定性重放。|共用模块/兼容接口；按实际调用使用|仅本地，尚未跟踪|
|[annealing_window_evidence.py](annealing_window_evidence.py)|近优退火样本只影响选择哪个区间，不额外固定模型关系。|共用模块/兼容接口；按实际调用使用|仅本地，尚未跟踪|
|[candidate_trial_records.py](candidate_trial_records.py)|在原已接受样本之外保存被拒绝近优编码，不改变退火决策。|共用模块/兼容接口；按实际调用使用|仅本地，尚未跟踪|
|[constraint_generation.py](constraint_generation.py)|退火记录直接决定解除的先后关系和新增的相邻关系；参考解保持一致。|独立入口；运行前核对参数与预算|已跟踪|
|[information_analysis.py](information_analysis.py)|同范围全因子对比；以种子为重复单位，不能把退火尝试当独立样本。|共用模块/兼容接口；按实际调用使用|仅本地，尚未跟踪|
|[information_factors.py](information_factors.py)|五类信息独立开关；同一记录池、同一弧数量，逐条记录计算联合权重。|共用模块/兼容接口；按实际调用使用|仅本地，尚未跟踪|
|[process_evidence.py](process_evidence.py)|七条预定义记录规则：同一统计用于选区间或可扩大的相邻候选。|共用模块/兼容接口；按实际调用使用|仅本地，尚未跟踪|
|[process_workers.py](process_workers.py)|独立进程执行记录准备、固定区间诊断和完整区间搜索。|共用模块/兼容接口；按实际调用使用|仅本地，尚未跟踪|
|[sa_candidate_main.py](sa_candidate_main.py)|只补测退火候选相邻限制，基线为同编码的已保存完整模型试跑。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[sa_candidate_trials.py](sa_candidate_trials.py)|补入被拒绝近优编码，保持k=5，独立核对退火后再求解候选模型。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[sa_information_doe.py](sa_information_doe.py)|固定区间32组合筛选、完整组合新种子复核；固定截止，自动导出报告。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[sa_m6_candidate_ablation.py](sa_m6_candidate_ablation.py)|限时三组区间对照：不加候选、只加A/B候选、加四队列候选。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[sa_process_experiment.py](sa_process_experiment.py)|12小时串行实验；本机程序自动推进、检查点、独立复核和报告。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|
|[trace_edge_diagnosis.py](trace_edge_diagnosis.py)|事后诊断已保存退火记录和区间对照；不搜索、不调用求解器。|独立入口；运行前核对参数与预算|仅本地，尚未跟踪|

## 长时间搜索、图表与审计

|文件|职责|使用方式|Git跟踪状态|
|---|---|---|---|
|[audit_research.py](audit_research.py)|独立核查研究输出、完整调度、固定关系、模型哈希及源码快照。|独立入口；运行前核对参数与预算|已跟踪|
|[long_budget_plot.py](long_budget_plot.py)|使用现有ReportLab标准图表与PDFium渲染高温试跑的静态曲线。|独立入口；运行前核对参数与预算|已跟踪|
|[long_budget_report.py](long_budget_report.py)|结束后复核时间线、温度和改善快照，生成逐阶段中文实验记录。|独立入口；运行前核对参数与预算|已跟踪|
|[overnight_windows.py](overnight_windows.py)|四个宽度分别运行，单区间不限时；完整一轮无改善才结束该种子。|独立入口；运行前核对参数与预算|已跟踪|

## 早期模型、四算法与遗传研究

|文件|职责|使用方式|Git跟踪状态|
|---|---|---|---|
|[__init__.py](__init__.py)|题目2模块。|共用模块/兼容接口；按实际调用使用|已跟踪|
|[compare_case1.py](compare_case1.py)|只比较题目2 Case 1：完整初始化、四方法、Gurobi逐范围求到最优。|独立入口；运行前核对参数与预算|已跟踪|
|[four_methods.py](four_methods.py)|共用初始解的变邻域、禁忌、模拟退火与固定代数遗传对照。|共用模块/兼容接口；按实际调用使用|已跟踪|
|[genetic.py](genetic.py)|贪心构造初始个体、遗传搜索和优秀个体保留；不调用商业求解器。|共用模块/兼容接口；按实际调用使用|已跟踪|
|[genetic_main.py](genetic_main.py)|三数组编码的贪心、遗传、Case 1 遗传加受限求解统一运行入口。|独立入口；运行前核对参数与预算|已跟踪|
|[hybrid.py](hybrid.py)|Case 1 受限精确优化：固定未选中工件的相对顺序和机器归属。|共用模块/兼容接口；按实际调用使用|已跟踪|
|[initialization.py](initialization.py)|多种前段排列和工位6逐件插入；评价始终计算到工位10。|共用模块/兼容接口；按实际调用使用|已跟踪|
|[legacy_main.py](legacy_main.py)|命令行入口：从项目根目录执行 python -m problem2.experiments.legacy_main。|独立入口；运行前核对参数与预算|已跟踪|
|[schedule.py](schedule.py)|由排列、两条队列和并列优先级计算最早可行时间表。|共用模块/兼容接口；按实际调用使用|已跟踪|
|[search.py](search.py)|迭代贪婪、变邻域下降、模拟退火接受及停滞重启。|共用模块/兼容接口；按实际调用使用|已跟踪|
|[stable_relations.py](stable_relations.py)|启发式记录稳定关系，再调用少量缩小后的Gurobi模型。|独立入口；运行前核对参数与预算|已跟踪|
|[validate.py](validate.py)|独立按记录、原始时长与机器顺序核验时间表，不调用调度计算函数。|共用模块/兼容接口；按实际调用使用|已跟踪|

## 2026-10-21：自由工件选组诊断（仅本地）

[group_selection_study.py](group_selection_study.py)比较现有混合、关键权重、位置分散及同池随机四规则，固定同一个参考编码、3工件、每规则3组、不同范围30秒/8线程，重复组共用结果并预先打乱顺序。要求`--case`、`--reference`、新`--output`和带时区的未来`--end-utc`；模型阶段最多600秒，任务截止前保留600秒收尾，不自动扩大或续跑。见[本地run01报告](../results/free_job_selection/run01/实验记录.md)：四种规则各检查3组，去重后的9个范围均未改善，最好仍10650。其中0个范围已证明各自最优，另外9个尚未证明最优；本次没有证据选出胜者。这组30秒试验对四种选组规则没有产生区分，不能将同值解释为四种规则等效或均无用。这是单参考探索，不是多种子性能确认；正式流程未变。

## 宽度上限开发验证（2026-10-23，仅本地）

[width_cap_probe.py](width_cap_probe.py)复用保存的10614、10826退火起点，配对追加3分钟区间精修，比较最高7/9；单轮30秒。含默认兼容及288编码门禁。入口带本次固定截止，不可直接照抄历史日期重跑；后续需新授权、截止和不存在的输出。见[原始报告](../results/width_cap_probe/run01/实验记录.md)。不等同完整一阶段或参数稳定性验证。

## 一阶段10465公开成果

[复现入口和参数](../published/stage1_10465/README.md)复用正式stage1.main.run，不把本地研究控制器混入正式默认。已有width_cap_probe.py等标为仅本地的入口不因本次发布全部收录。
