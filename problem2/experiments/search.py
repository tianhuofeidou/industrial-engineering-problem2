"""迭代贪婪、变邻域下降、模拟退火接受及停滞重启。"""
import math
import random
import time
from dataclasses import dataclass, replace
from problem2.experiments.initialization import initial_solutions
from problem2.experiments.schedule import Solution


@dataclass(frozen=True)
class SearchConfig:
    seconds: float = 10.0
    neighborhood_budget: int = 40
    destroy_count: int = 3
    restart_after: int = 35


@dataclass
class SearchResult:
    solution: Solution
    initial_solution: Solution
    local_solution: Solution
    initial_cost: int
    local_cost: int
    best_cost: int
    seconds: float
    evaluations: int
    iterations: int
    restarts: int
    history: list


def _move(sequence, source, target):
    values = list(sequence)
    job = values.pop(source)
    values.insert(target, job)
    return tuple(values)


def _sample(items, budget, rng):
    return items if len(items) <= budget else rng.sample(items, budget)


def neighbors(solution, kind, evaluator, rng, budget):
    n = evaluator.data.n
    if kind == "front_insert":
        moves = [(i, j) for i in range(n) for j in range(n) if i != j]
        for i, j in _sample(moves, budget, rng):
            yield replace(solution, pi_a=_move(solution.pi_a, i, j))
    elif kind == "front_swap":
        moves = [(i, j) for i in range(n) for j in range(i+1, n)]
        for i, j in _sample(moves, budget, rng):
            order = list(solution.pi_a)
            order[i], order[j] = order[j], order[i]
            yield replace(solution, pi_a=tuple(order))
    elif kind == "queue_insert":
        queues = (solution.q1, solution.q2)
        moves = [(m, i, dest, p) for m in range(2) for i in range(len(queues[m]))
                 for dest in range(2) for p in range(len(queues[dest]) + (dest != m))
                 if m != dest or i != p]
        for m, i, dest, p in _sample(moves, budget, rng):
            q = [list(solution.q1), list(solution.q2)]
            job = q[m].pop(i)
            q[dest].insert(p, job)
            yield replace(solution, q1=tuple(q[0]), q2=tuple(q[1]))
    elif kind == "queue_swap":
        positions = [(m, i) for m, q in enumerate((solution.q1, solution.q2)) for i in range(len(q))]
        moves = [(a, b) for a in range(n) for b in range(a+1, n)]
        for a, b in _sample(moves, budget, rng):
            q = [list(solution.q1), list(solution.q2)]
            m, i = positions[a]
            dest, j = positions[b]
            q[m][i], q[dest][j] = q[dest][j], q[m][i]
            yield replace(solution, q1=tuple(q[0]), q2=tuple(q[1]))
    elif kind == "tie_swap":
        schedule = evaluator.schedule(solution)
        ends = {op.job: op.end for op in schedule.operations if op.station == 6}
        moves = [(i, j) for i in range(n) for j in range(i+1, n)
                 if ends[solution.tie_priority[i]] == ends[solution.tie_priority[j]]]
        for i, j in _sample(moves, budget, rng):
            order = list(solution.tie_priority)
            order[i], order[j] = order[j], order[i]
            yield replace(solution, tie_priority=tuple(order))


def local_search(solution, evaluator, rng, config, deadline):
    kinds = ["front_insert", "queue_insert", "front_swap", "queue_swap", "tie_swap"]
    value = evaluator.cost(solution)
    index = 0
    # 小算例检查全部候选；大算例每类抽样，预算越大检查越充分。
    budget = 10000 if evaluator.data.n <= 7 else config.neighborhood_budget
    while index < len(kinds) and time.perf_counter() < deadline:
        best, best_value = solution, value
        for candidate in neighbors(solution, kinds[index], evaluator, rng, budget):
            if time.perf_counter() >= deadline:
                break
            candidate_value = evaluator.cost(candidate)
            if candidate_value < best_value:
                best, best_value = candidate, candidate_value
        if best_value < value:
            solution, value, index = best, best_value, 0
        else:
            index += 1
    return solution


