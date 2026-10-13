"""Case 1 一般模型的精确求解。Gurobi 建模，COPT 读取同一份 MPS 复核。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
from problem2.common.export import export
import argparse
import csv
import colorsys
import hashlib
import json
import os
import random
import time
from importlib.metadata import version
from pathlib import Path
from problem2.common.data import load_case, m62_duration
from problem2.common.validation import validate_exact
from problem2.common.encoding import Chromosome, decode as decode_code, make_result, code_from_result
from problem2.common.restrictions import make_restriction


def decode(data, a, b, machines):
    """保留精确入口的调用格式，时间递推统一由 encoding 模块实现。"""
    return decode_code(data, Chromosome(tuple(a), tuple(b), tuple(machines)))


def warm_start(data):
    """小规模确定预算的局部搜索，只提供上界和初始解，不固定精确模型变量。"""
    rng = random.Random(20261010)
    best = decode(data, list(range(data.n)), list(range(data.n)), [0]*data.n)
    for restart in range(12):
        a, b = list(range(data.n)), list(range(data.n))
        if restart:
            rng.shuffle(a)
            rng.shuffle(b)
        machines = [rng.randrange(2) for _ in a]
        value = decode(data, a, b, machines)
        changed = True
        while changed:
            changed = False
            candidates = []
            for which in (0, 1):
                for i in range(data.n):
                    for j in range(i+1, data.n):
                        aa, bb = a[:], b[:]
                        target = aa if which == 0 else bb
                        target[i], target[j] = target[j], target[i]
                        candidates.append((aa, bb, machines))
            for j in range(data.n):
                mm = machines[:]
                mm[j] = 1-mm[j]
                candidates.append((a, b, mm))
            for aa, bb, mm in candidates:
                trial = decode(data, aa, bb, mm)
                if trial['objective'] < value['objective']:
                    a, b, machines, value = aa, bb, mm, trial
                    changed = True
            if value['objective'] < best['objective']:
                best = value
    validate_exact(data, best)
    return best


def build_model(data, warm, folder, seconds, threads, free_jobs=None, stable_constraints=None, strengthen=False,
                compact=False, solver_env=None):
    import gurobipy as gp
    from gurobipy import GRB
    build_started = time.perf_counter()
    timing = {}
    env = solver_env
    if env is None:
        env = gp.Env(empty=True)
        env.setParam('OutputFlag', 0)
        env.start()
    timing['environment_seconds'] = time.perf_counter()-build_started
    model = gp.Model('problem2_case1_general', env=env)
    model.Params.OutputFlag = 1
    model.Params.LogToConsole = 0
    # 本机原生求解器不能写含中文的绝对路径；在输出目录内使用 ASCII 相对名。
    model.Params.LogFile = 'solver.log'
    if seconds is not None:
        model.Params.TimeLimit = seconds
    model.Params.MIPGap = 0
    model.Params.MIPGapAbs = 0
    model.Params.Threads = threads
    if stable_constraints is not None and free_jobs is not None:
        raise ValueError('稳定关系与旧放开工件接口不能同时使用')
    fixed_values = {}
    machines, orders, fixed_arcs = ({}, {}, {})
    if stable_constraints is not None:
        if not stable_constraints.satisfies(code_from_result(warm, data.n)):
            raise ValueError('固定约束排除了参考初始解')
        machines, orders, fixed_arcs = stable_constraints.decisions()
    original_fixed_arcs = len(fixed_arcs)
    if strengthen and stable_constraints is not None:
        from problem2.common.stable_constraints import propagated_decisions
        machines, orders, fixed_arcs = propagated_decisions(data.n, machines, orders, fixed_arcs)
    timing['decisions_seconds'] = time.perf_counter()-build_started-timing['environment_seconds']

    def binary(name, fixed=None):
        if fixed is not None:
            fixed_values[name] = fixed
            return fixed
        return model.addVar(vtype=GRB.BINARY, name=name)

    h = warm['objective']
    # 单个工件必须经历的加工时长给出时间上下界；工位6取较快的机器。
    lb_s = {(j, k): sum(data.processing[j][:k]) for j in range(data.n) for k in range(10)}
    ub_c = {(j, k): h-sum(data.processing[j][k+1:]) for j in range(data.n) for k in range(10)}
    lb_c = {(j, k): lb_s[j, k]+data.processing[j][k] for j in range(data.n) for k in range(10)}
    ub_s = {(j, k): ub_c[j, k]-data.processing[j][k] for j in range(data.n) for k in range(10)}
    objective_lower = 0
    if strengthen:
        from problem2.common.time_bounds import time_bounds
        lb_s, lb_c, ub_s, ub_c, objective_lower = time_bounds(data, h, machines, orders, fixed_arcs)
    bounds_finished = time.perf_counter()
    timing['bounds_seconds'] = bounds_finished-build_started-sum(timing.values())
    s = {(j, k): model.addVar(lb=lb_s[j, k], ub=ub_s[j, k], name=f'S_{j}_{k}')
         for j in range(data.n) for k in range(10)}
    c = {(j, k): model.addVar(lb=lb_c[j, k], ub=ub_c[j, k], name=f'C_{j}_{k}')
         for j in range(data.n) for k in range(10)}
    x = {(j, m): binary(f'x_{j}_{m}', int(machines[j] == m) if j in machines else None)
         for j in range(data.n) for m in range(2)}
    arcs = {}
    source, sink = -1, data.n
    for q in ('A', 'B', '6-1', '6-2'):
        edges = [(source, j) for j in range(data.n)]+[(j, sink) for j in range(data.n)]
        edges += [(i, j) for i in range(data.n) for j in range(data.n) if i != j]
        if q.startswith('6'):
            edges.append((source, sink))
        constants = {}
        if stable_constraints is not None:
            from problem2.common.stable_constraints import arc_constants
            edges, constants = arc_constants(data.n, q, machines, orders, fixed_arcs, strengthen)
        arcs[q] = {}
        for i, j in edges:
            var = binary(f'z_{q}_{i}_{j}', constants.get((i, j)))
            if not isinstance(var, int) or var:
                arcs[q][i, j] = var
        model.addConstr(gp.quicksum(v for (i, j), v in arcs[q].items() if i == source) == 1)
        model.addConstr(gp.quicksum(v for (i, j), v in arcs[q].items() if j == sink) == 1)
        for j in range(data.n):
            membership = x[j, int(q[-1])-1] if q.startswith('6') else 1
            model.addConstr(gp.quicksum(v for (i, jj), v in arcs[q].items() if jj == j) == membership)
            model.addConstr(gp.quicksum(v for (ii, t), v in arcs[q].items() if ii == j) == membership)
    for j in range(data.n):
        if j not in machines:
            model.addConstr(x[j, 0]+x[j, 1] == 1)
        for k in range(10):
            p = data.processing[j][k]
            if k == 5:
                p = p*x[j, 0]+m62_duration(p)*x[j, 1]
            model.addConstr(c[j, k] == s[j, k]+p)
            if k:
                model.addConstr(s[j, k] >= c[j, k-1])
        model.addConstr(s[j, 0] <= h*(1-arcs['A'].get((source, j), 0)))
    for q in arcs:
        stages = range(5) if q == 'A' else range(6, 10) if q == 'B' else [5]
        for (i, j), z in arcs[q].items():
            if i < 0 or j == sink:
                continue
            setup = data.setup[i][j]
            for k in stages:
                big_m = max(0, ub_c[i, k]+setup-lb_s[j, k])
                model.addConstr(s[j, k] >= c[i, k]+setup-big_m*(1-z))
                if k:
                    big_m = max(0, ub_c[j, k-1]+setup-lb_s[j, k])
                    model.addConstr(s[j, k] >= c[j, k-1]+setup-big_m*(1-z))
            if q == 'B':
                big_m = max(0, ub_c[i, 5]-lb_c[j, 5])
                model.addConstr(c[j, 5] >= c[i, 5]-big_m*(1-z))
    # 连续位置变量及两两先后变量加强排列的松弛；时间约束也独立排除子回路。
    pairs_started = time.perf_counter()
    timing['variables_and_arcs_seconds'] = pairs_started-bounds_finished
    skipped_fixed_pairs = 0
    for q in ('A', 'B'):
        # 保持原位置界，避免额外改变预处理及分支路径；这里只省略由变量界保证的约束。
        pos_bounds = {j: (0, data.n-1) for j in range(data.n)}
        pos = {j: model.addVar(lb=pos_bounds[j][0], ub=pos_bounds[j][1], name=f'pos_{q}_{j}')
               for j in range(data.n)}
        for (i, j), z in arcs[q].items():
            if i >= 0 and j < sink:
                model.addConstr(pos[j] >= pos[i]+1-data.n*(1-z))
        stages = range(5) if q == 'A' else range(6, 10)
        for i in range(data.n):
            for j in range(i+1, data.n):
                order = binary(f'order_{q}_{i}_{j}', orders.get((q, i, j)))
                if compact and isinstance(order, int):
                    before, after = (i, j) if order else (j, i)
                    if pos_bounds[before][1] >= pos_bounds[after][0]:
                        model.addConstr(pos[after] >= pos[before]+1)
                    # 保留固定方向的时间约束以加强线性松弛；另一方向已由变量界保证，
                    # 无需生成。若当前方向也由上下界保证成立，则同样省略。
                    for k in stages:
                        if lb_s[after, k] < ub_c[before, k]:
                            model.addConstr(s[after, k] >= c[before, k])
                    if q == 'B' and lb_c[after, 5] < ub_c[before, 5]:
                        model.addConstr(c[after, 5] >= c[before, 5])
                    skipped_fixed_pairs += 1
                    continue
                model.addConstr(pos[j] >= pos[i]+1-data.n*(1-order))
                model.addConstr(pos[i] >= pos[j]+1-data.n*order)
                for k in stages:
                    m1 = max(0, ub_c[i, k]-lb_s[j, k])
                    m2 = max(0, ub_c[j, k]-lb_s[i, k])
                    model.addConstr(s[j, k] >= c[i, k]-m1*(1-order))
                    model.addConstr(s[i, k] >= c[j, k]-m2*order)
                if q == 'B':
                    m1 = max(0, ub_c[i, 5]-lb_c[j, 5])
                    m2 = max(0, ub_c[j, 5]-lb_c[i, 5])
                    model.addConstr(c[j, 5] >= c[i, 5]-m1*(1-order))
                    model.addConstr(c[i, 5] >= c[j, 5]-m2*order)
    timing['pair_constraints_seconds'] = time.perf_counter()-pairs_started
    warm_started = time.perf_counter()
    objective = model.addVar(lb=objective_lower, ub=h, name='Cmax')
    for j in range(data.n):
        model.addConstr(objective >= c[j, 9])
    model.setObjective(objective, GRB.MINIMIZE)
    if free_jobs is not None:
        restriction = make_restriction(code_from_result(warm, data.n), free_jobs)
        model.update()
        for j, m in restriction.fixed_machines:
            model.addConstr(x[j, 0] == int(m == 0), name=f'fixed_machine_{j}')
        for q, before, after in restriction.fixed_orders:
            i, j = sorted((before, after))
            var = model.getVarByName(f'order_{q}_{i}_{j}')
            model.addConstr(var == int(before == i), name=f'fixed_order_{q}_{i}_{j}')
    for q, order in warm['queues'].items():
        selected = set(zip([source]+order, order+[sink]))
        for edge, var in arcs[q].items():
            if not isinstance(var, int):
                var.Start = int(edge in selected)
    records = {(r['job'], r['station']-1): r for r in warm['operations']}
    for j in range(data.n):
        for k in range(10):
            s[j, k].Start = records[j, k]['start']
            c[j, k].Start = records[j, k]['finish']
        for m in range(2):
            if not isinstance(x[j, m], int):
                x[j, m].Start = int(j in warm['queues'][f'6-{m+1}'])
    objective.Start = h
    model.update()
    model._fixed_values = fixed_values
    model._reduction = {'full_binary_variables': 5*data.n*data.n+5*data.n+2,
                        'binary_variables': model.NumBinVars, 'variables': model.NumVars,
                        'constraints': model.NumConstrs, 'substituted_binary_variables': len(fixed_values)}
    model._strengthening = {'enabled': strengthen, 'objective_lower_from_fixed_relations': objective_lower,
                           'additional_mandatory_arcs': len(fixed_arcs)-original_fixed_arcs,
                           'minimum_time_width': min(ub_s[k]-lb_s[k] for k in lb_s),
                           'maximum_time_width': max(ub_s[k]-lb_s[k] for k in lb_s)}
    model._strengthening.update({'compact': compact, 'skipped_fixed_pairs': skipped_fixed_pairs})
    timing['warm_start_seconds'] = time.perf_counter()-warm_started
    write_started = time.perf_counter()
    model.write('model.mps')
    model.write('warm_start.mst')
    timing['model_write_seconds'] = time.perf_counter()-write_started
    timing['total_build_seconds'] = time.perf_counter()-build_started
    model._build_timing = timing
    return env, model


def extract(data, get_value):
    queues = {}
    for q in ('A', 'B', '6-1', '6-2'):
        order, previous = [], -1
        while True:
            successors = [j for j in range(data.n+1) if j != previous
                          and (j != data.n or previous != -1 or q.startswith('6'))
                          and get_value(f'z_{q}_{previous}_{j}') > 0.5]
            if len(successors) != 1:
                raise ValueError('相邻弧不能形成唯一队列')
            previous = successors[0]
            if previous == data.n:
                break
            if previous in order:
                raise ValueError('队列中出现环')
            order.append(previous)
        queues[q] = order
    s = [[get_value(f'S_{j}_{k}') for k in range(10)] for j in range(data.n)]
    c = [[get_value(f'C_{j}_{k}') for k in range(10)] for j in range(data.n)]
    return make_result(data, queues, s, c, get_value('Cmax'))




def main():
    root = PROJECT_ROOT
    parser = argparse.ArgumentParser(description='题目2 Case 1 一般模型精确求解')
    parser.add_argument('--solver', choices=['gurobi', 'copt'], default='gurobi')
    parser.add_argument('--seconds', type=float, default=600)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--output', type=Path, default=root/'problem2/results/exact_case1')
    args = parser.parse_args()
    if args.seconds <= 0 or args.threads < 1:
        parser.error('seconds 和 threads 必须为正数')
    args.output = args.output.resolve()
    data = load_case(root/'问题2数据.xlsx', 1)
    folder = args.output/args.solver
    if folder.exists():
        parser.error('输出目录已经存在，请使用新的 --output，避免覆盖证据')
    folder.mkdir(parents=True)
    os.chdir(folder)
    t0 = time.perf_counter()
    if args.solver == 'gurobi':
        import gurobipy as gp
        warm = warm_start(data)
        export(folder/'initial', warm)
        print(json.dumps({'phase': 'model', 'upper_bound': warm['objective']}, ensure_ascii=False), flush=True)
        env, model = build_model(data, warm, folder, args.seconds, args.threads)
        try:
            model.optimize()
            status = model.Status
            has_sol = model.SolCount > 0
            meta = {'solver': 'gurobi', 'version': '.'.join(map(str, gp.gurobi.version())),
                    'status': status, 'optimal': status == gp.GRB.OPTIMAL,
                    'bound': model.ObjBound, 'gap': model.MIPGap if has_sol else None,
                    'runtime': model.Runtime, 'nodes': model.NodeCount}
            if has_sol:
                result = extract(data, lambda name: model.getVarByName(name).X)
                model.write('solution.sol')
        finally:
            model.dispose()
            env.dispose()
        model_file = folder/'model.mps'
    else:
        import coptpy as cp
        from coptpy import COPT
        model_file = args.output/'gurobi/model.mps'
        if not model_file.is_file():
            raise FileNotFoundError('先运行 Gurobi 生成同一份 model.mps')
        cfg = cp.EnvrConfig()
        cfg.set('nobanner', '1')
        env = cp.Envr(cfg)
        try:
            model = env.createModel('problem2_case1_general')
            model.setParam('Logging', 1)
            model.setParam('LogToConsole', 0)
            model.setLogFile('solver.log')
            model.read('../gurobi/model.mps')
            model.setParam('TimeLimit', args.seconds)
            model.setParam('RelGap', 0)
            model.setParam('AbsGap', 0)
            model.setParam('Threads', args.threads)
            # 使用 Gurobi 可行解作为初始解；不固定变量，不改变原模型。
            variables = model.getVars()
            solved = json.loads((args.output/'gurobi/result.json').read_text(encoding='utf-8'))
            records = {(r['job'], r['station']-1): r for r in solved['operations']}
            starts = {}
            for j in range(data.n):
                for k in range(10):
                    starts[f'S_{j}_{k}'] = records[j, k]['start']
                    starts[f'C_{j}_{k}'] = records[j, k]['finish']
                for m in range(2):
                    starts[f'x_{j}_{m}'] = int(j in solved['queues'][f'6-{m+1}'])
            for q, order in solved['queues'].items():
                selected = set(zip([-1]+order, order+[data.n]))
                for i in [-1]+list(range(data.n)):
                    for j in list(range(data.n))+[data.n]:
                        starts[f'z_{q}_{i}_{j}'] = int((i, j) in selected)
            starts['Cmax'] = solved['objective']
            chosen = [v for v in variables if v.name in starts]
            model.setMipStart(chosen, [starts[v.name] for v in chosen])
            model.loadMipStart()
            model.solve()
            status = model.getAttr(COPT.Attr.Status)
            has_sol = model.getAttr(COPT.Attr.HasSol) > 0
            meta = {'solver': 'copt', 'version': version('coptpy'), 'status': status,
                    'optimal': status == COPT.OPTIMAL, 'bound': model.getAttr(COPT.Attr.ObjBound),
                    'gap': model.getAttr(COPT.Attr.BestGap) if has_sol else None,
                    'runtime': model.getAttr(COPT.Attr.SolvingTime)}
            if has_sol:
                values = {v.name: v.x for v in variables}
                result = extract(data, values.__getitem__)
                model.write('solution.sol')
        finally:
            env.close()
    meta['seconds_requested'] = args.seconds
    meta['threads'] = args.threads
    meta['total_seconds'] = time.perf_counter()-t0
    meta['model_sha256'] = hashlib.sha256(model_file.read_bytes()).hexdigest()
    meta['source_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in (root/'问题2.pdf', root/'问题2数据.xlsx')}
    if has_sol:
        if meta['optimal'] and abs(result['objective']-meta['bound']) > 1e-4:
            raise ValueError('OPTIMAL 状态与记录的上下界不一致')
        result['proof'] = meta
        result['validation'] = validate_exact(data, result)
        export(folder, result)
        print(json.dumps({'objective': result['objective'], **meta, 'valid': True}, ensure_ascii=False), flush=True)
    else:
        (folder/'status.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
        print(json.dumps(meta, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
