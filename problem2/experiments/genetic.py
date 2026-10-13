"""贪心构造初始个体、遗传搜索和优秀个体保留；不调用商业求解器。"""
from problem2.common.evaluator import BudgetExpired, Evaluator, SearchResult, distance, diverse_archive
from problem2.stage1.construction import balanced_code, greedy_construct
import random
import time
from itertools import islice
from dataclasses import dataclass
from problem2.common.data import m62_duration
from problem2.common.encoding import Chromosome, evaluate, BatchEvaluator






@dataclass(frozen=True)
class SearchConfig:
    seconds: float = 10
    population: int = 60
    generations: int | None = None
    archive_size: int = 12
    mutation_rate: float = 0.35
    local_candidates: int = 80

    def check(self):
        if self.seconds <= 0 or self.population < 6 or self.archive_size < 1:
            raise ValueError('预算须为正数，种群至少6个，保留个体数至少1')
        if self.generations is not None and self.generations < 0:
            raise ValueError('代数不得为负数')
        if not 0 <= self.mutation_rate <= 1 or self.local_candidates < 0:
            raise ValueError('变异概率须在0到1之间，局部候选数不得为负数')






def random_code(n, rng):
    a, b = list(range(n)), list(range(n))
    rng.shuffle(a)
    rng.shuffle(b)
    return Chromosome(tuple(a), tuple(b), tuple(rng.randrange(2) for _ in range(n)))




def ordered_crossover(first, second, rng):
    """顺序交叉：保留一段，再按另一亲本的循环顺序填入未出现工件。"""
    n = len(first)
    left, right = sorted(rng.sample(range(n+1), 2))
    child = [None]*n
    child[left:right] = first[left:right]
    used = set(first[left:right])
    remaining = [j for j in second[right:]+second[:right] if j not in used]
    positions = list(range(right, n))+list(range(left))
    for index, j in zip(positions, remaining):
        child[index] = j
    return tuple(child)


def crossover(first, second, rng):
    return Chromosome(ordered_crossover(first.a, second.a, rng),
                      ordered_crossover(first.b, second.b, rng),
                      tuple(rng.choice((m1, m2)) for m1, m2 in zip(first.machines, second.machines)))


def mutate(code, rng, rate=0.35):
    permutations = []
    for original in (code.a, code.b):
        order = list(original)
        if len(order) > 1 and rng.random() < rate:
            i, j = rng.sample(range(len(order)), 2)
            if rng.random() < 0.5:
                order[i], order[j] = order[j], order[i]
            else:
                order.insert(j, order.pop(i))
        permutations.append(tuple(order))
    machines = list(code.machines)
    if rng.random() < rate:
        j = rng.randrange(len(machines))
        machines[j] = 1-machines[j]
    return Chromosome(*permutations, tuple(machines))


def local_improve(code, evaluator, rng, limit):
    """随机取少量交换、插入和机器翻转，返回其中最好编码。"""
    n = len(code.a)
    moves = [('flip', 0, j, j) for j in range(n)]
    moves += [('swap', which, i, j) for which in (0, 1)
              for i in range(n) for j in range(i+1, n)]
    moves += [('insert', which, i, j) for which in (0, 1)
              for i in range(n) for j in range(n) if i != j]
    rng.shuffle(moves)
    best, value = code, evaluator.cost(code)
    for kind, which, i, j in moves[:limit]:
        a, b, machines = list(code.a), list(code.b), list(code.machines)
        if kind == 'flip':
            machines[j] = 1-machines[j]
        else:
            order = a if which == 0 else b
            if kind == 'swap':
                order[i], order[j] = order[j], order[i]
            else:
                order.insert(j, order.pop(i))
        trial = Chromosome(tuple(a), tuple(b), tuple(machines))
        cost = evaluator.cost(trial)
        if cost < value:
            best, value = trial, cost
    return best






