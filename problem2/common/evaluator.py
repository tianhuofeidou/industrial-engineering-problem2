"""完整编码评分缓存、最好解记录和搜索结果。"""
import time
from itertools import islice
from dataclasses import dataclass
from problem2.common.encoding import Chromosome, evaluate, BatchEvaluator

class BudgetExpired(Exception):
    pass

class Evaluator:
    """缓存评分并记录所有实际评价过的最好完整编码；预算包含初始化。"""
    def __init__(self, data, cache_limit=20000, batch_size=0):
        if batch_size < 0:
            raise ValueError('批次数量不能为负')
        self.data = data
        self.batch_size = batch_size
        self.batch_evaluator = BatchEvaluator(data) if batch_size else None
        self.cache_limit = cache_limit
        self.cache = {}
        self.evaluations = 0
        self.cache_hits = 0
        self.best = None
        self.best_cost = float('inf')
        self.started = time.perf_counter()
        self.deadline = float('inf')
        self.progress = []

    def cost(self, code):
        if time.perf_counter() >= self.deadline:
            raise BudgetExpired
        value = self.cache.get(code)
        if value is None:
            value = evaluate(self.data, code)
            self.evaluations += 1
            if len(self.cache) >= self.cache_limit:
                self.cache.clear()
            self.cache[code] = value
        else:
            self.cache_hits += 1
        if value < self.best_cost:
            self.best, self.best_cost = code, value
            self.progress.append({'seconds': time.perf_counter()-self.started, 'best': value,
                                  'evaluations': self.evaluations})
        return value

    def costs(self, codes):
        """按原邻居顺序返回评分；整批计算后先记录所有已评分的完整编码。"""
        if not self.batch_size:
            for code in codes:
                yield code, self.cost(code)
            return
        iterator = iter(codes)
        while chunk := list(islice(iterator, self.batch_size)):
            if time.perf_counter() >= self.deadline:
                raise BudgetExpired
            existing = {code: self.cache[code] for code in chunk if code in self.cache}
            missing = list(dict.fromkeys(code for code in chunk if code not in existing))
            computed = dict(zip(missing, self.batch_evaluator.evaluate(missing)))
            self.evaluations += len(missing)
            results, reused = [], set(existing)
            for code in chunk:
                value = existing[code] if code in existing else computed[code]
                if code in reused:
                    self.cache_hits += 1
                reused.add(code)
                if code not in self.cache:
                    if len(self.cache) >= self.cache_limit:
                        self.cache.clear()
                    self.cache[code] = value
                if value < self.best_cost:
                    self.best, self.best_cost = code, value
                    self.progress.append({'seconds': time.perf_counter()-self.started, 'best': value,
                                          'evaluations': self.evaluations})
                results.append((code, value))
            # 计算途中截止时，这一批仍先完整记录；下一批开始前停止。
            yield from results

@dataclass
class SearchResult:
    best: Chromosome
    best_cost: int
    archive: list[Chromosome]
    seconds: float
    evaluations: int
    cache_hits: int
    generations: int
    constructions: int
    progress: list[dict]
    generation_history: list[dict]

def distance(first, second):
    return sum(x != y for left, right in zip((first.a, first.b, first.machines),
                                             (second.a, second.b, second.machines))
               for x, y in zip(left, right))

def diverse_archive(pool, values, size):
    """最好个体必留；在不超过最好值5%的个体中优先保留数组差异较大的方案。"""
    unique = sorted(set(pool), key=lambda code: (values[code], code.a, code.b, code.machines))
    if not unique:
        return []
    eligible = [code for code in unique if values[code] <= values[unique[0]]*1.05]
    selected = [eligible.pop(0)]
    while eligible and len(selected) < size:
        index = max(range(len(eligible)), key=lambda i: (
            min(distance(eligible[i], code) for code in selected), -values[eligible[i]], -i))
        selected.append(eligible.pop(index))
    return selected

@dataclass
class Outcome:
    search: SearchResult
    termination: dict
    evidence: dict | None = None

class Recorder:
    def __init__(self, data, initial, size):
        self.evaluator = Evaluator(data)
        self.evaluator.cost(initial)
        self.size = size
        self.codes = {initial: self.evaluator.best_cost}
        self.history = []

    def remember(self, code):
        cost = self.evaluator.cost(code)
        if cost <= self.evaluator.best_cost*1.05:
            self.codes[code] = cost
        if len(self.codes) > self.size*8:
            self.codes[self.evaluator.best] = self.evaluator.best_cost
            selected = diverse_archive(list(self.codes), self.codes, self.size)
            self.codes = {c: self.codes[c] for c in selected}

    def log(self, iteration, **extra):
        self.history.append({'iteration': iteration,
                             'seconds': time.perf_counter()-self.evaluator.started,
                             'best': self.evaluator.best_cost, **extra})

    def finish(self, iterations, termination):
        e = self.evaluator
        self.codes[e.best] = e.best_cost
        archive = diverse_archive(list(self.codes), self.codes, self.size)
        result = SearchResult(e.best, e.best_cost, archive, time.perf_counter()-e.started,
                              e.evaluations, e.cache_hits, 0, 0, e.progress, self.history)
        return Outcome(result, {'iterations': iterations, **termination})

