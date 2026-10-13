"""由排列、两条队列和并列优先级计算最早可行时间表。"""
from dataclasses import dataclass
from problem2.common.data import CaseData, m62_duration


@dataclass(frozen=True)
class Solution:
    pi_a: tuple[int, ...]
    q1: tuple[int, ...]
    q2: tuple[int, ...]
    tie_priority: tuple[int, ...]


@dataclass(frozen=True)
class Operation:
    job: int
    station: int
    machine: str
    predecessor: int | None
    arrival: int
    setup_start: int
    setup_end: int
    start: int
    end: int
    processing: int


@dataclass(frozen=True)
class Schedule:
    solution: Solution
    pi_b: tuple[int, ...]
    operations: tuple[Operation, ...]
    makespan: int


def check_solution(solution: Solution, n: int):
    expected = list(range(n))
    if sorted(solution.pi_a) != expected or sorted(solution.q1 + solution.q2) != expected:
        raise ValueError("前段排列及工位6两条队列均必须包含每个工件恰一次")
    if sorted(solution.tie_priority) != expected:
        raise ValueError("并列优先级必须是全部工件的排列")


class Evaluator:
    def __init__(self, data: CaseData, cache_limit=12000):
        self.data = data
        self.cache_limit = cache_limit
        self.cost_cache = {}
        self.front_cache = {}
        self.evaluations = 0

    def cost(self, solution: Solution) -> int:
        cached = self.cost_cache.get(solution)
        if cached is not None:
            return cached
        value = self._calculate(solution, detail=False)
        self.evaluations += 1
        if len(self.cost_cache) >= self.cache_limit:
            self.cost_cache.clear()
        self.cost_cache[solution] = value
        return value

    def schedule(self, solution: Solution) -> Schedule:
        check_solution(solution, self.data.n)
        return self._calculate(solution, detail=True)

    def _calculate(self, solution, detail):
        data = self.data
        n = data.n
        completions = [[0]*10 for _ in range(n)]
        operations = []

        def queue(sequence, k, machine, slow=False):
            previous = None
            machine_end = 0
            for j in sequence:
                arrival = 0 if k == 0 else completions[j][k-1]
                setup = 0 if previous is None else data.setup[previous][j]
                # 等机器空闲且后件到达后才换模；每条队列首件均无换模。
                setup_start = max(machine_end, arrival)
                start = setup_start + setup
                duration = data.processing[j][k]
                if slow:
                    duration = m62_duration(duration)
                end = start + duration
                completions[j][k] = end
                if detail:
                    operations.append(Operation(j, k+1, machine, previous, arrival,
                                                setup_start, start, start, end, duration))
                previous, machine_end = j, end

        front = None if detail else self.front_cache.get(solution.pi_a)
        if front is None:
            for k in range(5):
                queue(solution.pi_a, k, str(k+1))
            if not detail:
                if len(self.front_cache) >= 1000:
                    self.front_cache.clear()
                self.front_cache[solution.pi_a] = tuple(tuple(c[:5]) for c in completions)
        else:
            for j in range(n):
                completions[j][:5] = front[j]
        queue(solution.q1, 5, "6-1")
        queue(solution.q2, 5, "6-2", slow=True)
        rank = {j: r for r, j in enumerate(solution.tie_priority)}
        # 优先级只用于同时完工；严格更早完工的工件始终在前。
        pi_b = tuple(sorted(range(n), key=lambda j: (completions[j][5], rank[j])))
        for k in range(6, 10):
            queue(pi_b, k, str(k+1))
        makespan = max(c[9] for c in completions)
        if detail:
            return Schedule(solution, pi_b, tuple(operations), makespan)
        return makespan
