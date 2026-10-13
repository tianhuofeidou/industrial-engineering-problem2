"""从关系记录选择固定约束；固定关系必须与同一个参考可行解一致。"""
from dataclasses import dataclass
from math import ceil
from problem2.common.relation_tracking import features, signature, matches


@dataclass
class StableConstraints:
    reference: object
    records: list[dict]

    @classmethod
    def from_evidence(cls, reference, evidence):
        actual, selected = features(reference), {}
        for row in evidence['relations']:
            key = tuple(row['key'])
            if row['selected'] and actual.get(key) == row['value']:
                old = selected.get(key)
                if old is None or row['basis'] == 'whole_run':
                    selected[key] = row
        return cls(reference, list(selected.values()))

    def decisions(self):
        machines, orders, arcs = {}, {}, {}
        n = len(self.reference.a)
        for row in self.records:
            key, value = tuple(row['key']), row['value']
            if key[0] == 'machine':
                machines[key[1]] = value
            elif key[0] == 'order':
                _, q, i, j = key
                orders[q, i, j] = value
            else:
                _, q, i, j = key
                arcs[q, i, j] = 1
                if q.startswith('6'):
                    for job in (i, j):
                        if 0 <= job < n:
                            machines[job] = int(q[-1])-1
                elif 0 <= i < n and 0 <= j < n:
                    a, b = sorted((i, j))
                    orders[q, a, b] = int(i == a)
        # 先后和相邻关系蕴含的传递关系也直接代入，避免保留多余0/1变量。
        for q in ('A', 'B'):
            reach = [[False]*n for _ in range(n)]
            for (which, i, j), value in orders.items():
                if which == q:
                    before, after = (i, j) if value else (j, i)
                    reach[before][after] = True
            for k in range(n):
                for i in range(n):
                    if reach[i][k]:
                        for j in range(n):
                            reach[i][j] |= reach[k][j]
            if any(reach[j][j] for j in range(n)):
                raise ValueError('固定关系形成循环')
            for i in range(n):
                for j in range(i+1, n):
                    if reach[i][j] or reach[j][i]:
                        orders[q, i, j] = int(reach[i][j])
        return machines, orders, arcs

    def satisfies(self, code):
        sig = signature(code)
        return all(matches(tuple(r['key']), r['value'], sig) for r in self.records)

    def relaxed(self, fraction=0.25):
        if not 0 < fraction <= 1:
            raise ValueError('解除比例须在(0,1]')
        if not self.records:
            return self
        # 后期一致先解除；全程稳定按有效尝试数量排序，不把该排序解释为概率。
        ordered = sorted(self.records, key=lambda r: (
            r['basis'] == 'whole_run', r.get('eligible', r.get('perturbed', 0)),
            r['key'][0] == 'adj', tuple(str(x) for x in r['key'])))
        return StableConstraints(self.reference, ordered[max(1, ceil(len(ordered)*fraction)):])

    def as_dict(self):
        machines, orders, arcs = self.decisions()
        return {'reference_code': self.reference.as_dict(), 'selected_relations': self.records,
                'direct_relations': len(self.records),
                'fixed_machines': [[j, m] for j, m in sorted(machines.items())],
                'fixed_orders': [[q, i, j, value] for (q, i, j), value in sorted(orders.items())],
                'fixed_arcs': [[q, i, j] for q, i, j in sorted(arcs)],
                'includes_inferred_machine_and_transitive_order_constraints': True}


def arc_constants(n, queue, machines, orders, fixed_arcs, strengthen=False):
    """返回所有被排除或确定的相邻弧；不存在的弧在导出时取0。"""
    source, sink = -1, n
    edges = [(source, j) for j in range(n)]+[(j, sink) for j in range(n)]
    edges += [(i, j) for i in range(n) for j in range(n) if i != j]
    if queue.startswith('6'):
        edges.append((source, sink))
    chosen = {(i, j) for q, i, j in fixed_arcs if q == queue}
    outgoing, incoming = {i: j for i, j in chosen}, {j: i for i, j in chosen}
    if len(outgoing) != len(chosen) or len(incoming) != len(chosen):
        raise ValueError('固定相邻关系有多个前驱或后继')
    constants = {}

    # 位集合记录已知前驱和后继；两者交集直接判断是否存在必须夹在中间的工件。
    # 工位6只把已经固定在当前机器上的中间工件计入，保留原来的排除条件。
    successors, predecessors = [0]*n, [0]*n
    eligible = (1 << n)-1
    if strengthen:
        which = 'B' if queue.startswith('6') else queue
        for (q, i, j), order in orders.items():
            if q == which:
                before, after = (i, j) if order else (j, i)
                successors[before] |= 1 << after
                predecessors[after] |= 1 << before
        if queue.startswith('6'):
            eligible = sum(1 << j for j, m in machines.items() if m == int(queue[-1])-1)

    for i, j in edges:
        exclude = ((i in outgoing and outgoing[i] != j) or (j in incoming and incoming[j] != i))
        if queue.startswith('6'):
            machine = int(queue[-1])-1
            exclude |= any(0 <= job < n and job in machines and machines[job] != machine for job in (i, j))
        elif i >= 0 and j < n:
            a, b = sorted((i, j))
            order = orders.get((queue, a, b))
            exclude |= order is not None and int(i == a) != order
        if strengthen:
            if i >= 0 and j < n:
                # 存在必须夹在两件之间的工件，二者就不可能紧邻。
                exclude |= bool(successors[j] & (1 << i))
                exclude |= bool(successors[i] & predecessors[j] & eligible & ~((1 << i) | (1 << j)))
            if i == source:
                exclude |= bool(predecessors[j] & eligible & ~(1 << j)) if j < n else False
            if j == sink:
                exclude |= bool(successors[i] & eligible & ~(1 << i)) if i >= 0 else False
        if (i, j) in chosen:
            if exclude:
                raise ValueError('固定相邻关系与机器或先后约束冲突')
            constants[i, j] = 1
        elif exclude:
            constants[i, j] = 0
    return edges, constants


def propagated_decisions(n, machines, orders, fixed_arcs):
    """必加工的节点只剩一个前驱或后继时，该弧也必选；重新排除冲突直到不再变化。"""
    machines, fixed_arcs = dict(machines), dict(fixed_arcs)
    changed = True
    while changed:
        changed = False
        for q in ('A', 'B', '6-1', '6-2'):
            edges, const = arc_constants(n, q, machines, orders, fixed_arcs, True)
            present = [(i, j) for i, j in edges if const.get((i, j)) != 0]
            required = set(range(n)) if q in ('A', 'B') else {
                j for j, m in machines.items() if m == int(q[-1])-1}
            for node, outgoing in [(i, True) for i in required | {-1}]+[(j, False) for j in required | {n}]:
                candidates = [e for e in present if e[0 if outgoing else 1] == node]
                if not candidates:
                    raise ValueError('固定关系使必加工节点没有前驱或后继')
                if len(candidates) != 1:
                    continue
                i, j = candidates[0]
                if (q, i, j) not in fixed_arcs:
                    fixed_arcs[q, i, j] = 1
                    changed = True
                if q.startswith('6'):
                    m = int(q[-1])-1
                    for job in (i, j):
                        if 0 <= job < n and job not in machines:
                            machines[job] = m
                            changed = True
    return machines, orders, fixed_arcs
