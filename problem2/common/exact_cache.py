"""跨阶段复用同一固定范围的最优证明；未完成的范围不进入证明缓存。"""
import copy
import hashlib
import json
import time
from pathlib import Path
from problem2.common.encoding import code_from_result, evaluate
from problem2.common.validation import validate_exact
from problem2.common.solver import export


class ExactCache:
    def __init__(self):
        root = Path(__file__).resolve().parent
        # 编码或模型规则改变后，不能沿用旧规则下的最优证明。
        self.model_digest = hashlib.sha256(b''.join((root/name).read_bytes() for name in
            ('data.py', 'encoding.py', 'solver.py', 'stable_constraints.py', 'time_bounds.py'))).hexdigest()
        self.entries, self.events = {}, []

    def key(self, data, reference, restrictions, upper=None):
        if restrictions is None or restrictions.reference != reference:
            raise ValueError('范围缓存仅用于来自当前参考编码的固定关系')
        fixed = sorted((tuple(row['key']), row['value']) for row in restrictions.records)
        value = evaluate(data, reference) if upper is None else upper
        payload = (self.model_digest, data.case, data.jobs, data.processing, data.setup,
                   reference.as_dict(), fixed, value)
        return hashlib.sha256(repr(payload).encode('utf-8')).hexdigest()

    def remember(self, key, data, reference, restrictions, result, folder):
        proof = result['proof']
        if not proof.get('optimal'):
            return False
        if (proof['status'] != 2 or proof['scope'] != 'restricted'
            or abs(proof['bound']-result['objective']) > 1e-4
            or abs(proof['solver_objective']-result['objective']) > 1e-4):
            raise AssertionError('最优证明的状态、范围或上下界不一致')
        validate_exact(data, result)
        if not restrictions.satisfies(code_from_result(result, data.n)):
            raise AssertionError('缓存候选违反固定关系')
        if result['objective'] > evaluate(data, reference):
            raise AssertionError('缓存候选劣于可行参考解')
        model = folder/'model.mps'
        if hashlib.sha256(model.read_bytes()).hexdigest() != proof['model_sha256']:
            raise AssertionError('缓存证明的模型哈希不一致')
        self.entries[key] = (copy.deepcopy(result), folder.resolve())
        return True

    def solve(self, solver, data, reference, restrictions, folder, seconds, threads, **kwargs):
        started = time.perf_counter()
        key = self.key(data, reference, restrictions)
        cached = self.entries.get(key)
        if cached is None:
            result = solver(data, reference, restrictions, folder, seconds, threads, **kwargs)
            certified = self.remember(key, data, reference, restrictions, result, folder)
            self.events.append({'key': key, 'folder': str(folder.resolve()), 'cache_hit': False,
                                'certified': certified, 'seconds': time.perf_counter()-started})
            result['proof']['cache_hit'] = False
            return result
        result, evidence = cached
        result = copy.deepcopy(result)
        # 命中仍验证调度，不重新建立模型或把原日志冒充新求解。
        validate_exact(data, result)
        assert restrictions.satisfies(code_from_result(result, data.n))
        if hashlib.sha256((evidence/'model.mps').read_bytes()).hexdigest() != result['proof']['model_sha256']:
            raise AssertionError('原缓存模型被更改')
        folder.mkdir(parents=True, exist_ok=False)
        (folder/'restrictions.json').write_bytes((json.dumps(restrictions.as_dict(), ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
        result['proof'].update({'cache_hit': True, 'cache_key': key,
            'cache_evidence_folder': str(evidence), 'original_runtime': result['proof']['runtime'],
            'runtime': 0, 'nodes': 0, 'seconds_requested': seconds,
            'solution_source': 'certified_range_cache',
            'current_request': {'threads': threads, 'strengthen': kwargs.get('strengthen', False),
                                'compact': kwargs.get('compact', False)}})
        export(folder, result)
        result['proof']['total_seconds'] = time.perf_counter()-started
        (folder/'result.json').write_bytes((json.dumps(result, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
        self.events.append({'key': key, 'folder': str(folder.resolve()), 'cache_hit': True,
                            'evidence': str(evidence), 'objective': result['objective'],
                            'seconds': time.perf_counter()-started})
        return result

    def summary(self):
        return {'requests': len(self.events), 'solver_calls': sum(not e['cache_hit'] for e in self.events),
                'cache_hits': sum(e['cache_hit'] for e in self.events), 'certified_ranges': len(self.entries),
                'events': self.events}
