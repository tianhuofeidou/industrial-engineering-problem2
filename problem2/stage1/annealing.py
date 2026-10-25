"""模拟退火：随机移动、温度校准、接受和全程最好解保留。"""
import math
import random
import statistics
import time
from problem2.common.evaluator import Recorder
from problem2.common.local_search import all_neighbors, random_neighbor

def run_annealing(data, initial, seed, config, observer=None, deadline=None, on_event=None, process=None):
    rng, record = random.Random(seed), Recorder(data, initial, config.archive_size)
    current, cost = initial, record.evaluator.cost(initial)
    # 可选过程记录只读取已产生的决策；关闭时不创建过程文件。
    if process is not None:
        process.start(initial, cost, record.evaluator)
    def finish(iterations, details):
        outcome = record.finish(iterations, details)
        if process is not None:
            process.finish(outcome)
        return outcome
    last_operation = None
    def remember_operation(operation):
        nonlocal last_operation
        last_operation = operation
        if observer is not None and hasattr(observer, 'operation'):
            observer.operation(operation)
    if deadline is not None and time.perf_counter() >= deadline:
        return finish(0, {'reason': 'time_budget', 'levels': 0,
                                'calibration_complete': False, 'accepted': 0, 'uphill_accepted': 0})
    candidates = list(all_neighbors(initial))
    # 仅用当前邻域分数估计初温，不读取5031；校准评价计入退火耗时和次数。
    sample = rng.sample(candidates, min(64, len(candidates)))
    positive = []
    for candidate in sample:
        if deadline is not None and time.perf_counter() >= deadline:
            return finish(0, {'reason': 'time_budget', 'levels': 0,
                                    'calibration_complete': False, 'accepted': 0, 'uphill_accepted': 0})
        previous_best = record.evaluator.best_cost
        value = record.evaluator.cost(candidate)
        delta = value-cost
        if process is not None:
            process.calibration(initial, candidate, cost, value, previous_best, record.evaluator)
        if delta > 0:
            positive.append(delta)
    calibrated_temperature = statistics.median(positive)/(-math.log(0.8)) if positive else 1.0
    initial_temperature = calibrated_temperature*config.sa_temperature_multiplier
    if observer is not None:
        observer.initial_temperature = initial_temperature
    temperature, levels, steps, accepted, uphill_accepted = initial_temperature, 0, 0, 0, 0
    reason = 'temperature_floor'
    if on_event is not None:
        on_event('calibration', record.evaluator.best, {'temperature': temperature,
                 'calibrated_temperature': calibrated_temperature, 'current': cost,
                 'best': record.evaluator.best_cost, 'steps': steps})
    # 提高初温后仍降到原校准温度对应的低温，不把终止温度一起抬高。
    while temperature >= calibrated_temperature*config.sa_ratio:
        for _ in range(config.sa_moves):
            if deadline is not None and steps % 64 == 0 and time.perf_counter() >= deadline:
                reason = 'time_budget'
                break
            # 五种邻域的所有具体操作等概率抽取。
            before, before_cost = current, cost
            if process is not None:
                candidate = random_neighbor(current, rng, on_operation=remember_operation)
            elif observer is not None and hasattr(observer, 'operation'):
                candidate = random_neighbor(current, rng, on_operation=observer.operation)
            else:
                candidate = random_neighbor(current, rng)
            previous_best = record.evaluator.best_cost
            value = record.evaluator.cost(candidate)
            if on_event is not None and value < previous_best:
                on_event('improvement', record.evaluator.best, {'temperature': temperature,
                         'best': value, 'current': cost, 'steps': steps+1})
            delta = value-cost
            if observer is not None:
                observer.trial(current, candidate, cost, value, temperature=temperature)
            if process is None:
                take = delta <= 0 or rng.random() < math.exp(-delta/temperature)
            else:
                probability = 1.0 if delta <= 0 else math.exp(-delta/temperature)
                draw = None if delta <= 0 else rng.random()
                take = delta <= 0 or draw < probability
            if take:
                current, cost = candidate, value
                if observer is not None:
                    observer.accepted(current, cost)
                accepted += 1
                uphill_accepted += int(delta > 0)
                record.remember(current)
            if process is not None:
                process.trial_result(before, candidate, before_cost, value, steps+1,
                                     temperature, last_operation, take, probability,
                                     draw, previous_best, record.evaluator)
            steps += 1
        if reason == 'time_budget':
            break
        levels += 1
        record.log(steps, temperature=temperature, accepted=accepted,
                   current=cost, uphill_accepted=uphill_accepted)
        if on_event is not None:
            on_event('temperature_level', record.evaluator.best, {'temperature': temperature,
                     'current': cost, 'best': record.evaluator.best_cost, 'steps': steps,
                     'accepted': accepted, 'uphill_accepted': uphill_accepted, 'level': levels})
        temperature *= config.sa_cooling
    return finish(steps, {'reason': reason, 'levels': levels,
                                'initial_temperature': initial_temperature,
                                'calibrated_temperature': calibrated_temperature,
                                'temperature_multiplier': config.sa_temperature_multiplier,
                                'final_temperature': temperature,
                                'temperature_ratio': config.sa_ratio,
                                'cooling': config.sa_cooling, 'moves_per_temperature': config.sa_moves,
                                'accepted': accepted, 'uphill_accepted': uphill_accepted})

