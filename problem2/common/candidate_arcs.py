"""用退火样本选择允许的相邻工件；这是可解除的附加限制，不是必选关系。"""
from collections import Counter
from dataclasses import dataclass
from math import isfinite

from problem2.common.annealing_records import as_code
from problem2.common.encoding import evaluate
from problem2.common.relation_tracking import queues

QUEUES = ('A', 'B', '6-1', '6-2')


@dataclass(frozen=True)
class CandidateArcs:
    n: int
    edges: dict[str, frozenset[tuple[int, int]]]

    def check(self, n):
        if self.n != n or set(self.edges) != set(QUEUES):
            raise ValueError('候选集合必须覆盖同一算例的四条队列')
        for edges in self.edges.values():
            if any(type(i) is not int or type(j) is not int or
                   not 0 <= i < n or not 0 <= j < n or i == j for i, j in edges):
                raise ValueError('实际工件候选弧的端点必须有效且不同')

    def permits(self, queue, i, j):
        # 不按历史频数限制队首/队尾；工位6允许起点直接接终点，即空队列。
        return i == -1 or j == self.n or (i, j) in self.edges[queue]

    def satisfies(self, code):
        code.check(self.n)
        return all(all((i, j) in self.edges[q] for i, j in zip(order, order[1:]))
                   for q, order in queues(code).items())

    def as_dict(self):
        return {'scope': 'restricted', 'kind': 'candidate_arcs', 'n': self.n,
                'edges': {q: [list(edge) for edge in sorted(self.edges[q])] for q in QUEUES},
                'all_source_sink_arcs_allowed': True, 'empty_station6_queues_allowed': True,
                'fixed_machine_assignments': 0,
                'machine_combinations_can_be_indirectly_restricted': True}


def generate_candidates(data, reference, report, k=5, quality_ratio=1.03):
    """每种队列排列只投票一次；前驱和后继候选取并集，再补参考解实际弧。"""
    reference.check(data.n)
    if type(k) is not int or k < 1 or not isfinite(quality_ratio) or quality_ratio < 1:
        raise ValueError('候选数为正整数，质量比例为至少1的有限数')
    reference_cost = evaluate(data, reference)
    samples = {}
    raw_rows = report['front_samples'] + report['other_samples']
    for row in raw_rows:
        cost = row['objective']
        if not isfinite(cost):
            raise ValueError('样本目标不是有限数')
        code = as_code(row['code'])
        code.check(data.n)
        if evaluate(data, code) != cost:
            raise ValueError('样本完整评分与记录不一致')
        if cost <= reference_cost * quality_ratio:
            samples[code] = cost
    if not samples or min(samples.values()) != reference_cost or reference not in samples:
        raise ValueError('退火记录的最好编码与本次参考解不一致')

    chosen, statistics = {}, {}
    reference_queues = queues(reference)
    for q in QUEUES:
        distinct = {queues(code)[q] for code in samples}
        counts = Counter(edge for order in distinct for edge in zip(order, order[1:]))
        selected = set()
        for job in range(data.n):
            successors = sorted((j for i, j in counts if i == job),
                                key=lambda j: (-counts[job, j], data.setup[job][j], j))[:k]
            predecessors = sorted((i for i, j in counts if j == job),
                                  key=lambda i: (-counts[i, job], data.setup[i][job], i))[:k]
            selected.update((job, j) for j in successors)
            selected.update((i, job) for i in predecessors)
        reference_edges = set(zip(reference_queues[q], reference_queues[q][1:]))
        added = reference_edges - selected
        selected.update(reference_edges)
        chosen[q] = frozenset(selected)
        statistics[q] = {'distinct_queue_orders': len(distinct), 'observed_arcs': len(counts),
                         'allowed_actual_arcs': len(selected), 'reference_arcs_added': len(added),
                         'frequencies': [{'from': i, 'to': j, 'count': counts[i, j]}
                                         for i, j in sorted(counts)]}
    result = CandidateArcs(data.n, chosen)
    result.check(data.n)
    if not result.satisfies(reference):
        raise AssertionError('候选集合排除了参考解')
    return result, {'k': k, 'quality_ratio': quality_ratio, 'reference_code': reference.as_dict(),
                    'reference_objective': reference_cost, 'raw_sample_rows': len(raw_rows),
                    'distinct_eligible_codes': len(samples), 'queue_statistics': statistics,
                    'frequency_counts_distinct_queue_orders': True,
                    'zero_frequency_arcs_not_selected_except_reference': True,
                    'tie_break': 'directed_setup_then_job_id', 'scope': 'restricted'}
