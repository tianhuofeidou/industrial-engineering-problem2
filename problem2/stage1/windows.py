"""从当前参考解选择连续区间，调用受限Gurobi。"""
import json
import random
import time
from problem2.common.encoding import decode, evaluate, code_from_result
from problem2.common.validation import validate_exact
from problem2.common.export import export, write_json
from problem2.common.solver_utils import optimize_once
from problem2.common.exact_cache import ExactCache
from problem2.stage1.neighborhoods import choose_window, window_constraints

def refine_windows(data, initial, uncertainty, output, budget=120, per_round=5, max_rounds=36,
                   width=5, seed=11, threads=8, compact=False, reuse_env=False, on_round=None,
                   exact_cache=None, cache_enabled=True, deadline=None, adaptive_width=True,
                   selector=None, candidate_provider=None, max_width=None):
    # None preserves the legacy policy, including fixed-width research calls.
    if max_width is not None and (isinstance(max_width, bool) or not isinstance(max_width, int) or max_width < 1):
        raise ValueError('max_width须为正整数或None')
    if candidate_provider is not None and (cache_enabled or exact_cache is not None):
        raise ValueError('候选弧实验禁止使用未包含候选集合的范围缓存')
    import gurobipy as gp
    started = time.perf_counter()
    deadline = min(started+budget, deadline) if deadline is not None else started+budget
    if cache_enabled and exact_cache is None:
        exact_cache = ExactCache()
    env = None
    try:
        if reuse_env:
            env = gp.Env(empty=True)
            env.setParam('OutputFlag', 0)
            env.start()
        return _refine_windows(data, initial, uncertainty, output, budget, per_round, max_rounds,
                               width, seed, threads, compact, env, started, on_round,
                               exact_cache if cache_enabled else None, deadline, adaptive_width, selector, candidate_provider, max_width)
    finally:
        if env is not None:
            env.dispose()

def _refine_windows(data, initial, uncertainty, output, budget, per_round, max_rounds,
                    width, seed, threads, compact, solver_env, started, on_round, exact_cache, deadline,
                    adaptive_width=True, selector=None, candidate_provider=None, max_width=None):
    current, cost = initial, evaluate(data, initial)
    seen, records, rng = set(), [], random.Random(seed)
    width = min(width, max(1, data.n-1))
    cap = min(9 if max_width is None else max_width, max(1, data.n-1))
    if max_width is not None:
        width = min(width, cap)
    failures = 0
    for iteration in range(max_rounds):
        remaining = deadline-time.perf_counter()
        if remaining <= 0.1:
            break
        # 实验可替换区间选择，模型、解码、接受与默认选择规则保持共用。
        chooser = choose_window if selector is None else selector
        choice = chooser(data, current, width, uncertainty, seen, iteration, rng)
        if choice is None:
            if not adaptive_width or width >= (min(9, data.n-1) if max_width is None else cap):
                break
            width = min(width+2, data.n-1) if max_width is None else min(width+2, cap)
            continue
        a, b, policy = choice
        restriction = window_constraints(current, a, b, width)
        before = cost
        remaining = deadline-time.perf_counter()
        if remaining <= 0.1:
            break
        solver = optimize_once if exact_cache is None else lambda *a, **kw: exact_cache.solve(optimize_once, *a, **kw)
        options = {} if candidate_provider is None else {'candidate_arcs': candidate_provider(current)}
        result = solver(data, current, restriction, output/f'round{iteration+1:03d}',
                        min(per_round, remaining), threads, strengthen=True,
                        compact=compact, solver_env=solver_env, deadline=deadline, **options)
        if result['objective'] < cost:
            current, cost = code_from_result(result, data.n), result['objective']
            failures = 0
        else:
            failures += 1
        row = {'round': iteration+1, 'before': before, 'after': cost, 'window_a': a, 'window_b': b,
               'width': width, 'policy': policy, 'proof': result['proof'],
               'elapsed_seconds': time.perf_counter()-started}
        records.append(row)
        if on_round is not None:
            on_round(current, row)
        print(json.dumps({'phase': 'window', 'case': data.case, 'round': iteration+1,
                          'before': before, 'after': cost, 'width': width,
                          'binaries': result['proof']['reduction']['binary_variables'],
                          'runtime': result['proof']['runtime'], 'status': result['proof']['status']}), flush=True)
        write_json(output/'checkpoint.json', {'complete': False, 'best': cost, 'records': records})
        # 固定宽度仅供对照实验；正式入口默认继续使用原来的扩大、缩小规则。
        if adaptive_width and failures >= 6 and all(r['proof']['optimal'] for r in records[-3:]):
            width = min(width+2, cap)
            failures = 0
        elif adaptive_width and not result['proof']['optimal'] and cost == before and width > 3:
            width -= 2
    final = decode(data, current)
    final['validation'] = validate_exact(data, final)
    final['refinement'] = {'scope': 'restricted', 'original_optimality_proven_by_this_run': False,
                           'before': evaluate(data, initial), 'after': cost,
                           'seconds': time.perf_counter()-started, 'records': records,
                           'adaptive_width': adaptive_width, 'max_width': max_width,
                           'cache_hits': sum(r['proof'].get('cache_hit', False) for r in records),
                           'actual_solver_calls': sum(not r['proof'].get('cache_hit', False) for r in records)}
    export(output/'final', final)
    write_json(output/'checkpoint.json', {'complete': True, 'best': cost, 'records': records})
    return final

