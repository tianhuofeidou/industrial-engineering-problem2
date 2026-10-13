"""记录搜索实际保留的关系及打破关系的尝试；不改变随机数或接受规则。"""
from collections import deque
from dataclasses import dataclass, asdict
from time import perf_counter


def queues(code):
    return {'A': code.a, 'B': code.b,
            '6-1': tuple(j for j in code.b if code.machines[j] == 0),
            '6-2': tuple(j for j in code.b if code.machines[j] == 1)}


def features(code):
    n = len(code.a)
    result = {('machine', j): m for j, m in enumerate(code.machines)}
    for q, order in queues(code).items():
        result.update({('adj', q, i, j): 1 for i, j in zip((-1,)+order, order+(n,))})
        if q in ('A', 'B'):
            ranks = {j: k for k, j in enumerate(order)}
            result.update({('order', q, i, j): int(ranks[i] < ranks[j])
                           for i in range(n) for j in range(i+1, n)})
    return result


def signature(code):
    """候选只生成位置和相邻弧，不为每个试探复制全部两两关系。"""
    q = queues(code)
    ranks = {k: {j: i for i, j in enumerate(q[k])} for k in ('A', 'B')}
    edges = {k: set(zip((-1,)+v, v+(len(code.a),))) for k, v in q.items()}
    return code.machines, ranks, edges


def matches(key, value, sig):
    machines, ranks, edges = sig
    if key[0] == 'machine':
        return machines[key[1]] == value
    if key[0] == 'order':
        _, q, i, j = key
        return int(ranks[q][i] < ranks[q][j]) == value
    _, q, i, j = key
    return ((i, j) in edges[q]) == bool(value)


@dataclass(frozen=True)
class EvidenceConfig:
    min_attempts: int = 20
    min_perturbations: int = 10
    restore_ratio: float = 0.8
    min_late_samples: int = 5
    late_samples: int = 24
    quality_ratio: float = 1.03

    def check(self):
        if min(self.min_attempts, self.min_perturbations, self.min_late_samples) < 1:
            raise ValueError('证据次数必须为正')
        if self.late_samples < self.min_late_samples or not 0 <= self.restore_ratio <= 1 or self.quality_ratio < 1:
            raise ValueError('后期样本数量、恢复比例或质量比例无效')


