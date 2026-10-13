"""三数组编码的完整邻域下降；不改变编码、换模规则或目标。"""
from problem2.common.encoding import Chromosome
from functools import lru_cache


KINDS = ('insert_a', 'insert_b', 'flip', 'swap_a', 'swap_b')


@lru_cache(maxsize=100)
def operations(n, kind):
    if kind == 'flip':
        return tuple((kind, job, job) for job in range(n))
    if kind not in KINDS:
        raise ValueError(f'未知邻域: {kind}')
    return tuple((kind, i, j) for i in range(n) for j in range(n)
                 if i != j and (not kind.startswith('swap') or i < j))


def apply_move(code, operation):
    kind, i, j = operation
    if kind == 'flip':
        machines = list(code.machines)
        machines[i] = 1-machines[i]
        return Chromosome(code.a, code.b, tuple(machines))
    original = code.a if kind.endswith('_a') else code.b
    order = list(original)
    if kind.startswith('insert'):
        order.insert(j, order.pop(i))
    else:
        order[i], order[j] = order[j], order[i]
    return Chromosome(tuple(order) if kind.endswith('_a') else code.a,
                      tuple(order) if kind.endswith('_b') else code.b, code.machines)


def neighbors(code, kind):
    for operation in operations(len(code.a), kind):
        yield apply_move(code, operation)


@lru_cache(maxsize=20)
def combined_operations(n):
    return tuple(op for kind in KINDS for op in operations(n, kind))


def random_neighbor(code, rng, on_operation=None):
    operation = rng.choice(combined_operations(len(code.a)))
    if on_operation is not None:
        # 记录已抽出的操作；回调不得抽取随机数或影响候选。
        on_operation(operation)
    return apply_move(code, operation)


def all_neighbors(code):
    for kind in KINDS:
        yield from neighbors(code, kind)


def descend(code, evaluator, observer=None):
    """每个邻域完整检查；接受严格改善后从第一个邻域重新检查。"""
    value, index = evaluator.cost(code), 0
    while index < len(KINDS):
        best, best_value = code, value
        candidates = neighbors(code, KINDS[index])
        trials = evaluator.costs(candidates) if observer is None and hasattr(evaluator, 'costs') else (
            (candidate, evaluator.cost(candidate)) for candidate in candidates)
        for candidate, cost in trials:
            if observer is not None:
                observer.descent_trial(code, candidate, value, cost)
            if cost < best_value:
                best, best_value = candidate, cost
        if best_value < value:
            code, value, index = best, best_value, 0
        else:
            index += 1
    return code


def perturb(code, rng, strength):
    """移动指定数量的不同工件，并可能改变机器归属；保证编码完整。"""
    selected = rng.sample(range(len(code.a)), min(strength, len(code.a)))
    a, b, machines = list(code.a), list(code.b), list(code.machines)
    for job in selected:
        for order in (a, b):
            order.remove(job)
            order.insert(rng.randrange(len(order)+1), job)
        if rng.random() < 0.5:
            machines[job] = 1-machines[job]
    trial = Chromosome(tuple(a), tuple(b), tuple(machines))
    if trial == code:
        machines[selected[0]] = 1-machines[selected[0]]
        trial = Chromosome(tuple(a), tuple(b), tuple(machines))
    return trial


def changed_attributes(before, after):
    """返回修改后的属性及修改前的属性；禁忌表短期禁止恢复旧属性。"""
    new, old = [], []
    for job, (m1, m2) in enumerate(zip(before.machines, after.machines)):
        if m1 != m2:
            new.append(('machine', job, m2))
            old.append(('machine', job, m1))
    for q, first, second in zip(('A', 'B'), (before.a, before.b), (after.a, after.b)):
        r1 = {j: i for i, j in enumerate(first)}
        r2 = {j: i for i, j in enumerate(second)}
        for i in range(len(first)):
            for j in range(i+1, len(first)):
                a, b = int(r1[i] < r1[j]), int(r2[i] < r2[j])
                if a != b:
                    new.append(('order', q, i, j, b))
                    old.append(('order', q, i, j, a))
    return tuple(new), tuple(old)
