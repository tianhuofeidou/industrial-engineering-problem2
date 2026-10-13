"""种群只决定放开哪些工件；所有固定关系从同一个可行编码提取。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Restriction:
    free_jobs: tuple[int, ...]
    fixed_machines: tuple[tuple[int, int], ...]
    fixed_orders: tuple[tuple[str, int, int], ...]  # 前件、后件，不要求紧邻

    def as_dict(self):
        return {'free_jobs': list(self.free_jobs), 'fixed_machines': list(self.fixed_machines),
                'fixed_orders': list(self.fixed_orders)}


def make_restriction(code, free_jobs):
    n = len(code.a)
    code.check(n)
    free = tuple(sorted(free_jobs))
    if len(set(free)) != len(free) or any(j not in range(n) for j in free):
        raise ValueError('可调整工件必须是不同的有效工件编号')
    fixed = set(range(n))-set(free)
    relations = []
    for q, order in [('A', code.a), ('B', code.b)]:
        remaining = [j for j in order if j in fixed]
        relations.extend((q, i, j) for index, i in enumerate(remaining) for j in remaining[index+1:])
    return Restriction(free, tuple((j, code.machines[j]) for j in sorted(fixed)), tuple(relations))


def satisfies(code, restriction):
    if any(code.machines[j] != m for j, m in restriction.fixed_machines):
        return False
    ranks = {q: {j: i for i, j in enumerate(order)} for q, order in [('A', code.a), ('B', code.b)]}
    return all(ranks[q][i] < ranks[q][j] for q, i, j in restriction.fixed_orders)


def select_free_jobs(reference, archive, count):
    """以优秀个体的两两顺序和机器归属差异给工件排序，不把多数意见直接固定。"""
    n = len(reference.a)
    if not 0 <= count <= n:
        raise ValueError('可调整工件数必须在0到n之间')
    reference.check(n)
    scores = [0]*n
    base_ranks = [{j: index for index, j in enumerate(order)} for order in (reference.a, reference.b)]
    for code in archive:
        code.check(n)
        for base, order in zip(base_ranks, (code.a, code.b)):
            rank = {j: index for index, j in enumerate(order)}
            for i in range(n):
                for j in range(i+1, n):
                    if (base[i] < base[j]) != (rank[i] < rank[j]):
                        scores[i] += 1
                        scores[j] += 1
        for j in range(n):
            scores[j] += (n-1)*int(code.machines[j] != reference.machines[j])
    selected = tuple(sorted(sorted(range(n), key=lambda j: (-scores[j], j))[:count]))
    return selected, scores
