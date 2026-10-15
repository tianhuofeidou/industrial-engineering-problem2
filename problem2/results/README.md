# 实验结果归档索引

[项目总索引](../../项目索引.md) · [运行说明](../README.md) · [实验记录索引](../docs/实验记录索引.md)

本目录是只读实验归档导航，不在本次整理中移动批次、模型、完整调度或源码快照。先看[实验记录索引](../docs/实验记录索引.md)了解问题与结论，再查下面的原始批次。

## 优先查看

|用途|文件|解释|
|---|---|---|
|Case 1最优性基准|[5031完整调度](exact_case1/run01/gurobi/result.json)|完整模型已证明最优；COPT读取Gurobi初始解，不比较两者冷启动速度|
|当前默认配置的代表运行|[种子23摘要](reproduce_10890/multiple_seeds_run01/seed23/summary.json)|11086→10952→10873，完整约141.10秒；不是每次运行保证|
|较大阶段预算|[停止条件与宽试探报告](stage1_budget_probe/run01/实验记录.md)|180秒/200轮三次重复10824、10811、10825；10811完整约213秒|
|长时间最好可行调度|[10702完整调度](overnight_windows/run01/width9/seed23/best/result.json)|宽9首次找到追加约7小时3分钟，无全局证明，未完成整个宽9邻域检查|
|最新宽度×单轮时间对照|[56组报告](interval_width_time/run01/实验记录.md)|八新种子；全部模型与完整调度核验通过，默认流程保持|
|五类退火信息全因子|[最终报告](sa_information_doe/run02/实验记录.md)|参考screening_rows的folder跨run01/run02取模型，不只扫描run02|

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
|[full_pipeline_30min](full_pipeline_30min/)|run01、run02_no_gurobi|历史完整流程与关闭Gurobi对照，条件以各批次记录为准。|
|[genetic_v1](genetic_v1/)|case1_compare、case1_compare_refresh、case1_release5、case2_genetic、case2_genetic_fixed、case2_greedy|早期贪心、遗传、Case 1混合受限求解等批次。|
|[interval_width_time](interval_width_time/)|run01|八新种子56组宽度×时限对照，run01已完整核验。|
|[interval_width_time_gate](interval_width_time_gate/)|run01、run02|14个三工件模型门禁；run02对应计时字段修正后正式源码。|
|[long_budget](long_budget/)|run01|30分钟多起点历史任务、温度及曲线；不能冒充默认单起点运行。|
|[multistart_30min](multistart_30min/)|run01、smoke_case1|二阶段多进程联合搜索的历史批次。|
|[overnight_windows](overnight_windows/)|run01|宽度3/5/7/9夜间不限单轮时限搜索；10702为width9/seed23/best。|
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
|[stage1_round_time](stage1_round_time/)|run01|自由工件同模型5/15/30秒及后续总预算对照，不是最新宽度×时间试验。|
|[stage1_width_comparison](stage1_width_comparison/)|run01、run02|宽3/5/7/9及自适应；run01许可证账户失败，正式结果在run02。|
|[temperature_comparison](temperature_comparison/)|run01|历史退火温度参数对照，仅按对应配置解释。|
|[trace_edge_diagnosis](trace_edge_diagnosis/)|run01、run02、run03|已保存样本的事后弧排除检查，不把结果回填搜索或候选排序。|
|[width7_unlimited](width7_unlimited/)|run01|六个原超时宽7范围不限单轮时限的耗时诊断。|

## 文件怎么读

通常先读`实验记录.md`、`summary.json`或`report_summary.json`，再读`config.json`、`verification.json`/`final_audit.json`/`final_review.json`；具体名称依入口而异，不保证每批次完全相同。`result.json`是完整调度，`schedule.csv`是工序表，`gantt.svg`是相应目标值的甘特图。`solver_schedule/`可保留原生时间表；重新解码后的表可能更早，须区分。

`source/`等快照只记录当时版本，不在目录整理中改写。`run01`不自动意味着正式成功：失败、部分完成、续跑、门禁、烟雾检查须按报告判定。任何受限OPTIMAL仅证明对应固定范围，不能当作原题全局证明。

输入PDF/Excel、逐轮模型日志及大部分完整调度仅在本机；公开仓库是筛选收录，链接存在于本机不等于已上传。Gate目录只检查规则，不纳入性能胜负统计。不要递归遍历大量逐轮目录来找总体结论，也不要自动续跑旧任务。
