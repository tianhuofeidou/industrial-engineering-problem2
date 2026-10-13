"""少量工件同时在前后段成组重排；其余工件的相对顺序和机器保持。"""
import itertools
import time
from problem2.common.encoding import BatchEvaluator, Chromosome, evaluate
from problem2.stage1.neighborhoods import critical_weights
from problem2.common.relation_tracking import features
from problem2.common.stable_constraints import StableConstraints


def block_orders(sequence, jobs):
    base = tuple(j for j in sequence if j not in jobs)
    for offset in range(len(base)+1):
        for free in itertools.permutations(jobs):
            yield base[:offset]+free+base[offset:]


def check_jobs(data, reference, jobs):
    reference.check(data.n)
    if not jobs or len(set(jobs)) != len(jobs) or any(type(j) is not int or not 0 <= j < data.n for j in jobs):
        raise ValueError('自由工件必须是不重复的有效编号')
    if len(jobs) > 4:
        raise ValueError('连续成组枚举最多放开4个工件')


def enumerate_block(data, reference, jobs, deadline=None, scorer=None):
    """每个A只递推一次前段，再批量评价B和机器；附加限制仅是所选工件连续。"""
    started = time.perf_counter()
    jobs = tuple(sorted(jobs))
    check_jobs(data, reference, jobs)
    scorer = scorer or BatchEvaluator(data)
    if scorer.data != data:
        raise ValueError('批量评分器数据不一致')
    bb = list(block_orders(reference.b, jobs))
    assignments = []
    for values in itertools.product((0, 1), repeat=len(jobs)):
        machines = list(reference.machines)
        for j, m in zip(jobs, values):
            machines[j] = m
        assignments.append(tuple(machines))
    nm = len(assignments)
    b = scorer.np.repeat(scorer.np.asarray(bb, dtype=scorer.np.int64), nm, axis=0)
    m = scorer.np.tile(scorer.np.asarray(assignments, dtype=scorer.np.int64), (len(bb), 1))
    prepared = scorer.prepare(b, m)
    best, cost, before, count, complete = reference, evaluate(data, reference), evaluate(data, reference), 0, True
    for a in block_orders(reference.a, jobs):
        if deadline is not None and time.perf_counter() >= deadline:
            complete = False
            break
        values = prepared.evaluate(a)
        count += len(values)
        index = int(scorer.np.argmin(values))
        if values[index] < cost:
            best = Chromosome(a, bb[index//nm], assignments[index % nm])
            cost = int(values[index])
            if evaluate(data, best) != cost:
                raise AssertionError('批量评分与逐个评分不一致')
    na = (data.n-len(jobs)+1)*len(list(itertools.permutations(jobs)))
    return best, {'jobs': list(jobs), 'before': before, 'after': cost, 'complete': complete,
                  'evaluations': count, 'expected_evaluations': na*len(bb)*nm,
                  'seconds': time.perf_counter()-started, 'reference': reference.as_dict(),
                  'scope': 'restricted', 'original_optimality_proven_by_this_run': False,
                  'conditions': 'selected_jobs_contiguous_in_A_and_B;other_relative_orders_and_machines_fixed;reference_also_retained'}


def choose_groups(data, reference, size=3, limit=80):
    if not 1 <= size <= min(4, data.n) or limit < 1:
        raise ValueError('工件组大小或数量无效')
    weights, critical, operations = critical_weights(data, reference, details=True)
    setup = {}
    for node in critical:
        row = operations[node]
        prev = row['predecessor']
        if prev is not None and (prev, node[1]) in critical and operations[prev, node[1]]['finish'] == row['setup_start']:
            pair = tuple(sorted((prev, node[0])))
            setup[pair] = max(setup.get(pair, 0), row['start']-row['setup_start'])
    def priority(jobs):
        largest = max((setup.get(pair, 0) for pair in itertools.combinations(jobs, 2)), default=0)
        return (-largest, -sum(weights['A'][j]+weights['B'][j] for j in jobs), jobs)
    # 先覆盖两条参考排列已有的连续组合，避免全部名额被同一对工件占用。
    existing = set(tuple(sorted(q[k:k+size])) for q in (reference.a, reference.b)
                   for k in range(data.n-size+1))
    first = sorted(existing, key=priority)
    extra = sorted(itertools.combinations(range(data.n), size), key=priority)
    return list(dict.fromkeys(first+extra))[:limit]


def free_job_constraints(reference, jobs):
    """更宽的精确范围：所选工件可分别任意插入，未选工件仅固定相对顺序。"""
    selected = set(jobs)
    if not selected or len(selected) != len(jobs) or len(selected) >= len(reference.a) or any(
            type(j) is not int or not 0 <= j < len(reference.a) for j in jobs):
        raise ValueError('必须保留其他工件，禁止退化为完整模型')
    rows = []
    for key, value in features(reference).items():
        fixed = (key[0] == 'machine' and key[1] not in selected) or (
            key[0] == 'order' and key[2] not in selected and key[3] not in selected)
        if fixed:
            rows.append({'key': list(key), 'value': value, 'basis': 'joint_search_free_jobs'})
    return StableConstraints(reference, rows)
