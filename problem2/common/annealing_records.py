"""持续记录退火改变的关系；优质编码的一致性只提供受限求解的候选依据。"""
from collections import Counter
from dataclasses import asdict, dataclass
from time import perf_counter
from problem2.common.encoding import Chromosome
from problem2.common.relation_tracking import features, signature, matches
from problem2.common.stable_constraints import StableConstraints, arc_constants, propagated_decisions


@dataclass(frozen=True)
class SelectionConfig:
    quality_ratio: float = 1.01
    agreement: float = .95
    min_samples: int = 5
    min_seeds: int = 2
    min_attempts: int = 20
    max_samples: int = 1024

    def check(self):
        if self.quality_ratio < 1 or not 0 < self.agreement <= 1:
            raise ValueError('质量比例至少为1，一致比例在(0,1]内')
        if min(self.min_samples, self.min_seeds, self.min_attempts) < 1 or self.max_samples < self.min_samples:
            raise ValueError('样本、种子、试探次数必须为正')


def changed_relations(before, operation):
    """插入最多改变n-1对先后，交换最多改变2n-3对；不扫描全部工件对。"""
    kind, i, j = operation
    if kind == 'flip':
        return [(('machine', i), before.machines[i])]
    q = 'A' if kind.endswith('_a') else 'B'
    order = before.a if q == 'A' else before.b
    result = []
    def add(left, right):
        a, b = sorted((left, right))
        result.append((('order', q, a, b), int(left == a)))
    if kind.startswith('insert'):
        if i < j:
            for other in order[i+1:j+1]:
                add(order[i], other)
        else:
            for other in order[j:i]:
                add(other, order[i])
    else:
        i, j = sorted((i, j))
        add(order[i], order[j])
        for other in order[i+1:j]:
            add(order[i], other)
            add(other, order[j])
    return result


class AnnealingRecords:
    """观察器不调用随机数、不评价额外候选；首次改变后仍继续统计。"""
    def __init__(self, initial, cost, seed, config=None):
        self.seed, self.config = seed, config or SelectionConfig()
        self.config.check()
        self.initial_temperature = None
        self.best_cost = cost
        self.best_code = initial
        self.samples = {initial: cost}
        self.stats = {}
        self.current_operation = None
        self.pending = []
        self.trials = self.accepted_updates = 0
        self.seconds = 0.0

    def operation(self, operation):
        self.current_operation = operation

    def sample(self, code, cost):
        if cost <= self.best_cost*self.config.quality_ratio:
            self.samples[code] = cost
        if len(self.samples) > self.config.max_samples*2:
            ordered = sorted(self.samples, key=lambda c: (self.samples[c], c.a, c.b, c.machines))
            self.samples = {c: self.samples[c] for c in ordered[:self.config.max_samples]}

    def trial(self, before, after, before_cost, cost, *, temperature=None):
        started = perf_counter()
        if self.current_operation is None:
            raise ValueError('持续记录需要同一次抽取的移动信息')
        self.pending = changed_relations(before, self.current_operation)
        delta = cost-before_cost
        for key, value in self.pending:
            row = self.stats.setdefault(key, {'attempts': [0, 0], 'accepted': [0, 0],
                    'hot_attempts': [0, 0], 'delta_sum': [0, 0], 'delta_min': [None, None]})
            row['attempts'][value] += 1
            row['delta_sum'][value] += delta
            old = row['delta_min'][value]
            row['delta_min'][value] = delta if old is None else min(old, delta)
            if temperature is not None and temperature >= self.initial_temperature*.1:
                row['hot_attempts'][value] += 1
        self.trials += 1
        if cost < self.best_cost:
            self.best_cost, self.best_code = cost, after
            self.sample(after, cost)
        self.seconds += perf_counter()-started

    def accepted(self, code, cost):
        started = perf_counter()
        for key, value in self.pending:
            self.stats[key]['accepted'][value] += 1
        self.accepted_updates += 1
        self.sample(code, cost)
        self.seconds += perf_counter()-started

    def report(self):
        eligible = sorted((c for c in self.samples if self.samples[c] <= self.best_cost*self.config.quality_ratio),
                          key=lambda c: (self.samples[c], c.a, c.b, c.machines))[:self.config.max_samples]
        return {'seed': self.seed, 'config': asdict(self.config), 'best_cost': self.best_cost,
                'best_code': self.best_code.as_dict(), 'trials': self.trials,
                'accepted_updates': self.accepted_updates, 'tracking_seconds': self.seconds,
                'statistics_continue_after_accepted_change': True,
                'delta_means_complete_candidate_difference_not_single_relation_effect': True,
                'samples': [{'code': c.as_dict(), 'objective': self.samples[c]} for c in eligible],
                'relations': [{'key': list(k), **v} for k, v in sorted(self.stats.items())]}