def _result(evaluator, archive, generations, constructions, history):
    # 在预算截止后只整理已知评分，不再调用有截止检查的 cost。
    return SearchResult(evaluator.best, evaluator.best_cost, archive,
                        time.perf_counter()-evaluator.started, evaluator.evaluations,
                        evaluator.cache_hits, generations, constructions,
                        evaluator.progress, history)


def run_greedy(data, seed, config):
    config.check()
    rng = random.Random(seed)
    evaluator = Evaluator(data)
    evaluator.cost(balanced_code(data))
    evaluator.deadline = evaluator.started+config.seconds
    constructions = 0
    try:
        while True:
            code = greedy_construct(data, evaluator, rng, randomized=constructions > 0)
            evaluator.cost(code)
            constructions += 1
    except BudgetExpired:
        pass
    return _result(evaluator, [evaluator.best], 0, constructions, [])


def run_genetic(data, seed, config, initial=None):
    config.check()
    rng = random.Random(seed)
    evaluator = Evaluator(data)
    evaluator.cost(balanced_code(data) if initial is None else initial)
    evaluator.deadline = evaluator.started+config.seconds
    values = {evaluator.best: evaluator.best_cost}
    population, archive, history = [], [evaluator.best], []
    constructions = generations = 0

    def score(code):
        value = evaluator.cost(code)
        values[code] = value
        return value

    try:
        if initial is None:
            for index in range(min(8, config.population//3)):
                code = greedy_construct(data, evaluator, rng, randomized=index > 0)
                score(code)
                population.append(code)
                constructions += 1
        else:
            # 对照入口提供已经完成局部下降的共同初始解；种群构造计入遗传耗时。
            population.append(initial)
        while len(population) < config.population:
            code = (random_code(data.n, rng) if len(population) % 2
                    else mutate(evaluator.best, rng, 1.0))
            score(code)
            population.append(code)
        elite_count = max(2, config.population//10)
        immigrants = max(1, config.population//10)
        while config.generations is None or generations < config.generations:
            score(evaluator.best)
            population.append(evaluator.best)
            population.sort(key=values.__getitem__)
            archive = diverse_archive(archive+population[:24], values, config.archive_size)
            history.append({'generation': generations, 'seconds': time.perf_counter()-evaluator.started,
                            'best': evaluator.best_cost, 'population_best': values[population[0]],
                            'unique': len(set(population)), 'archive': len(archive)})
            next_population = list(dict.fromkeys(population))[:elite_count]
            seen = set(next_population)
            attempts = 0
            while len(next_population) < config.population-immigrants:
                def parent():
                    return min(rng.sample(population, 3), key=values.__getitem__)
                child = mutate(crossover(parent(), parent(), rng), rng, config.mutation_rate)
                attempts += 1
                if child in seen and attempts < config.population*8:
                    continue
                score(child)
                next_population.append(child)
                seen.add(child)
            for _ in range(immigrants):
                child = random_code(data.n, rng)
                score(child)
                next_population.append(child)
            if generations % 10 == 9:
                # 仅靠完全随机个体容易被选择淘汰；定期补入有质量差异的贪心构造。
                fresh = greedy_construct(data, evaluator, rng, randomized=True)
                score(fresh)
                next_population[-1] = fresh
                constructions += 1
            if config.local_candidates:
                best_new = min(next_population, key=values.__getitem__)
                improved = local_improve(best_new, evaluator, rng, config.local_candidates)
                score(improved)
                next_population[-1] = improved
            population = next_population
            generations += 1
            # 仅保留当前种群、历史候选和最好个体的评分，避免长时间搜索无限占内存。
            keep = set(population+archive+[evaluator.best])
            values[evaluator.best] = evaluator.best_cost
            values = {code: values[code] for code in keep}
    except BudgetExpired:
        pass
    values[evaluator.best] = evaluator.best_cost
    candidates = archive+[code for code in population if code in values]+[evaluator.best]
    archive = diverse_archive(candidates, values, config.archive_size)
    return _result(evaluator, archive, generations, constructions, history)
