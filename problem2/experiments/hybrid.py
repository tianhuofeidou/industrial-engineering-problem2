"""Case 1 受限精确优化：固定未选中工件的相对顺序和机器归属。"""
import hashlib
import json
import os
import itertools
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from problem2.common.encoding import decode, code_from_result
from problem2.common.solver import build_model, extract, export
from problem2.common.validation import validate_exact
from problem2.common.restrictions import select_free_jobs, make_restriction, satisfies


def refine(data, search_result, output, free_count=3, seconds=10, threads=8, free_jobs=None):
    if data.case != 1 or data.n != 7:
        raise ValueError('受限商业求解器仅允许题目2 Case 1；Case 2只运行启发式')
    if (seconds is not None and seconds <= 0) or threads < 1:
        raise ValueError('求解预算和线程数必须为正数')
    import gurobipy as gp
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('受限求解输出目录已存在，拒绝覆盖')
    start = perf_counter()
    reference = search_result.best
    if free_jobs is None:
        free, disagreements = select_free_jobs(reference, search_result.archive, free_count)
    else:
        restriction_check = make_restriction(reference, free_jobs)
        free, disagreements = restriction_check.free_jobs, None
    restriction = make_restriction(reference, free)
    assert satisfies(reference, restriction)
    warm = decode(data, reference)
    validate_exact(data, warm)
    output.mkdir(parents=True)
    constraints = {**restriction.as_dict(), 'disagreements': disagreements,
                   'reference_code': reference.as_dict(), 'reference_objective': warm['objective'],
                   'archive': [code.as_dict() for code in search_result.archive]}
    (output/'restrictions.json').write_text(json.dumps(constraints, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'phase': 'restricted_model', 'warm': warm['objective'],
                      'free_jobs': list(free), 'fixed_constraints':
                      len(restriction.fixed_machines)+len(restriction.fixed_orders)}), flush=True)
    original = Path.cwd()
    env = model = None
    try:
        os.chdir(output)
        env, model = build_model(data, warm, output, seconds, threads, free_jobs=free)
        model.optimize()
        scope = 'original' if len(free) == data.n else 'restricted'
        meta = {'solver': 'gurobi', 'version': '.'.join(map(str, gp.gurobi.version())),
                'scope': scope, 'status': model.Status, 'optimal': model.Status == gp.GRB.OPTIMAL,
                'bound': model.ObjBound, 'gap': model.MIPGap if model.SolCount else None,
                'runtime': model.Runtime, 'nodes': model.NodeCount,
                'seconds_requested': seconds, 'threads': threads,
                'free_jobs': list(free), 'original_optimality_proven_by_this_run':
                scope == 'original' and model.Status == gp.GRB.OPTIMAL}
        if model.SolCount:
            result = extract(data, lambda name: model.getVarByName(name).X)
            model.write('solution.sol')
            assert result['objective'] <= warm['objective']+1e-4
            assert satisfies(code_from_result(result, data.n), restriction)
            if meta['optimal']:
                assert abs(result['objective']-meta['bound']) <= 1e-4
            meta['solution_source'] = 'solver'
        else:
            # 求解器无可用解时保留已验证的参考方案；状态和下界仍如实记录。
            result = warm
            meta['solution_source'] = 'heuristic_fallback'
        meta['model_sha256'] = hashlib.sha256(Path('model.mps').read_bytes()).hexdigest()
    finally:
        if model is not None:
            model.dispose()
        if env is not None:
            env.dispose()
        os.chdir(original)
    result['validation'] = validate_exact(data, result)
    meta['total_refinement_seconds'] = perf_counter()-start
    meta['total_search_and_refinement_seconds'] = search_result.seconds+meta['total_refinement_seconds']
    result['proof'] = meta
    export(output, result)
    return result


def refine_until_stable(data, search_result, output, threads=8, on_step=None):
    """不限时求解所有三工件组合；改善后还须完成一轮无改善检查。"""
    if data.case != 1 or data.n != 7:
        raise ValueError('范围轮换仅允许题目2 Case 1')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('范围轮换输出目录已存在，拒绝覆盖')
    output.mkdir(parents=True)
    started = perf_counter()
    current, value = search_result.best, search_result.best_cost
    records, passes = [], 0
    while True:
        passes += 1
        improved = False
        for free in itertools.combinations(range(data.n), 3):
            folder = output/f'pass{passes:02d}'/('free_'+'_'.join(str(j+1) for j in free))
            before = value
            reference = replace(search_result, best=current, best_cost=value)
            result = refine(data, reference, folder, seconds=None, threads=threads, free_jobs=free)
            if not result['proof']['optimal'] or result['proof']['solution_source'] != 'solver':
                raise RuntimeError('不限时受限模型未证明最优；保留现场，不报告范围搜索完成')
            trial = code_from_result(result, data.n)
            decoded = decode(data, trial)
            if abs(decoded['objective']-result['objective']) > 1e-4:
                raise AssertionError('受限最优值与同编码最早可行调度不一致')
            if decoded['objective'] < value:
                current, value, improved = trial, decoded['objective'], True
            item = {'pass': passes, 'free_jobs': list(free), 'before': before,
                    'range_optimum': result['objective'], 'best_after': value,
                    'proof': result['proof'],
                    'result': str((folder/'result.json').relative_to(output)).replace('\\', '/')}
            records.append(item)
            checkpoint = {'passes': passes, 'models': len(records), 'best': value,
                          'code': current.as_dict(), 'complete': False, 'records': records}
            (output/'rotation.json').write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding='utf-8')
            if on_step is not None:
                on_step(item, len(records))
        if not improved:
            break
    final = decode(data, current)
    final['validation'] = validate_exact(data, final)
    seconds = perf_counter()-started
    final['rotation'] = {'passes': passes, 'models': len(records), 'seconds': seconds,
                         'initial_objective': search_result.best_cost,
                         'termination': 'complete_pass_without_improvement',
                         'three_job_local_optimum_proven': True,
                         'original_optimality_proven_by_this_run': False,
                         'scope': 'restricted', 'threads': threads, 'time_limit': None}
    export(output/'final', final)
    (output/'rotation.json').write_text(json.dumps(
        {'complete': True, **final['rotation'], 'code': current.as_dict(), 'best': value,
         'records': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    return final
