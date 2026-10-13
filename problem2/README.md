# 题目2运行与开发说明

正式一阶段入口为 `problem2.stage1.main`，二阶段研究入口为 `problem2.stage2.main`。所有命令从项目根目录执行。项目概况和当前结果见[根目录README](../README.md)，规则及数学递推见[算法设计](docs/算法设计.md)，其他材料见[文档索引](docs/README.md)。

## 输入与环境

仓库不包含原始输入。运行前在项目根目录放入 `问题2.pdf`、`问题2数据.xlsx`，文件名与原始布局保持不变。Excel“表2”提供加工时间，“表4”提供有方向的换模时间。PDF除作为题意依据外，还由入口读取并计算哈希。

基础依赖为openpyxl和NumPy：

```powershell
python -m pip install -r problem2/requirements.txt
```

正式混合流程另需安装 `gurobipy` 并配置有效Gurobi许可证。Case 1的COPT复核另需 `coptpy` 与其许可证。安装Python包不会替代许可证。项目使用现有正常用户许可证，不上传许可证或密钥。

代码使用Python 3.10及以上语法；本机实测Python 3.14。使用者须选择与其Python环境兼容的求解器接口。输入路径由 `common/paths.py` 相对源码定位，输出路径按命令的当前工作目录解释。

## 编码、目标和关键规则

一个编码包含三个长度为n的数组：

- `a`：工位1～5的共同加工顺序。
- `b`：工位6的完工全序，也是工位7～10的共同加工顺序。
- `machines[j]`：工件j属于6-1还是6-2，按工件编号存储，不按排列位置存储。

两条工位6队列由b按机器归属过滤得到。解码在必要时延后工位6开工，使实际完工时刻符合b；机器没有空闲也允许被选中，工件按队列等待。单个编码的评分及完整解码均为O(10n)，完整计算所有工件十道工序。

换模必须等待后一个工件到达，非首件开始时间满足 `S >= max(前件完成, 本件到达) + 换模`。换模只与有方向的工件对有关，每条机器队列首件换模为0；6-2加工时间用 `(12*p+5)//10` 换算。目标是最后一道工序的最大完成时间，不是各工件完成时间之和。

评分、解码及模型共用 `common/`；独立验证器检查完整时间表。修改搜索时应同时保证两个排列合法、机器数组含义不变，并评价完整调度。

## 一阶段：从原始数据求解

```powershell
python -B -m problem2.stage1.main --case 1 --seed 11 --seconds 600 --output problem2/results/stage1_case1_run01
python -B -m problem2.stage1.main --case 2 --seed 2026101114 --seconds 600 --output problem2/results/stage1_case2_run01
python -B -m problem2.stage1.main --help
```

流程如下：

1. 构造8个初始编码，随机化后续构造并对完整编码评分；执行完整局部下降，选择最好者。
2. 模拟退火用前后段插入、交换和单工件换机探索，允许按温度接受较差解，最好可行编码独立保留。
3. Gurobi每轮放开A、B各一个连续区间，固定区间外相对顺序及部分机器归属，设置参考调度为初始解并用其目标限制上界。发现严格改善后更新参考编码，继续选择区间。

目前传给区间选择函数的分歧统计为空；正式流程没有用“退火全程未变”来固定关系。退火记录相关方案在 `experiments/` 独立测试。

| 选项 | 默认值 | 含义 |
| --- | --- | --- |
| `--case` | 2 | 1为7工件，2为35工件 |
| `--seed` | 2026101114 | 随机种子，不是质量保证 |
| `--seconds` | 600 | 含初始化的总预算 |
| `--constructions` | 8 | 初始构造次数 |
| `--annealing-seconds` | 90 | 退火上限 |
| `--temperature-multiplier` | 2 | 校准温度倍率 |
| `--cooling` | 0.97 | 每层降温系数 |
| `--moves` | 1000 | 每温度层的移动数 |
| `--solver-seconds` | 110 | 精确阶段预算 |
| `--round-seconds` | 5 | 单轮Gurobi求解上限 |
| `--max-rounds` | 80 | 精确阶段轮数上限，0跳过求解器 |
| `--width` | 5 | 初始区间宽度，默认按求解状态自适应 |
| `--threads` | 8 | 单轮求解器线程数 |
| `--no-batch-descent` | 不开启 | 关闭Case 2初始化的批量评分 |
| `--range-cache` | 不开启 | 启用已证明范围缓存 |
| `--output` | 必填 | 必须是不存在的新输出目录 |

正式入口默认启用模型精简和环境共用，不提供早期 `research_main` 的 `--compact-model`、`--reuse-env` 参数。各阶段还受总截止时间约束；可能提前结束，不保证用满预算或遍历完全部区间。建模、批量评分、验证及导出不能被时间检查立即中断，查看输出的真实时间。

只运行贪心、下降和退火：

```powershell
python -B -m problem2.stage1.main --case 2 --max-rounds 0 --seconds 120 --output problem2/results/heuristic_only_run01
```

该命令无需启动Gurobi；课程PDF和Excel仍必须准备。

## 二阶段：继续改善已有解

```powershell
python -B -m problem2.stage2.main --case 2 --reference problem2/results/stage1_case2_run01/final/result.json --seconds 600 --explore --output problem2/results/stage2_case2_run01
python -B -m problem2.stage2.main --help
```

先独立验证参考时间表，再选少量工件，枚举其成组插入A、B的位置、组内排列及机器归属。其余工件保持相对顺序和机器归属。有限次Gurobi求解会解除所选工件必须连续的限制，允许它们分别插入其他位置。`--explore`在停滞后扰动并下降，允许较差参考继续探索，全程最好解单独保存。

