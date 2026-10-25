# 实验结果归档索引

[项目总索引](../../项目索引.md) · [运行说明](../README.md) · [实验记录索引](../docs/实验记录索引.md)

本目录是只读实验归档导航，不在本次整理中移动批次、模型、完整调度或源码快照。先看[实验记录索引](../docs/实验记录索引.md)了解问题与结论，再查下面的原始批次。

## 优先查看

|用途|文件|解释|
|---|---|---|
|Case 1最优性基准|[5031完整调度](exact_case1/run01/gurobi/result.json)|完整模型已证明最优；COPT读取Gurobi初始解，不比较两者冷启动速度|
|当前默认配置的代表运行|[种子23摘要](reproduce_10890/multiple_seeds_run01/seed23/summary.json)|11086→10952→10873，完整约141.10秒；不是每次运行保证|
|较大阶段预算|[停止条件与宽试探报告](stage1_budget_probe/run01/实验记录.md)|180秒/200轮三次重复10824、10811、10825；10811完整约213秒|
|历史长时间可行调度（10月14日）|[10702完整调度](overnight_windows/run01/width9/seed23/best/result.json)|宽9首次找到追加约7小时3分钟，无全局证明，未完成整个宽9邻域检查|
|最新宽度×单轮时间对照|[56组报告](interval_width_time/run01/实验记录.md)|八新种子；全部模型与完整调度核验通过，默认流程保持|
|五类退火信息全因子|[最终报告](sa_information_doe/run02/实验记录.md)|参考screening_rows的folder跨run01/run02取模型，不只扫描run02|

## 2026-10-21二阶段开发门禁（仅本地）

[stage2_neighborhoods_gate/run02报告](stage2_neighborhoods_gate/run02/实验记录.md)保存最终版本的10个小模型、168项测试、4轮Case2切换/续跑、输入与源码哈希以及独立核验。Case2从历史10650起步，仍10650；短验证不能证明新方案有性能收益。`run01`保留相对路径归档问题的原产物，修复后另建run02，未覆盖旧模型。两批合计求解成本见run02核验，未启动夜间长实验。新增文件尚未提交，公开仓库不保证存在。

## 全部归档类别

