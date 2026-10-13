"""共用初始解的变邻域、禁忌、模拟退火与固定代数遗传对照。"""
from problem2.stage1.config import ComparisonConfig
from problem2.stage1.construction import initialize
from problem2.stage1.annealing import run_annealing
from problem2.common.evaluator import Outcome, Recorder
import math
import random
import statistics
import time
from dataclasses import dataclass
from problem2.common.encoding import evaluate
from problem2.experiments.genetic import (Evaluator, SearchConfig, SearchResult, balanced_code,
                      greedy_construct, run_genetic, diverse_archive, BudgetExpired)
from problem2.common.local_search import all_neighbors, descend, perturb, changed_attributes, random_neighbor










def run_vns(data, initial, seed, config, observer=None):
    rng, record = random.Random(seed), Recorder(data, initial, config.archive_size)
    current, level, failures, iterations = initial, 0, 0, 0
    strengths = (2, 3, 4)
    while level < len(strengths):
        shaken = perturb(current, rng, strengths[level])
        candidate = descend(shaken, record.evaluator, observer)
        value = record.evaluator.cost(candidate)
        if observer is not None:
            observer.perturbation(current, shaken, candidate, record.evaluator.cost(current), value)
        record.remember(candidate)
        iterations += 1
        if value < record.evaluator.cost(current):
            current, level, failures = candidate, 0, 0
            if observer is not None:
                observer.accepted(current, value)
        else:
            failures += 1
            if failures == config.vns_failures:
                level, failures = level+1, 0
        record.log(iterations, next_level=level, failures=failures)
    return record.finish(iterations, {'reason': 'all_perturbation_levels_exhausted',
                                     'strengths': list(strengths),
                                     'failures_per_level': config.vns_failures})


def tabu_allowed(requests, tabu, step, cost, historical_best):
    blocked = any(tabu.get(key, 0) > step for key in requests)
    return not blocked or cost < historical_best


def run_tabu(data, initial, seed, config, observer=None):
    rng, record = random.Random(seed), Recorder(data, initial, config.archive_size)
    current, tabu, stall, step, forced = initial, {}, 0, 0, 0
    current_cost = record.evaluator.best_cost
    while stall < config.tabu_stall:
        historical = record.evaluator.best_cost
        chosen = fallback = None
        for candidate in all_neighbors(current):
            value = record.evaluator.cost(candidate)
            requests, undo = changed_attributes(current, candidate)
            tie = rng.random()
            entry = ((value, tie), candidate, undo)
            allowed = tabu_allowed(requests, tabu, step, value, historical)
            if observer is not None:
                observer.trial(current, candidate, current_cost, value, blocked=not allowed)
            if allowed:
                if chosen is None or entry[0] < chosen[0]:
                    chosen = entry
            else:
                expiry = max(tabu.get(key, 0) for key in requests)
                entry = ((expiry, value, tie), candidate, undo)
                if fallback is None or entry[0] < fallback[0]:
                    fallback = entry
        if chosen is None:
            # 所有移动均被禁忌时选择最早解除禁忌的移动，仍记录这次破例。
            chosen, forced = fallback, forced+1
        if chosen is None:
            raise ValueError('没有可用邻居')
        _, current, undo = chosen
        current_cost = chosen[0][-2]
        if observer is not None:
            observer.tabu_selected(current_cost)
            observer.accepted(current, current_cost)
        tenure = rng.randint(3, 7)
        for key in undo:
            tabu[key] = step+tenure+1
        record.remember(current)
        stall = 0 if record.evaluator.best_cost < historical else stall+1
        step += 1
        if step % 100 == 0 or stall == config.tabu_stall:
            record.log(step, stall=stall)
    return record.finish(step, {'reason': 'no_improvement_steps', 'stall': stall,
                               'stall_limit': config.tabu_stall, 'tenure': [3, 7],
                               'all_tabu_fallbacks': forced})




def run_method(method, data, initial, seed, config, observer=None):
    config.check()
    if method == 'genetic':
        if observer is not None:
            raise ValueError('关系记录入口不包含遗传算法')
        cfg = SearchConfig(seconds=float('inf'), population=config.population,
                           generations=config.generations, archive_size=config.archive_size)
        result = run_genetic(data, seed, cfg, initial=initial)
        assert result.generations == config.generations
        return Outcome(result, {'reason': 'fixed_generations', 'generations': result.generations,
                                'population': config.population, 'includes_sampled_local_search': True})
    outcome = {'vns': run_vns, 'tabu': run_tabu, 'annealing': run_annealing}[method](data, initial, seed, config, observer)
    if observer is not None:
        begin = time.perf_counter()
        outcome.evidence = observer.report(outcome.search.best, outcome.search.best_cost)
        outcome.search.seconds += time.perf_counter()-begin
    return outcome
