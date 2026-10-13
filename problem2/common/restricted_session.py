"""受限模型在内存中保留；追加求解不修改变量、约束、初始解或线程。"""
import hashlib
import math
import os
from pathlib import Path
import time
from problem2.common.encoding import decode, code_from_result
from problem2.common.export import export, write_json
from problem2.common.solver import build_model, extract
from problem2.common.validation import validate_exact


class RestrictedSession:
    def __init__(self, data, reference, restrictions, folder, env=None, threads=8):
        if restrictions is None or restrictions.reference != reference:
            raise ValueError('只能继续同一参考编码的受限模型')
        self.data, self.reference, self.restrictions = data, reference, restrictions
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=False)
        self.created = time.perf_counter()
        self.warm = decode(data, reference)
        validate_exact(data, self.warm)
        write_json(self.folder/'restrictions.json', restrictions.as_dict())
        original = Path.cwd()
        self.own_env = env is None
        self.model = self.env = None
        try:
            os.chdir(self.folder)
            self.env, self.model = build_model(data, self.warm, self.folder, None, threads,
                stable_constraints=restrictions, strengthen=True, compact=True, solver_env=env)
        finally:
            os.chdir(original)
        self.digest = hashlib.sha256((self.folder/'model.mps').read_bytes()).hexdigest()
        self.phases, self.trace, self.solver_wall = [], [], 0.0
        self.result = self.warm
        self.threads = threads

    def run(self, seconds, deadline=None):
        import gurobipy as gp
        if self.model is None:
            raise RuntimeError('会话已关闭')
        if self.phases and self.phases[-1]['optimal']:
            raise ValueError('已经证明最优，不再求解相同范围')
        started = time.perf_counter()
        limit = max(0, min(seconds, deadline-started)) if deadline is not None else max(0, seconds)
        stop = started+limit
        interrupted = False
        def callback(model, where):
            nonlocal interrupted
            if where == gp.GRB.Callback.MIPSOL:
                self.trace.append({'phase': len(self.phases)+1, 'session_seconds': time.perf_counter()-self.created,
                    'phase_seconds': time.perf_counter()-started,
                    'solver_objective': model.cbGet(gp.GRB.Callback.MIPSOL_OBJ)})
            # 使用本次调用的墙钟停止，不依赖版本间累计Runtime的区别。
            if time.perf_counter() >= stop:
                interrupted = True
                model.terminate()
        original = Path.cwd()
        try:
            os.chdir(self.folder)
            self.model.optimize(callback)
            wall = time.perf_counter()-started
            self.solver_wall += wall
            m = self.model
            bound = m.ObjBound
            proof = {'scope': 'restricted', 'original_optimality_proven_by_this_run': False,
                'solver': 'gurobi', 'version': '.'.join(map(str, gp.gurobi.version())),
                'status': m.Status, 'optimal': m.Status == gp.GRB.OPTIMAL,
                'runtime': m.Runtime, 'nodes': m.NodeCount, 'bound': bound if math.isfinite(bound) else 0,
                'solver_objective': m.ObjVal if m.SolCount else None,
                'gap': m.MIPGap if m.SolCount else None, 'seconds_requested': seconds,
                'effective_phase_seconds_limit': limit, 'phase_solver_wall_seconds': wall,
                'session_solver_wall_seconds': self.solver_wall, 'callback_time_stop': interrupted,
                'resumed_same_model': bool(self.phases), 'model_sha256': self.digest,
                'threads': self.threads, 'reduction': m._reduction, 'strengthening': m._strengthening,
                'build_timing': m._build_timing, 'environment_reused': not self.own_env,
                'phase': len(self.phases)+1, 'total_seconds': time.perf_counter()-self.created}
            result = self.warm
            if m.SolCount:
                def value(name):
                    var = m.getVarByName(name)
                    return var.X if var is not None else m._fixed_values.get(name, 0)
                solved = extract(self.data, value)
                validate_exact(self.data, solved)
                code = code_from_result(solved, self.data.n)
                if not self.restrictions.satisfies(code):
                    raise AssertionError('继续求解违反固定范围')
                result = decode(self.data, code)
                if proof['optimal'] and abs(result['objective']-solved['objective']) > 1e-4:
                    raise AssertionError('受限最优解与解码不一致')
                if result['objective'] > self.warm['objective']+1e-4:
                    raise AssertionError('继续求解劣于参考方案')
                export(self.folder/f'phase{proof["phase"]}_solver', solved)
                m.write('solution.sol')
                proof['solution_source'] = 'decoded_solver_code'
            else:
                proof['solution_source'] = 'reference_fallback'
        finally:
            os.chdir(original)
        if hashlib.sha256((self.folder/'model.mps').read_bytes()).hexdigest() != self.digest:
            raise AssertionError('追加期间模型文件发生变化')
        result['proof'] = proof
        result['validation'] = validate_exact(self.data, result)
        self.phases.append(proof.copy())
        self.result = result
        export(self.folder/f'phase{proof["phase"]}', result)
        export(self.folder, result)
        write_json(self.folder/'phases.json', self.phases)
        write_json(self.folder/'incumbents.json', self.trace)
        return result

    def close(self):
        if self.model is not None:
            self.model.dispose()
            self.model = None
        if self.own_env and self.env is not None:
            self.env.dispose()
            self.env = None