class RelationTracker:
    def __init__(self, initial, cost, method, config=None):
        self.config = config or EvidenceConfig()
        self.config.check()
        self.method = method
        self.original = features(initial)
        self.active = dict(self.original)
        self.keys = list(self.original)
        self.key_indices = {k: i for i, k in enumerate(self.keys)}
        self.active_mask = (1 << len(self.keys))-1
        self.stats = {k: {'attempts': 0, 'blocked': 0, 'eligible': 0, 'hot': 0,
                          'delta_sum': 0, 'delta_min': None, 'perturbed': 0,
                          'restored': 0, 'unrestored_best_delta': None,
                          'selection_checks': 0, 'selection_gap_sum': 0,
                          'selection_gap_min': None} for k in self.original}
        self.accepted_changes = 0
        self.pending = {}
        self.initial_temperature = None
        self.samples = deque(maxlen=64)
        self.sample_codes = set()
        self.matching_cache = {}
        self.sample(initial, cost)
        self.seconds = 0.0

    def sample(self, code, cost):
        # 同一个编码重复停留不增加支持次数；只保留有限个不同编码。
        if code in self.sample_codes:
            return
        if len(self.samples) == self.samples.maxlen:
            old, _ = self.samples.popleft()
            self.sample_codes.remove(old)
        self.samples.append((code, cost))
        self.sample_codes.add(code)

    def matching_mask(self, code):
        """一个位表示一条关系成立；全程稳定集合只缩小，因此旧缓存仍可用。"""
        mask = self.matching_cache.get(code)
        if mask is not None:
            return mask
        mask, ranks, edges = 0, {}, {}
        for key, value in self.active.items():
            if key[0] == 'machine':
                present = code.machines[key[1]] == value
            elif key[0] == 'order':
                _, q, i, j = key
                if q not in ranks:
                    ranks[q] = {job: pos for pos, job in enumerate(code.a if q == 'A' else code.b)}
                present = int(ranks[q][i] < ranks[q][j]) == value
            else:
                _, q, i, j = key
                if q not in edges:
                    order = code.a if q == 'A' else code.b
                    if q.startswith('6'):
                        order = tuple(job for job in order if code.machines[job] == int(q[-1])-1)
                    edges[q] = set(zip((-1,)+order, order+(len(code.a),)))
                present = (i, j) in edges[q]
            if present:
                mask |= 1 << self.key_indices[key]
        if len(self.matching_cache) >= 20000:
            self.matching_cache.clear()
        self.matching_cache[code] = mask
        return mask

    def mask_keys(self, mask):
        while mask:
            bit = mask & -mask
            yield self.keys[bit.bit_length()-1]
            mask ^= bit

    def trial(self, before, after, before_cost, cost, *, blocked=False, temperature=None):
        if not self.active:
            return []
        started = perf_counter()
        broken = list(self.mask_keys(self.matching_mask(before) & ~self.matching_mask(after) & self.active_mask))
        delta = cost-before_cost
        for key in broken:
            row = self.stats[key]
            row['attempts'] += 1
            row['blocked'] += int(blocked)
            if not blocked:
                row['eligible'] += 1
                row['delta_sum'] += delta
                row['delta_min'] = delta if row['delta_min'] is None else min(row['delta_min'], delta)
                if temperature is not None and temperature >= self.initial_temperature*0.1:
                    row['hot'] += 1
                if self.method == 'tabu':
                    self.pending[key] = min(self.pending.get(key, cost), cost)
        self.seconds += perf_counter()-started
        return broken

    def accepted(self, code, cost):
        started = perf_counter()
        if self.active:
            mask = self.active_mask & self.matching_mask(code)
            if mask != self.active_mask:
                self.active_mask = mask
                self.active = {k: self.original[k] for k in self.mask_keys(mask)}
        self.accepted_changes += 1
        self.sample(code, cost)
        self.seconds += perf_counter()-started

    def tabu_selected(self, cost):
        started = perf_counter()
        for key, best_breaking in self.pending.items():
            row, gap = self.stats[key], best_breaking-cost
            row['selection_checks'] += 1
            row['selection_gap_sum'] += gap
            row['selection_gap_min'] = gap if row['selection_gap_min'] is None else min(row['selection_gap_min'], gap)
        self.pending.clear()
        self.seconds += perf_counter()-started

    def perturbation(self, before, shaken, final, before_cost, final_cost):
        started = perf_counter()
        if not self.active:
            self.sample(final, final_cost)
            self.seconds += perf_counter()-started
            return
        a, b, c = self.matching_mask(before), self.matching_mask(shaken), self.matching_mask(final)
        for key in self.mask_keys(a & ~b & self.active_mask):
            row = self.stats[key]
            row['perturbed'] += 1
            if c & (1 << self.key_indices[key]):
                row['restored'] += 1
            else:
                delta = final_cost-before_cost
                old = row['unrestored_best_delta']
                row['unrestored_best_delta'] = delta if old is None else min(old, delta)
        self.sample(final, final_cost)
        self.seconds += perf_counter()-started

    def descent_trial(self, before, after, before_cost, cost):
        self.trial(before, after, before_cost, cost)

    def report(self, best, best_cost):
        started = perf_counter()
        target = features(best)
        rows = []
        for key, value in self.original.items():
            row = dict(self.stats[key])
            stable = key in self.active
            compatible = target.get(key) == value
            supported = row['eligible'] >= self.config.min_attempts
            if self.method == 'annealing':
                supported &= row['hot'] >= max(1, self.config.min_attempts//4)
            elif self.method == 'tabu':
                supported &= row['selection_checks'] > 0 and row['selection_gap_sum'] > 0
            elif self.method == 'vns':
                supported = (row['perturbed'] >= self.config.min_perturbations
                             and row['restored']/row['perturbed'] >= self.config.restore_ratio
                             and (row['unrestored_best_delta'] is None or row['unrestored_best_delta'] > 0))
            rows.append({'key': list(key), 'value': value, 'whole_run_stable': stable,
                         'compatible_with_best': compatible, 'selected': bool(stable and compatible and supported),
                         'basis': 'whole_run', **row})
        eligible = [(c, v) for c, v in self.samples if v <= best_cost*self.config.quality_ratio]
        eligible = eligible[-self.config.late_samples:]
        # 最好编码也参加交集；后期一致仍单独标注，不冒充全程稳定。
        late = dict(target)
        for code, _ in eligible:
            sig = signature(code)
            late = {k: v for k, v in late.items() if matches(k, v, sig)}
        selected = {tuple(r['key']) for r in rows if r['selected']}
        if len(eligible) >= self.config.min_late_samples:
            for key, value in late.items():
                if key not in selected:
                    rows.append({'key': list(key), 'value': value, 'basis': 'late_samples',
                                 'whole_run_stable': key in self.active, 'compatible_with_best': True,
                                 'selected': True, 'distinct_samples': len(eligible)})
        self.seconds += perf_counter()-started
        return {'method': self.method, 'config': asdict(self.config), 'accepted_updates': self.accepted_changes,
                'initial_relations': len(self.original), 'whole_run_stable': len(self.active),
                'late_distinct_samples': len(eligible), 'tracking_seconds': self.seconds,
                'statistics_stop_after_first_accepted_change': True,
                'whole_run_means_outer_accepted_states_for_vns': True, 'relations': rows}