|目录|现存直接子批次|用途与注意事项|
|---|---|---|
|[abc_comparison](abc_comparison/)|run01|追加退火、区间求解、记录固定关系的ABC对照。|
|[annealing_ablation](annealing_ablation/)|run01|取消/保留前置退火，固定宽5、180秒追加预算的三种子对照。|
|[annealing_feedback](annealing_feedback/)|run01|较早的退火记录挑选区间研究。|
|[annealing_portfolio](annealing_portfolio/)|run01|同预算单参考与三参考编码分组比较。|
|[call_performance](call_performance/)|replay01、replay02、replay03、search01、search02|相同模型回放、弧筛选、精简约束和36轮搜索的实现效率对照。|
|[case1_encoding_check](case1_encoding_check/)|run01|Case 1编码评分及边界核查。|
|[case1_four_methods](case1_four_methods/)|run01、smoke01|Case 1四算法及精确后处理；run01为正式批次，smoke为烟雾检查。|
|[constraint_generation](constraint_generation/)|run01、run02|记录生成固定关系；run02包含机器联合变化反例。|
|[constraint_generation_small](constraint_generation_small/)|machine_limits01、run01|固定关系的小模型、机器条件与诊断。|
|[critical_search](critical_search/)|run01|联合重排、批量评分及10875/10862/10847历史改善。|
|[design_validation](design_validation/)|run01|早期模型与设计规则核查。|
|[exact_case1](exact_case1/)|gurobi、run01|Case 1完整一般模型，run01/gurobi为5031最优性证据及代表性调度。|
|[first_version](first_version/)|case1、case2|早期最早开工模型/原型，不能当作当前一般模型默认结果。|
|[free_job_selection](free_job_selection/)|run01|固定10650、同候选池四规则各3组；9个去重范围均未改善，不据此选胜者。|
|[full_pipeline_30min](full_pipeline_30min/)|run01、run02_no_gurobi|历史完整流程与关闭Gurobi对照，条件以各批次记录为准。|
|[genetic_v1](genetic_v1/)|case1_compare、case1_compare_refresh、case1_release5、case2_genetic、case2_genetic_fixed、case2_greedy|早期贪心、遗传、Case 1混合受限求解等批次。|
|[interval_width_time](interval_width_time/)|run01|八新种子56组宽度×时限对照，run01已完整核验。|
|[interval_width_time_gate](interval_width_time_gate/)|run01、run02|14个三工件模型门禁；run02对应计时字段修正后正式源码。|
|[iterated_quality](iterated_quality/)|run01、run02|从10650追加的全工件下降与受控较差接受；run02的seed23得到10628。|
|[long_budget](long_budget/)|run01|30分钟多起点历史任务、温度及曲线；不能冒充默认单起点运行。|
|[multistart_30min](multistart_30min/)|run01、smoke_case1|二阶段多进程联合搜索的历史批次。|
|[overnight_windows](overnight_windows/)|run01|宽度3/5/7/9夜间不限单轮时限搜索；10702为width9/seed23/best。|
|[pair_quality](pair_quality/)|run01|从10650与10628两个相关起点各180秒的原搜索与双工件对照；最好10627。|
|[parameter_tuning_8h](parameter_tuning_8h/)|run01|八小时参数研究：16筛选＋9确认＋2长预算＋1余量，共28次；最好10650。|
|[perturb_rebuild_gate](perturb_rebuild_gate/)|run01、run02|5/7/9工件大组扰动重建；run02为最终版本，三候选均未超过10650。|
|[reproduce_10702](reproduce_10702/)|run01|读取和程序复算10702等复核记录，不等于重新搜索发现。|
|[reproduce_10890](reproduce_10890/)|multiple_seeds_run01、run01|正式默认参数复现；run01为10890，multiple_seeds_run01包含10873。|
|[research_v2](research_v2/)|case1_multiseed01、case1_probe01、case2_probe01、case2_seed11_run01、case2_seed23_run01、case2_seed37_run01|区间框架、完整模型诊断、追加退火与局部精确的早期对照。|
|[sa_candidate_arcs](sa_candidate_arcs/)|run01、validation01|原k=5候选相邻约束与纯退火完整模型基线对照。|
|[sa_candidate_trials](sa_candidate_trials/)|run01|增加被拒绝近优样本后的候选约束试验。|
|[sa_complete_process](sa_complete_process/)|run01|完整退火记录、选区间与候选约束联合对照，含独立新种子及长预算复核。|
|[sa_complete_process_gate](sa_complete_process_gate/)|run01、run02|完整过程记录与区间/候选交集的穷举门禁，非性能样本。|
|[sa_guided_windows](sa_guided_windows/)|run01|三种子退火分歧选区间与原选择规则对照。|
|[sa_information_doe](sa_information_doe/)|run01、run02|五类信息32组合；run02续接run01已完成模型，最终数据覆盖两目录。|
|[sa_information_doe_gate](sa_information_doe_gate/)|run01、run02|32组合与默认范围一致性的三工件穷举门禁。|
|[sa_m6_candidate_ablation](sa_m6_candidate_ablation/)|run01|四新种子：不加、只加A/B、加四队列候选限制的消融比较。|
|[sa_m6_candidate_ablation_gate](sa_m6_candidate_ablation_gate/)|run01|移除工位6候选限制的模型穷举门禁。|
|[sa_record_components](sa_record_components/)|run01|A/B/机器字段及权重对照，旧种子探索，不是独立复核。|
|[sa_start_full](sa_start_full/)|run01|同纯退火起点的Case 2完整Gurobi模型，三组各180秒未改善。|
|[search_improvement](search_improvement/)|run01|历史搜索调整及阶段改善记录。|
|[stable_relations](stable_relations/)|case1_run01、case1_run02、case1_run03、case2_run01、case2_run02、case2_run03|早期稳定关系受限模型及各算例独立批次。|
|[stage1_adaptive_time](stage1_adaptive_time/)|prototype01、run01|短跑后继续求解、随机追加及评分追加的研究；prototype是原型。|
|[stage1_budget_probe](stage1_budget_probe/)|run01|110/180秒×80/200轮三次重复与宽试探；包含约213秒得到10811。|
|[stage1_free_jobs](stage1_free_jobs/)|run01|两自由工件全位置重排与连续区间比较。|
|[stage1_one_hour](stage1_one_hour/)|run01、run02|一小时预算的一阶段多批试跑；结果按当时配置解释。|
|[stage1_round_time](stage1_round_time/)|run01|自由工件同模型5/15/30秒及后续总预算对照，不是最新宽度×时间试验。|
|[stage1_sa_allocation](stage1_sa_allocation/)|run01、run02|20分钟档退火分配研究：run01为种子2101，run02补2102、2103；最终10592/10738/10726。|
|[stage1_width_comparison](stage1_width_comparison/)|run01、run02|宽3/5/7/9及自适应；run01许可证账户失败，正式结果在run02。|
|[stage2_neighborhoods_gate](stage2_neighborhoods_gate/)|run01、run02|区间与非连续自由工件切换及续跑门禁；run02为最终版本，Case2仍10650。|
|[stage2_overnight_hybrid](stage2_overnight_hybrid/)|run01|十小时大组扰动、重建下降与宽5/7/9区间精修串联；308轮得到10454。|
|[temperature_comparison](temperature_comparison/)|run01|历史退火温度参数对照，仅按对应配置解释。|
|[trace_edge_diagnosis](trace_edge_diagnosis/)|run01、run02、run03|已保存样本的事后弧排除检查，不把结果回填搜索或候选排序。|
|[width7_unlimited](width7_unlimited/)|run01|六个原超时宽7范围不限单轮时限的耗时诊断。|