def as_code(raw):
    return Chromosome(tuple(raw['a']), tuple(raw['b']), tuple(raw['machines']))


def select_relations(reference, reference_cost, reports, config=None):
    config = config or SelectionConfig()
    config.check()
    if len({r['seed'] for r in reports}) != len(reports):
        raise ValueError('不同种子的记录不能重复计数')
    groups = []
    for report in reports:
        unique = {as_code(row['code']): row['objective'] for row in report['samples']
                  if row['objective'] <= report['best_cost']*config.quality_ratio}
        if len(unique) >= config.min_samples:
            groups.append((report['seed'], [(signature(c), v) for c, v in unique.items()],
                           {tuple(row['key']): row for row in report['relations']}))
    selected, evidence = [], []
    for key, value in features(reference).items():
        if key[0] not in ('machine', 'order'):
            continue
        supports, attempts, veto = [], 0, False
        for seed, samples, stats in groups:
            count = sum(matches(key, value, sig) for sig, cost in samples)
            supports.append({'seed': seed, 'distinct_samples': len(samples), 'matching': count,
                             'agreement': count/len(samples)})
            attempts += stats.get(key, {'attempts': [0, 0]})['attempts'][value]
            # 同等或更好的完整编码已打破该关系时，先保留其自由。
            veto |= any(cost <= reference_cost and not matches(key, value, sig) for sig, cost in samples)
        minimum = min((r['agreement'] for r in supports), default=0)
        chosen = (len(groups) >= config.min_seeds and minimum >= config.agreement
                  and attempts >= config.min_attempts and not veto)
        row = {'key': list(key), 'value': value, 'basis': 'independent_quality_samples',
               'supports': supports, 'minimum_agreement': minimum, 'eligible': attempts,
               'better_or_equal_opposite_sample': veto, 'selected': chosen}
        evidence.append(row)
        if chosen:
            selected.append(row)
    restriction = StableConstraints(reference, selected)
    assert restriction.satisfies(reference)
    return restriction, {'config': asdict(config), 'valid_seeds': [g[0] for g in groups],
                         'selected': len(selected), 'selected_types': dict(Counter(r['key'][0] for r in selected)),
                         'relations': evidence, 'scope': 'restricted'}


def model_counts(restriction):
    """按共享模型的同一常量代入规则静态计数；不启动Gurobi。"""
    n = len(restriction.reference.a)
    machines, orders, arcs = restriction.decisions()
    machines, orders, arcs = propagated_decisions(n, machines, orders, arcs)
    remaining_arcs = {}
    for q in ('A', 'B', '6-1', '6-2'):
        edges, constants = arc_constants(n, q, machines, orders, arcs, strengthen=True)
        remaining_arcs[q] = len(edges)-len(constants)
    full = 5*n*n+5*n+2
    remaining = sum(remaining_arcs.values())+2*(n-len(machines))+n*(n-1)-len(orders)
    return {'full_binary_variables': full, 'binary_variables': remaining,
            'substituted_binary_variables': full-remaining, 'remaining_arcs': remaining_arcs,
            'fixed_machine_jobs': len(machines), 'fixed_orders_after_inference': len(orders),
            'fixed_arcs_after_inference': len(arcs), 'direct_relations': len(restriction.records)}


def release_weak(restriction, fraction=.25):
    from math import ceil
    ordered = sorted(restriction.records, key=lambda r: (r['minimum_agreement'], r['eligible'], str(r['key'])))
    remove = max(1, ceil(len(ordered)*fraction)) if ordered else 0
    # 每轮重新生成推论；不保存旧的传递关系或相邻弧常量。
    return StableConstraints(restriction.reference, ordered[remove:])
