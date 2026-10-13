"""用不同搜索的关系记录选区间；固定区间外的参考顺序，精确重排区间内工件。"""
from collections import Counter
from problem2.common.encoding import decode
from problem2.common.relation_tracking import features, signature, matches
from problem2.common.stable_constraints import StableConstraints


def window_constraints(reference, start_a, start_b, width):
    n = len(reference.a)
    if not 1 <= width <= n or not 0 <= start_a <= n-width or not 0 <= start_b <= n-width:
        raise ValueError('区间范围无效')
    free_a = set(reference.a[start_a:start_a+width])
    free_b = set(reference.b[start_b:start_b+width])
    free_machines = free_a | free_b
    rows = []
    for key, value in features(reference).items():
        fixed = key[0] == 'machine' and key[1] not in free_machines
        if key[0] == 'order':
            free = free_a if key[1] == 'A' else free_b
            fixed = not (key[2] in free and key[3] in free)
        if fixed:
            rows.append({'key': list(key), 'value': value, 'basis': 'reference_outside_window'})
    return StableConstraints(reference, rows)


def consensus_constraints(reference, samples_by_seed, quality_ratio=1.03):
    """多次独立搜索共同支持才固定；返回样本分歧用于选择要打开的位置。"""
    target = features(reference)
    best_cost = min(value for samples in samples_by_seed for _, value in samples)
    selected = dict(target)
    counts = Counter()
    sample_count, supported_seeds = 0, 0
    for samples in samples_by_seed:
        distinct = {code: value for code, value in samples if value <= best_cost*quality_ratio}
        if not distinct:
            continue
        supported_seeds += 1
        for code in distinct:
            sig = signature(code)
            counts.update(key for key, value in target.items() if matches(key, value, sig))
            selected = {key: value for key, value in selected.items() if matches(key, value, sig)}
            sample_count += 1
    rows = [{'key': list(key), 'value': value, 'basis': 'independent_runs',
             'distinct_samples': sample_count, 'supported_seeds': supported_seeds}
            for key, value in selected.items()] if supported_seeds >= 2 else []
    uncertainty = {key: 1-counts[key]/sample_count for key in target} if sample_count else {}
    return StableConstraints(reference, rows), uncertainty, {'distinct_samples': sample_count,
                                                           'supported_seeds': supported_seeds}


def critical_weights(data, reference, details=False):
    """从最后完工反向检查取等号的时间递推，统计各工件在前、后段的加工时长。"""
    result = decode(data, reference)
    records = {(r['job'], r['station']): r for r in result['operations']}
    end = result['objective']
    pending = [(j, 10) for j in range(data.n) if records[j, 10]['finish'] == end]
    previous_b = {j: reference.b[k-1] if k else None for k, j in enumerate(reference.b)}
    seen = set()
    weights = {'A': Counter(), 'B': Counter()}
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        j, stage = node
        r = records[node]
        q = 'A' if stage <= 5 else 'B'
        weights[q][j] += r['finish']-r['setup_start']
        prev = r['predecessor']
        if prev is not None and records[prev, stage]['finish'] == r['setup_start']:
            pending.append((prev, stage))
        if stage > 1 and records[j, stage-1]['finish'] == r['setup_start']:
            pending.append((j, stage-1))
        if stage == 6:
            prior = previous_b[j]
            if prior is not None and records[prior, 6]['finish'] == r['finish']:
                pending.append((prior, 6))
    return (weights, seen, records) if details else weights


def choose_window(data, reference, width, uncertainty, seen, iteration, rng):
    critical = critical_weights(data, reference)
    unstable = {'A': Counter(), 'B': Counter()}
    for key, value in uncertainty.items():
        if key[0] == 'machine':
            for q in unstable:
                unstable[q][key[1]] += value
        elif key[0] == 'order':
            for j in key[2:]:
                unstable[key[1]][j] += value
    scores = {}
    policy = ('critical', 'unstable', 'random')[iteration % 3]
    for q, sequence in [('A', reference.a), ('B', reference.b)]:
        primary = unstable[q] if policy == 'unstable' else critical[q]
        scores[q] = [sum(primary[j] for j in sequence[k:k+width]) for k in range(data.n-width+1)]
    candidates = [(a, b) for a in range(data.n-width+1) for b in range(data.n-width+1)
                  if (reference, width, a, b) not in seen]
    if not candidates:
        return None
    if policy == 'random':
        a, b = rng.choice(candidates)
    else:
        # 同分只用已固定种子的随机数，不用已知最优排列或目标。
        a, b = max(candidates, key=lambda ab: (scores['A'][ab[0]]+scores['B'][ab[1]], rng.random()))
    seen.add((reference, width, a, b))
    return a, b, policy
