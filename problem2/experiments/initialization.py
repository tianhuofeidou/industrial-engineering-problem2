"""多种前段排列和工位6逐件插入；评价始终计算到工位10。"""
from problem2.experiments.schedule import Solution


def initial_solutions(evaluator, rng, random_count=3):
    data = evaluator.data
    jobs = tuple(range(data.n))
    orders = [jobs,
              tuple(sorted(jobs, key=lambda j: -sum(data.processing[j]))),
              tuple(sorted(jobs, key=lambda j: -data.processing[j][5]))]
    for _ in range(random_count):
        order = list(jobs)
        rng.shuffle(order)
        orders.append(tuple(order))
    results = []
    for order in dict.fromkeys(orders):
        q1, q2 = (), ()
        for index, j in enumerate(order):
            pending = order[index+1:]
            candidates = []
            # 尚未插入的工件暂放在6-1尾部，使所有候选都能完整评价。
            for pos in range(len(q1)+1):
                a = q1[:pos] + (j,) + q1[pos:]
                candidate = Solution(order, a + pending, q2, jobs)
                candidates.append((evaluator.cost(candidate), a, q2))
            for pos in range(len(q2)+1):
                b = q2[:pos] + (j,) + q2[pos:]
                candidate = Solution(order, q1 + pending, b, jobs)
                candidates.append((evaluator.cost(candidate), q1, b))
            _, q1, q2 = min(candidates, key=lambda item: item[0])
        results.append(Solution(order, q1, q2, jobs))
    return results