## 文件怎么读

通常先读`实验记录.md`、`summary.json`或`report_summary.json`，再读`config.json`、`verification.json`/`final_audit.json`/`final_review.json`；具体名称依入口而异，不保证每批次完全相同。`result.json`是完整调度，`schedule.csv`是工序表，`gantt.svg`是相应目标值的甘特图。`solver_schedule/`可保留原生时间表；重新解码后的表可能更早，须区分。

`source/`等快照只记录当时版本，不在目录整理中改写。`run01`不自动意味着正式成功：失败、部分完成、续跑、门禁、烟雾检查须按报告判定。任何受限OPTIMAL仅证明对应固定范围，不能当作原题全局证明。

输入PDF/Excel、逐轮模型日志及大部分完整调度仅在本机；公开仓库是筛选收录，链接存在于本机不等于已上传。Gate目录只检查规则，不纳入性能胜负统计。不要递归遍历大量逐轮目录来找总体结论，也不要自动续跑旧任务。

## 自由工件选组诊断（2026-10-21，仅本地）

[free_job_selection/run01](free_job_selection/run01/实验记录.md)保存四规则、12规则位/9不同范围、同10650参考、同候选池和30秒串行求解。四种规则各检查3组，去重后的9个范围均未改善，最好仍10650。其中0个范围已证明各自最优，另外9个尚未证明最优；本次没有证据选出胜者。这组30秒试验对四种选组规则没有产生区分，不能将同值解释为四种规则等效或均无用。 原始模型及350工序已独立核验；176项测试通过。共享成本不可相加，不是多种子长预算性能实验，未更改默认或提交。

## 大组扰动重建门禁（2026-10-21，仅本地）

[perturb_rebuild_gate/run02](perturb_rebuild_gate/run02/实验记录.md)是最终版本：186项测试、2450候选批量/逐个评分一致、5/7/9各一轮及全部350工序核验。run01保留过早两遍退出的初版，不覆盖历史。均保持10650，未调用Gurobi、未做长预算性能试验；实际重建耗时和限制见报告。

## 二阶段质量搜索10628（2026-10-21，仅本地）

[iterated_quality/run02报告](iterated_quality/run02/实验记录.md)及[10628完整调度](iterated_quality/run02/seed23/final/result.json)是从已有10650追加的研究结果，不是默认600秒完整流程。run01保存A版三种子120秒的10628/10650/10650及源码；run02保存边界修复B版197项测试、同种子回归和独立核验。版本和重复种子成本单列，没有原题最优证明、未调用Gurobi、未做夜间长跑。

## 双工件联合调整（2026-10-21，仅本地）

[新增对照目录](pair_quality/run01/实验记录.md)包含冻结源码、9个小范围穷举门禁、四工件72→71反例、207测试证据及四份180秒Case2对照。从10650出发原搜索/双工件为10628/10650，从10628出发为10628/10627；同种子23、每份180秒，两个相关起点不算独立多实例。本批最好10627，达到低于10628的本轮目标，不证明稳定胜出或全局最优。 [独立复核](pair_quality/run01/independent_review.json)核对逐轮完整编码、350工序、输入/源码/参考哈希；历史参考计算成本另计，未调用Gurobi、未安排长跑或推送。

## 一阶段20分钟档退火分配（2026-10-22，仅本地）

