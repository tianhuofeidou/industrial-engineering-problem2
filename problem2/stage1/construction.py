"""贪心构造、完整局部下降和初始解选择。"""
import random
import time
from problem2.common.data import m62_duration
from problem2.common.encoding import Chromosome, evaluate
from problem2.common.evaluator import Evaluator, BudgetExpired
from problem2.common.local_search import descend

def balanced_code(data):
    order = tuple(sorted(range(data.n), key=lambda j: (-sum(data.processing[j]), j)))
    machines = [0]*data.n
    load = [0, 0]
    for j in order:
        durations = (data.processing[j][5], m62_duration(data.processing[j][5]))
        m = min(range(2), key=lambda m: (load[m]+durations[m], m))
        machines[j] = m
        load[m] += durations[m]
    return Chromosome(order, order, tuple(machines))

def greedy_construct(data, evaluator, rng, randomized=True):
    """插入位置均评价完整编码；未插回工件放尾部，不评价不完整生产线。"""
    base = balanced_code(data)
    priority = list(base.a)
    if randomized:
        rng.shuffle(priority)
    machines = list(base.machines)
    prefix = []
    for index, j in enumerate(priority):
        tail = priority[index+1:]
        candidates = []
        for position in range(len(prefix)+1):
            order = prefix[:position]+[j]+prefix[position:]+tail
            code = Chromosome(tuple(order), tuple(order), tuple(machines))
            candidates.append((evaluator.cost(code), position))
        candidates.sort()
        chosen = candidates[0]
        if randomized and rng.random() < 0.25:
            chosen = rng.choice(candidates[:3])
        prefix.insert(chosen[1], j)
    a = tuple(prefix)
    prefix = []
    for index, j in enumerate(a):
        tail = list(a[index+1:])
        candidates = []
        for position in range(len(prefix)+1):
            b = tuple(prefix[:position]+[j]+prefix[position:]+tail)
            for m in (0, 1):
                assignments = machines[:]
                assignments[j] = m
                code = Chromosome(a, b, tuple(assignments))
                candidates.append((evaluator.cost(code), position, m))
        candidates.sort()
        chosen = candidates[0]
        if randomized and rng.random() < 0.25:
            chosen = rng.choice(candidates[:3])
        prefix.insert(chosen[1], j)
        machines[j] = chosen[2]
    return Chromosome(a, tuple(prefix), tuple(machines))

def initialize(data, seed, config, deadline=None, batch_descent=True, retain_candidates=False):
    """不限时完成五邻域下降；限时中止返回完整编码并明确标注未完成。"""
    config.check()
    begin = time.perf_counter()
    rng = random.Random(seed)
    # 小算例数组开销更高，仍逐个评分；大算例仅改变局部下降的评分批次。
    use_batch = batch_descent and data.n >= 20
    greedy, local = Evaluator(data), Evaluator(data, batch_size=1024 if use_batch else 0)
    fallback = balanced_code(data)
    greedy.cost(fallback)
    if deadline is not None:
        greedy.deadline = local.deadline = deadline
    trace, candidates = [], []
    complete = True
    retained = []
    try:
        for index in range(config.constructions):
            code = greedy_construct(data, greedy, rng, randomized=index > 0)
            raw = greedy.cost(code)
            improved = descend(code, local)
            candidates.append(improved)
            if retain_candidates:
                retained.append((improved, index+1))
            trace.append({'construction': index+1, 'constructed': raw,
                          'after_descent': local.cost(improved)})
        # 构造中已评价的方案也可能更好，对它同样完成下降。
        candidates.append(descend(greedy.best, local))
        if retain_candidates:
            retained.append((candidates[-1], 'greedy_best'))
        best = min(candidates, key=local.cost)
        score = local.cost(best)
    except BudgetExpired:
        complete = False
        # 所有评分均为完整编码；中止时保留已评价最好者，不声称局部最优。
        candidates = [c for c in (greedy.best, local.best) if c is not None]
        best = min(candidates, key=lambda c: evaluate(data, c))
        score = evaluate(data, best)
    info = {'seed': seed, 'greedy_best': greedy.best_cost, 'local_best': score,
                  'seconds': time.perf_counter()-begin, 'trace': trace,
                  'complete': complete, 'batch_descent': use_batch,
                  'termination': 'local_descent_complete' if complete else 'time_budget',
                  'evaluations': greedy.evaluations+local.evaluations,
                  'cache_hits': greedy.cache_hits+local.cache_hits,
                  'code': best.as_dict(), 'local_optimum_kinds':
                  list(('insert_a', 'insert_b', 'flip', 'swap_a', 'swap_b')) if complete else []}
    if retain_candidates:
        # 仅在请求时导出已完成下降的候选；不增加随机数调用或改变原评分顺序。
        unique = {}
        for code, source in retained:
            unique.setdefault(code, {'code': code.as_dict(), 'objective': evaluate(data, code),
                                     'seed': seed, 'construction': source, 'descent_complete': True})
        unique.setdefault(best, {'code': best.as_dict(), 'objective': score, 'seed': seed,
                                'construction': 'best', 'descent_complete': complete})
        info['candidates'] = list(unique.values())
    return best, info

