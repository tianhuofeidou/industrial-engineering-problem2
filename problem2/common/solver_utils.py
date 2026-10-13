"""两个阶段共用的受限模型求解、参考解保留和状态记录。"""
import os
import re
import time
import math
import hashlib
from pathlib import Path
from problem2.common.solver import build_model, extract
from problem2.common.export import export, write_json
from problem2.common.encoding import decode, code_from_result
from problem2.common.validation import validate_exact

def optimize_once(data, reference, restrictions, folder, seconds, threads, strengthen=False,
                  compact=False, solver_env=None, deadline=None):
    import gurobipy as gp
    if folder.exists():
        raise FileExistsError('求解目录已存在')
    folder.mkdir(parents=True)
    warm = decode(data, reference)
    validate_exact(data, warm)
    write_json(folder/'restrictions.json', restrictions.as_dict() if restrictions is not None else {'scope': 'full'})
    original, started = Path.cwd(), time.perf_counter()
    env = model = None
    try:
        os.chdir(folder)
        env, model = build_model(data, warm, folder, seconds, threads, stable_constraints=restrictions,
                                 strengthen=strengthen, compact=compact, solver_env=solver_env)
        # 建模也占总预算；不能把建模前的剩余时间原样当作求解时间。
        if deadline is not None:
            model.Params.TimeLimit = max(0, min(seconds, deadline-time.perf_counter()))
        model.optimize()
        proof = {'scope': 'restricted', 'original_optimality_proven_by_this_run': False,
                 'solver': 'gurobi', 'version': '.'.join(map(str, gp.gurobi.version())),
                 'status': model.Status, 'optimal': model.Status == gp.GRB.OPTIMAL,
                 'runtime': model.Runtime, 'nodes': model.NodeCount,
                 'bound': model.ObjBound, 'solver_objective': model.ObjVal if model.SolCount else None,
                 'gap': model.MIPGap if model.SolCount else None,
                 'seconds_requested': seconds, 'threads': threads, 'reduction': model._reduction,
                 'strengthening': model._strengthening, 'build_timing': model._build_timing,
                 'environment_reused': solver_env is not None}
        if not math.isfinite(proof['bound']):
            proof['bound'] = 0  # 加工时间均为正，0为有效保守下界。
        proof['solver_seconds_limit'] = model.Params.TimeLimit
        if restrictions is None:
            proof['scope'] = 'full'
            proof['original_optimality_proven_by_this_run'] = proof['optimal']
        result = warm
        if model.SolCount:
            def value(name):
                var = model.getVarByName(name)
                if var is not None:
                    return var.X
                return model._fixed_values.get(name, 0)
            solved = extract(data, value)
            solved['validation'] = validate_exact(data, solved)
            code = code_from_result(solved, data.n)
            if restrictions is not None and not restrictions.satisfies(code):
                raise AssertionError('求解结果违反固定关系')
            result = decode(data, code)
            if proof['optimal'] and abs(result['objective']-solved['objective']) > 1e-4:
                raise AssertionError('最优模型结果与同编码解码不一致')
            if result['objective'] > warm['objective']+1e-4:
                raise AssertionError('求解结果劣于参考方案')
            export(folder/'solver_schedule', solved)
            model.write('solution.sol')
            proof['solution_source'] = 'decoded_solver_code'
        else:
            proof['solution_source'] = 'reference_fallback'
        proof['model_sha256'] = hashlib.sha256(Path('model.mps').read_bytes()).hexdigest()
    finally:
        if model is not None:
            model.dispose()
        if env is not None and solver_env is None:
            env.dispose()
        os.chdir(original)
    log = (folder/'solver.log').read_text(encoding='utf-8', errors='replace')
    presolved = re.search(r'Presolved: (\d+) rows, (\d+) columns, (\d+) nonzeros', log)
    proof['presolved'] = dict(zip(('rows', 'columns', 'nonzeros'), map(int, presolved.groups()))) if presolved else None
    proof['total_seconds'] = time.perf_counter()-started
    result['proof'] = proof
    result['validation'] = validate_exact(data, result)
    export(folder, result)
    return result

