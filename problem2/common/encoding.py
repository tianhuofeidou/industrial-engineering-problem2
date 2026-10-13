"""一般模型的三数组编码；评分与完整调度共用同一组时间递推。"""
from dataclasses import dataclass
from problem2.common.data import m62_duration


@dataclass(frozen=True, slots=True)
class Chromosome:
    """a 为前段排列，b 为工位6完工全序，machines 按工件编号存0/1机器归属。"""
    a: tuple[int, ...]
    b: tuple[int, ...]
    machines: tuple[int, ...]

    def check(self, n):
        expected = set(range(n))
        if len(self.a) != n or set(self.a) != expected or len(self.b) != n or set(self.b) != expected:
            raise ValueError('两个排列必须分别包含全部工件恰一次')
        if len(self.machines) != n or any(m not in (0, 1) for m in self.machines):
            raise ValueError('机器分配必须按工件编号提供n个0/1值')

    def as_dict(self):
        return {'a': list(self.a), 'b': list(self.b), 'machines': list(self.machines)}


def code_from_result(result, n):
    q = result['queues']
    return Chromosome(tuple(q['A']), tuple(q['B']),
                      tuple(0 if j in q['6-1'] else 1 for j in range(n)))


def _calculate(data, code, detail):
    """每个工位遍历一次；机器排队、到达后换模和工位6继续等待都在此计算。"""
    finish = [0]*data.n
    starts = [[0]*10 for _ in range(data.n)] if detail else None
    completions = [[0]*10 for _ in range(data.n)] if detail else None
    slow = tuple(m62_duration(p[5]) for p in data.processing)
    for k in range(10):
        order = code.a if k < 5 else code.b
        previous = [None, None]
        machine_end = [0, 0]
        last_in_b = 0
        for j in order:
            m = code.machines[j] if k == 5 else 0
            prev = previous[m]
            setup = 0 if prev is None else data.setup[prev][j]
            start = max(machine_end[m], finish[j])+setup
            duration = slow[j] if k == 5 and m == 1 else data.processing[j][k]
            end = start+duration
            if k == 5:
                # b 表示实际完工全序；必要时延后开工，允许两台机器同时完工。
                end = max(end, last_in_b)
                start = end-duration
                last_in_b = end
            finish[j] = end
            previous[m], machine_end[m] = j, end
            if detail:
                starts[j][k], completions[j][k] = start, end
    objective = max(finish)
    if not detail:
        return objective
    queues = {'A': list(code.a), 'B': list(code.b),
              '6-1': [j for j in code.b if code.machines[j] == 0],
              '6-2': [j for j in code.b if code.machines[j] == 1]}
    return make_result(data, queues, starts, completions, objective)


def evaluate(data, code):
    code.check(data.n)
    return _calculate(data, code, False)


def decode(data, code):
    code.check(data.n)
    return _calculate(data, code, True)