def reconstruct(solution, evaluator, rng, config, deadline):
    selected = rng.sample(list(solution.pi_a), min(config.destroy_count, evaluator.data.n))
    # 前段移出后，未插回的工件暂置尾部；工位6保持完整，逐步选择插入位置。
    base = tuple(j for j in solution.pi_a if j not in selected)
    pending = list(selected)
    for j in selected:
        if time.perf_counter() >= deadline:
            return solution
        pending.remove(j)
        candidates = [replace(solution, pi_a=base[:p]+(j,)+base[p:]+tuple(pending))
                      for p in range(len(base)+1)]
        solution = min(candidates, key=evaluator.cost)
        base = tuple(k for k in solution.pi_a if k not in pending)
    # 再重插工位6工件；每次移出一个并枚举两台机器的插入位置。
    for j in selected:
        if time.perf_counter() >= deadline:
            break
        a = tuple(k for k in solution.q1 if k != j)
        b = tuple(k for k in solution.q2 if k != j)
        candidates = [replace(solution, q1=a[:p]+(j,)+a[p:], q2=b) for p in range(len(a)+1)]
        candidates += [replace(solution, q1=a, q2=b[:p]+(j,)+b[p:]) for p in range(len(b)+1)]
        solution = min(candidates, key=evaluator.cost)
    return solution


def search(evaluator, seed: int, config: SearchConfig) -> SearchResult:
    if config.seconds <= 0 or config.neighborhood_budget < 1 or config.destroy_count < 1 or config.restart_after < 1:
        raise ValueError("时间及搜索参数必须为正数")
    rng = random.Random(seed)
    start = time.perf_counter()
    deadline = start + config.seconds
    initial = min(initial_solutions(evaluator, rng), key=evaluator.cost)
    initial_cost = evaluator.cost(initial)
    initial_elapsed = time.perf_counter()-start
    local = local_search(initial, evaluator, rng, config, deadline)
    local_cost = evaluator.cost(local)
    current = best = local
    current_cost = best_cost = local_cost
    history = [(initial_elapsed, initial_cost, "initial"),
               (time.perf_counter()-start, local_cost, "local")]
    temperature = max(1.0, initial_cost * 0.015)
    iterations = restarts = stagnant = 0
    while time.perf_counter() < deadline:
        candidate = reconstruct(current, evaluator, rng, config, deadline)
        candidate = local_search(candidate, evaluator, rng, config, deadline)
        cost = evaluator.cost(candidate)
        delta = cost - current_cost
        elapsed_fraction = min(1.0, (time.perf_counter()-start) / config.seconds)
        t = max(0.1, temperature * (1-elapsed_fraction))
        if delta <= 0 or rng.random() < math.exp(-delta/t):
            current, current_cost = candidate, cost
        if cost < best_cost:
            best, best_cost, stagnant = candidate, cost, 0
            history.append((time.perf_counter()-start, cost, "improved"))
        else:
            stagnant += 1
        iterations += 1
        if stagnant >= config.restart_after and time.perf_counter() < deadline:
            a = list(best.pi_a)
            rng.shuffle(a)
            split = rng.randrange(evaluator.data.n+1)
            q = list(a)
            rng.shuffle(q)
            current = Solution(tuple(a), tuple(q[:split]), tuple(q[split:]), best.tie_priority)
            current_cost = evaluator.cost(current)
            if current_cost < best_cost:
                best, best_cost = current, current_cost
                history.append((time.perf_counter()-start, best_cost, "restart_improved"))
            stagnant = 0
            restarts += 1
    elapsed = time.perf_counter()-start
    history.append((elapsed, best_cost, "finished"))
    return SearchResult(best, initial, local, initial_cost, local_cost, best_cost,
                        elapsed, evaluator.evaluations, iterations, restarts, history)