| 选项 | 默认值 | 含义 |
| --- | --- | --- |
| `--case` | 必填 | 必须与参考解一致 |
| `--reference` | 不提供 | 已有完整result.json；不提供则重新初始化 |
| `--seconds` | 600 | 本次追加预算；无参考时包含初始化 |
| `--size` | 3 | 所选工件数，支持2、3、4 |
| `--groups` | 80 | 每个参考解的候选工件组数 |
| `--seed` | 11 | 随机种子 |
| `--solver-rounds` | 3 | 最多Gurobi调用次数；0仅作枚举及可选扰动 |
| `--solver-seconds` | 120 | 单次精确求解上限 |
| `--solver-period` | 32 | 无改善时先扫描的枚举组数 |
| `--explore` | 不开启 | 启用扰动后继续搜索 |
| `--perturbations` | 12 | 最大扰动次数 |
| `--output` | 必填 | 不存在的新输出目录 |

参考解的历史计算时间不计入追加预算。二阶段没有保证跳出所有局部最优，也没有保证固定预算下优于继续运行一阶段。

另有 `problem2.stage2.multistart` 进行不同起点的多进程枚举与扰动搜索，该入口不调用Gurobi。具体流程见[并行多起点说明](docs/并行多起点搜索.md)，不要把它与单进程方案当作相同CPU预算。

## Case 1完整精确模型

只处理题目2的7工件Case 1。先由Gurobi生成完整模型，再让COPT读取同一份MPS并使用Gurobi可行解作初始解：

```powershell
python -B -m problem2.common.solver --solver gurobi --seconds 600 --threads 8 --output problem2/results/exact_case1_run01
python -B -m problem2.common.solver --solver copt --seconds 600 --threads 8 --output problem2/results/exact_case1_run01
```

两条命令共用输出根目录，各自的求解器子目录不能预先存在。COPT有初始解，不能直接用两者耗时判断哪种求解器更快。最优证明要求OPTIMAL、上下界一致且完整调度验证通过。日常入口不求解Case 2完整模型。

## 输出与复核

| 输出 | 内容 |
| --- | --- |
| `initial/result.json` | 一阶段贪心及下降结果 |
| `annealing/result.json` | 一阶段退火最好调度 |
| `window/` | 一阶段逐轮限制、模型和求解证据 |
| `final/result.json` | 最终完整编码对应队列、工序和验证 |
| `final/schedule.csv`、`final/gantt.svg` | 时间表及加工、换模甘特图 |
| `summary.json` | 真实用时、阶段结果、终止情况 |
| `events.jsonl` | 过程事件及改善记录 |
| `config.json`、`source/` | 运行参数、输入哈希与准确源码快照 |

二阶段初始调度保存为 `reference/`。阶段及逐模型文件以对应入口为准，不保证所有历史实验使用完全相同目录。

完整验证使用 `common/validation.py:validate_exact`，检查到达后换模、首件、机器冲突、加工时长、A/B顺序和实际工位6完工顺序。受限模型的OPTIMAL、下界和gap只对应本轮附加条件；时间预算结束时的最好可行值不代表已证明最优。

## 测试

不需要课程输入和求解器的基础检查：

```powershell
python -B -m unittest problem2.tests.test_exact_case1 problem2.tests.test_batch
```

准备课程PDF和Excel后运行完整单元测试。部分测试读取原始Excel，另有测试核查入口的输入哈希，因此仓库刚下载、尚未放入输入文件时不能声称全部测试可直接通过。

```powershell
python -B -m unittest discover -s problem2/tests -t .
```

小实例的求解器与全部编码穷举对照需要有效Gurobi许可证，单独运行：

```powershell
python -B -m problem2.tests.test_exact_case1 --integration
python -B -m problem2.tests.test_research --integration --compact
```

`python -B -m problem2.tests`只转发早期测试，不等价于完整测试发现命令。

## 开发和历史实验

先读 `common/encoding.py`、`stage1/main.py`、`stage1/windows.py` 和 `common/solver.py`。新增搜索评分、解码或受限求解应共用现有模块，不复制时间递推。修改前遵守根目录[协作规范](../AGENTS.md)。

`experiments/`包含退火必要性、多个参考解、记录生成约束、区间宽度等对照，以及遗传、禁忌和变邻域的历史入口。保留代码用于复核研究，不意味着全部策略已经并入正式流程。实验命令、参数与证明范围见[文档索引](docs/README.md)。

截至2026-10-13，Case 1已证明5031秒；Case 2历史最好可行值10702秒，来自不限时宽度9追加搜索，未证明全局最优。10890是历史一阶段复现实验，10847是历史二阶段结果。退火记录生成固定约束的对照没有证明优于现有区间限制；候选前驱、后继集合目前只有统计与设计，尚未作为正式算法实现。

仓库收录实验报告、汇总JSON、运行参数、历史轨迹、事件记录、过程CSV和少量曲线；Case 1的5031秒调度和Case 2的10702秒调度各保留完整JSON、CSV和甘特图。收录范围见根目录[说明](../README.md)和[忽略规则](../.gitignore)。

原始数据、备份、历史源码快照和绝大多数逐轮模型及调度仍只保留在本机。设计文档中未被收录的 `results/` 链接以及PDF、Excel链接属于本地归档引用；缺少原始输入和原MPS时，不能在另一台电脑复核全部历史模型。