class BatchEvaluator:
    """将独立完整编码的同一时间递推放在数组中计算，适用于大量邻居评分。"""
    def __init__(self, data):
        import numpy as np
        self.np, self.data = np, data
        if data.n < 1:
            raise ValueError('工件数量必须为正')
        slow = tuple(m62_duration(p[5]) for p in data.processing)
        maximum_setup = max((data.setup[i][j] for i in range(data.n)
                             for j in range(data.n) if i != j), default=0)
        # 一条时间依赖路径最多经过10n道工序；用Python整数先检查，防止int64溢出。
        upper = sum(sum(p[:5])+max(p[5], slow[j])+sum(p[6:])
                    for j, p in enumerate(data.processing))+10*data.n*maximum_setup
        if upper > np.iinfo(np.int64).max:
            raise OverflowError('本数据超出批量评分的int64范围，请使用逐个评分')
        self.processing = np.asarray(data.processing, dtype=np.int64)
        # 对角元从不查询；不把原始对角元带入转换或溢出检查。
        self.setup = np.asarray([[0 if i == j else data.setup[i][j] for j in range(data.n)]
                                 for i in range(data.n)], dtype=np.int64)
        self.slow = np.asarray(slow, dtype=np.int64)

    def evaluate(self, codes):
        """返回输入顺序对应的整数Cmax；输入始终含全部工件、全部10个工位。"""
        import operator
        codes = list(codes)
        if not codes:
            return []
        for code in codes:
            code.check(self.data.n)
            for j in code.a+code.b+code.machines:
                operator.index(j)
        np, n, count = self.np, self.data.n, len(codes)
        if all(code.a == codes[0].a for code in codes):
            prepared = self.prepare([c.b for c in codes], [c.machines for c in codes])
            return [int(value) for value in prepared.evaluate(codes[0].a)]
        a = np.asarray([c.a for c in codes], dtype=np.int64)
        b = np.asarray([c.b for c in codes], dtype=np.int64)
        machines = np.asarray([c.machines for c in codes], dtype=np.int64)
        finish = np.zeros((count, n), dtype=np.int64)
        finish = self._finish(a, b, machines, finish, range(10))
        return [int(value) for value in np.max(finish, axis=1)]

    def prepare(self, orders_b, machines):
        """固定一批完整B和机器数组；重复评价不同的完整A时只计算一次前段。"""
        return _PreparedBatch(self, orders_b, machines)

    def _finish(self, a, b, machines, finish, stages):
        np, n, count = self.np, self.data.n, len(finish)
        rows, zero = np.arange(count), np.zeros(count, dtype=np.int64)
        for k in stages:
            sequence = a if k < 5 else b
            previous = np.full((count, 2), -1, dtype=np.int64)
            machine_end = np.zeros((count, 2), dtype=np.int64)
            last_in_b = zero
            for position in range(n):
                j = sequence[:, position]
                m = machines[rows, j] if k == 5 else zero
                prev = previous[rows, m]
                setup = np.where(prev < 0, 0, self.setup[np.maximum(prev, 0), j])
                duration = np.where(m == 1, self.slow[j], self.processing[j, k]) if k == 5 else self.processing[j, k]
                end = np.maximum(machine_end[rows, m], finish[rows, j])+setup+duration
                if k == 5:
                    # 与逐个评分相同：选定完工全序后，必要时延后工位6开工。
                    end = np.maximum(end, last_in_b)
                    last_in_b = end
                finish[rows, j] = end
                previous[rows, m], machine_end[rows, m] = j, end
        return finish


class _PreparedBatch:
    def __init__(self, scorer, orders_b, machines):
        self.scorer = scorer
        np, n = scorer.np, scorer.data.n
        b, m = np.asarray(orders_b), np.asarray(machines)
        if b.ndim != 2 or b.shape[1] != n or len(b) == 0 or m.shape != b.shape:
            raise ValueError('B和机器数组必须是相同数量的完整编码')
        if b.dtype.kind not in 'iub' or m.dtype.kind not in 'iub':
            raise TypeError('工件编号和机器归属必须为整数')
        valid_order = np.all((b >= 0) & (b < n))
        if valid_order:
            indices = b.astype(np.int64)+n*np.arange(len(b))[:, None]
            valid_order = np.all(np.bincount(indices.ravel(), minlength=n*len(b)) == 1)
        if not valid_order or not np.all((m == 0) | (m == 1)):
            raise ValueError('B必须含全部工件恰一次，机器数组必须按工件编号提供0/1')
        self._b, self._m = b.astype(np.int64, copy=True), m.astype(np.int64, copy=True)
        self._b.flags.writeable = self._m.flags.writeable = False

    def evaluate(self, a):
        """每个候选使用(a,B[row],machines[row])，完整计算工位1至10。"""
        import operator
        scorer, np, n = self.scorer, self.scorer.np, self.scorer.data.n
        a = tuple(operator.index(j) for j in a)
        if len(a) != n or set(a) != set(range(n)):
            raise ValueError('A必须含全部工件恰一次')
        front = scorer._finish(np.asarray([a], dtype=np.int64), None, None,
                               np.zeros((1, n), dtype=np.int64), range(5))
        finish = np.broadcast_to(front, (len(self._b), n)).copy()
        finish = scorer._finish(None, self._b, self._m, finish, range(5, 10))
        return np.max(finish, axis=1)


def make_result(data, queues, starts, completions, objective):
    """同时用于解码和求解器时间变量导出；此处不重新决定工序时间。"""
    operations = []
    for key, stages in [('A', range(5)), ('B', range(6, 10)), ('6-1', [5]), ('6-2', [5])]:
        for k in stages:
            prev = None
            for j in queues[key]:
                setup = 0 if prev is None else data.setup[prev][j]
                operations.append({'job': j, 'job_name': data.jobs[j], 'station': k+1,
                                   'machine': key if k == 5 else str(k+1), 'predecessor': prev,
                                   'arrival': 0 if k == 0 else completions[j][k-1],
                                   'setup_start': starts[j][k]-setup, 'setup_finish': starts[j][k],
                                   'start': starts[j][k], 'finish': completions[j][k]})
                prev = j
    return {'case': data.case, 'objective': objective, 'queues': queues, 'operations': operations}