[run01](stage1_sa_allocation/run01/实验记录.md)与[run02](stage1_sa_allocation/run02/实验记录.md)把总预算1200秒中的退火上限从约125秒提高到480秒：初温倍率0.5、降温0.998、每层1000移动，到终温后从已有最好编码升温重启，周期种子为原种子加1000003×(周期−1)；精修用剩余时间，单轮30秒、初始宽5自适应、8线程、缓存关闭。总预算与单轮时限、线程数、宽度均与正式默认不同，正式默认和119份源码未改。

|种子|历史原配置退火|历史原配置最终|新配置退火|新配置最终|
|---:|---:|---:|---:|---:|
|2026102101|10713|10650|10594|10592|
|2026102102|10741|10729|10738|10738|
|2026102103|10897|10862|10774|10726|

原配置均值10747.0、最好10650、最差10862；新配置均值10685.33、最好10592、最差10738，均值、最好、最差三项均改善，2胜1负、平均−61.67秒。三个种子的初始化结果均为11086且编码哈希一致，原配置为8小时参数研究已保存运行、本次未重跑，两者预算相差约12秒。种子2101参与过配置选择，只有2102、2103属新样本；同种子只有三份，不构成参数最优或稳定胜出证明。全部350工序与119份源码、输入哈希核对通过，所有Gurobi范围scope=restricted。

该批同时暴露两点：一是退火实际1200秒里只用了480秒，周期2仅得7.16/81.02/19.99秒且三次均无改善，重启在当前预算下未获有效执行；二是精修预算由原配置约1055秒压到约708秒、轮数由109–115降到67–73，阶段收益由平均−36.67秒降到−16.67秒。完整对照见各run的report_summary.json与verification.json。

## 十小时夜间二阶段混合（2026-10-22，仅本地）

[stage2_overnight_hybrid/run01](stage2_overnight_hybrid/run01/实验记录.md)从一阶段保存的10650出发，串联现有函数而不改119份源码：每轮随机选5/7/9个工件大组扰动，所选工件A/B/机器联合重建最多45秒，全工件下降与单件联合插入合计最多120秒；随后逐个运行宽5/7/9区间精修。跨轮允许最好值3%内按温度接受较差当前解，全程最好完整编码始终保留。

实际总墙钟35388.746秒（约9小时49分49秒），完成308轮、924个受限模型，最终最好**10454**、当前搜索解10470，最好值首次登记于任务起点后27140.02秒（该时间为发现时间上界）。与10627差−173秒，与用户报告但未独立核验的10407差47秒。最终独立核验True，350工序、原生求解日志及MPS哈希均核对；全部Gurobi结果scope=restricted，不构成原题全局最优证明。控制器检查点保存完整状态，未实现无条件重启续跑。

本次没有严格等预算方法对照，各阶段改善不能当作方法独立排名；历史10627与外部10407只在搜索结束后评价，未用于选关系、设上界或提前停止。

## 2026-10-23白天宽度上限短实验（仅本地）

[width_cap_probe/run01记录](width_cap_probe/run01/实验记录.md)：保存退火起点10614/10826，最高7/9各追加3分钟，固定30分钟任务预算含开发门禁；213测试和288编码门禁通过。结果以批次报告为准；历史起点成本另计，不是完整一阶段性能确认。

## 2026-10-25一阶段六组合夜间研究（仅本地）

[本批锁定计划](stage1_shape_cap_10h/run01/计划.md)：三套退火配置A/B/C与宽度上限7/9，两个新种子全对照及第三新种子补测，每份40分钟、6线程/六物理核单逻辑处理器、固定10小时。状态及结论以批次status与最终实验记录为准；未切换正式默认，历史八线程结果不作配对基线。

## 两核白天完整一阶段起点池

[锁定计划](stage1_start_pool_2core/run01/计划.md)：A/B各4个不同新种子，每份40分钟，串行、两物理核、Gurobi2线程、低优先级；仅生成二阶段起点，不启动二阶段。已有10568/10574复核后纳入，历史成本另计；最终以批次状态和报告为准，不作配对参数比较。

## 2026-10-25：两核起点池完成与公开精简包

本批8/8完成，最好10465，加历史参考去重后10个编码，1241个受限模型经程序核验。[公开报告、完整代表调度与10个编码](../published/stage1_10465/README.md)；[本地原始报告](stage1_start_pool_2core/run01/实验记录.md)。原始JSON/MPS/大日志不放宽忽略规则，也不删除本机归档。
