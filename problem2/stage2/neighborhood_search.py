"""二阶段变邻域：连续区间与非连续自由工件重排；本入口不使用扰动。"""
from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import time
import traceback

from problem2.common.encoding import Chromosome, code_from_result, decode, evaluate
from problem2.common.export import export, write_json
from problem2.common.solver_utils import optimize_once
from problem2.common.validation import validate_exact
from problem2.stage1.neighborhoods import choose_window, critical_weights, window_constraints
from problem2.stage2.joint_search import free_job_constraints


@dataclass(frozen=True)
class SearchConfig:
    widths: tuple = (5, 7, 9)
    group_sizes: tuple = (3, 4)
    groups_per_size: int = 32
    window_stall: int = 6
    free_batch: int = 3
    window_seconds: float = 30
    free_seconds: float = 90
    attempts_per_range: int = 2
    threads: int = 8
    seed: int = 23

    def check(self, n):
        if n < 2:
            raise ValueError('二阶段至少需要两个工件')
        for seq in (self.widths, self.group_sizes):
            if not seq or any(type(v) is not int or v < 1 for v in seq):
                raise ValueError('宽度与自由工件数量必须为正整数')
        if max(self.group_sizes) > 6:
            raise ValueError('本入口最多同时放开6个工件')
        for v in (self.groups_per_size, self.window_stall, self.free_batch,
                  self.attempts_per_range, self.threads):
            if type(v) is not int or v < 1:
                raise ValueError('数量、线程数和重试次数必须为正整数')
        if type(self.seed) is not int:
            raise ValueError('种子必须为整数')
        if any(not math.isfinite(v) or v <= 0 for v in (self.window_seconds, self.free_seconds)):
            raise ValueError('单轮时间必须有限且为正')

    def dictionary(self):
        return json.loads(json.dumps(asdict(self)))


def data_digest(data):
    raw = [data.case, data.jobs, data.processing, data.setup]
    return hashlib.sha256(json.dumps(raw, ensure_ascii=False).encode('utf-8')).hexdigest()


def code_key(code):
    return json.dumps(code.as_dict(), sort_keys=True, separators=(',', ':'))


def read_code(value, n):
    if set(value) != {'a', 'b', 'machines'} or any(
            type(x) is not int for row in value.values() for x in row):
        raise ValueError('检查点编码格式错误')
    code = Chromosome(tuple(value['a']), tuple(value['b']), tuple(value['machines']))
    code.check(n)
    return code


def job_groups(data, reference, size, limit, seed):
    """交替选择关键工件组合和位置分散组合，不要求所选工件连续。"""
    if not 1 <= size < data.n or limit < 1:
        raise ValueError('自由工件数量必须小于总工件数')
    weights = critical_weights(data, reference)
    score = {j: weights['A'][j]+weights['B'][j] for j in range(data.n)}
    positions = [{j: k for k, j in enumerate(q)} for q in (reference.a, reference.b)]
    pool = sorted(range(data.n), key=lambda j: (-score[j], j))[:min(data.n, max(12, size))]
    candidates = set(itertools.combinations(sorted(pool), size))
    salt = int(hashlib.sha256(code_key(reference).encode()).hexdigest()[:16], 16)
    rng = random.Random(seed+salt+size)
    for _ in range(limit*8):
        candidates.add(tuple(sorted(rng.sample(range(data.n), size))))

    def span(jobs):
        return sum(max(p[j] for j in jobs)-min(p[j] for j in jobs) for p in positions)

    critical = sorted(candidates, key=lambda js: (-sum(score[j] for j in js), -span(js), js))
    spread = sorted(candidates, key=lambda js: (-span(js), -sum(score[j] for j in js), js))
    chosen, seen = [], set()
    for pair in zip(critical, spread):
        for jobs in pair:
            if jobs not in seen:
                chosen.append(jobs)
                seen.add(jobs)
                if len(chosen) == limit:
                    return chosen
    return chosen


class Planner:
    """只管理参考解、切换和已尝试范围；不生成时间表或复制求解模型。"""
    def __init__(self, data, reference, config):
        config.check(data.n)
        reference.check(data.n)
        self.data, self.reference, self.config = data, reference, config
        self.original = reference
        self.widths = tuple(dict.fromkeys(min(w, data.n-1) for w in config.widths))
        self.sizes = tuple(dict.fromkeys(min(s, data.n-1) for s in config.group_sizes))
        self.mode, self.width_index = 'window', 0
        self.window_failures = self.free_failures = self.round_number = 0
        self.ledger, self.records, self.pool = {}, [], None
        self.pending = None
        self.prior_reported_seconds = 0
        self.interruption_cost_unknown = False
        self.rng = random.Random(config.seed)

    def key(self, kind, payload):
        return json.dumps([code_key(self.reference), kind, payload], sort_keys=True)

    def exhausted(self, key):
        entry = self.ledger.get(key)
        return entry is not None and (entry['optimal'] or entry['attempts'] >= self.config.attempts_per_range)

    def restriction(self, request):
        if request['kind'] == 'window':
            return window_constraints(self.reference, **request['payload'])
        return free_job_constraints(self.reference, request['payload']['jobs'])

    def next_request(self):
        for _ in range(2*len(self.widths)+4):
            if self.mode == 'window':
                width = self.widths[self.width_index]
                blocked = set()
                for key, entry in self.ledger.items():
                    if entry['reference'] == code_key(self.reference) and entry['kind'] == 'window' and self.exhausted(key):
                        p = entry['payload']
                        blocked.add((self.reference, p['width'], p['start_a'], p['start_b']))
                choice = choose_window(self.data, self.reference, width, {}, blocked,
                                       self.round_number, self.rng)
                if choice is not None:
                    a, b, policy = choice
                    payload = dict(start_a=a, start_b=b, width=width)
                    return self._request('window', payload, policy)
                self.mode = 'free'
            else:
                if self.pool is None:
                    lists = [job_groups(self.data, self.reference, s, self.config.groups_per_size,
                                        self.config.seed) for s in self.sizes]
                    self.pool = [list(js) for pair in itertools.zip_longest(*lists) for js in pair if js is not None]
                for jobs in self.pool:
                    payload = {'jobs': jobs}
                    if not self.exhausted(self.key('free', payload)):
                        return self._request('free', payload, 'critical_and_spread')
                self.mode = 'window'
                self.width_index = (self.width_index+1) % len(self.widths)
                self.window_failures = 0
        return None

    def _request(self, kind, payload, policy):
        key = self.key(kind, payload)
        attempts = self.ledger.get(key, {}).get('attempts', 0)
        base = self.config.window_seconds if kind == 'window' else self.config.free_seconds
        return dict(kind=kind, payload=payload, key=key, policy=policy,
                    seconds=base*2**attempts, attempt=attempts+1)

    def begin(self, request):
        self.round_number += 1
        self.ledger[request['key']] = dict(reference=code_key(self.reference),
            kind=request['kind'], payload=request['payload'], attempts=request['attempt'], optimal=False)
        self.pending = request | {'round': self.round_number}

    def accept(self, request, result, elapsed):
        validate_exact(self.data, result)
        candidate = code_from_result(result, self.data.n)
        before, after = evaluate(self.data, self.reference), evaluate(self.data, candidate)
        if abs(after-result['objective']) > 1e-4 or after > before or not self.restriction(request).satisfies(candidate):
            raise AssertionError('二阶段求解结果目标、固定范围或参考解保留错误')
        proof = result['proof']
        if proof['scope'] != 'restricted' or proof.get('original_optimality_proven_by_this_run', False):
            raise AssertionError('二阶段子问题必须记录restricted范围')
        self.ledger[request['key']]['optimal'] = bool(proof['optimal'])
        improved = after < before
        self.records.append(dict(round=self.round_number, kind=request['kind'], payload=request['payload'],
            policy=request['policy'], attempt=request['attempt'], requested_seconds=request['seconds'], before=before, after=after,
            improved=improved, elapsed_seconds=elapsed, proof=proof))
        self.pending = None
        if improved:
            self.reference, self.mode, self.width_index = candidate, 'window', 0
            self.window_failures = self.free_failures = 0
            self.pool = None
        elif request['kind'] == 'window':
            self.window_failures += 1
            if self.window_failures >= self.config.window_stall:
                self.mode, self.free_failures = 'free', 0
        else:
            self.free_failures += 1
            if self.free_failures >= self.config.free_batch:
                self.mode = 'window'
                self.width_index = (self.width_index+1) % len(self.widths)
                self.window_failures = self.free_failures = 0
        return improved

    def checkpoint(self, seconds, metadata):
        return dict(format_version=1, data_sha256=data_digest(self.data), parameters=self.config.dictionary(),
            original_code=self.original.as_dict(), best_code=self.reference.as_dict(),
            best_value=evaluate(self.data, self.reference), mode=self.mode, width_index=self.width_index,
            window_failures=self.window_failures, free_failures=self.free_failures,
            round_number=self.round_number, ledger=self.ledger, records=self.records, pool=self.pool,
            rng_state=self.rng.getstate(), pending=self.pending,
            reported_total_seconds=self.prior_reported_seconds+seconds,
            interruption_cost_unknown=self.interruption_cost_unknown, metadata=metadata)

    @classmethod
    def restore(cls, data, config, saved):
        if saved['format_version'] != 1 or saved['data_sha256'] != data_digest(data) or saved['parameters'] != config.dictionary():
            raise ValueError('检查点版本、数据或邻域参数不一致')
        state = cls(data, read_code(saved['best_code'], data.n), config)
        if evaluate(data, state.reference) != saved['best_value']:
            raise ValueError('检查点目标值与编码不一致')
        state.original = read_code(saved['original_code'], data.n)
        for field in ('mode', 'width_index', 'window_failures', 'free_failures',
                      'round_number', 'ledger', 'records', 'pool'):
            setattr(state, field, saved[field])
        if state.mode not in ('window', 'free') or not 0 <= state.width_index < len(state.widths):
            raise ValueError('检查点邻域状态错误')
        def tuples(value):
            return tuple(tuples(v) for v in value) if isinstance(value, list) else value
        state.rng.setstate(tuples(saved['rng_state']))
        state.prior_reported_seconds = saved['reported_total_seconds']
        state.interruption_cost_unknown = saved['interruption_cost_unknown'] or saved['pending'] is not None
        return state


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name+'.tmp')
    write_json(temporary, value)
    temporary.replace(path)


def run(data, reference, output, config=None, seconds=600, max_rounds=10000, saved=None,
        started=None, deadline=None, metadata=None, solve=optimize_once, solver_env=None,
        save_source=True):
    config = config or SearchConfig()
    config.check(data.n)
    if not math.isfinite(seconds) or seconds < 0 or type(max_rounds) is not int or max_rounds < 0:
        raise ValueError('总时间须有限且非负，最大轮数须为非负整数')
    started = time.perf_counter() if started is None else started
    deadline = min(started+seconds, deadline) if deadline is not None else started+seconds
    state = Planner.restore(data, config, saved) if saved is not None else Planner(data, reference, config)
    metadata = metadata or {}
    if saved is not None and saved.get('metadata', {}).get('core_sha256') != metadata.get('core_sha256'):
        raise ValueError('续跑核心源码与原检查点不一致')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('输出目录已存在，续跑也必须使用新目录')
    output.mkdir(parents=True)
    if save_source:
        from problem2.common.paths import snapshot_source
        source_sha = snapshot_source(output/'source')
    else:
        source_sha = {}
    write_json(output/'config.json', dict(parameters=config.dictionary(), seconds=seconds,
        max_rounds=max_rounds, resumed=saved is not None, metadata=metadata,
        code_sha256=source_sha, scope='restricted', original_optimality_proven_by_this_run=False))
    first = decode(data, state.reference)
    first['validation'] = validate_exact(data, first)
    export(output/'reference', first)
    export(output/'best', first)
    segment_initial = first['objective']
    count, error, reason, own_env = 0, None, 'max_rounds', False
    env = solver_env
    elapsed = lambda: time.perf_counter()-started
    checkpoint = lambda: atomic_json(output/'checkpoint.json', state.checkpoint(elapsed(), metadata))
    checkpoint()
    try:
        for _ in range(max_rounds):
            if time.perf_counter() >= deadline:
                reason = 'time_budget'
                break
            request = state.next_request()
            if request is None:
                reason = 'selected_neighborhoods_exhausted'
                break
            if time.perf_counter() >= deadline:
                reason = 'time_budget'
                break
            restriction = state.restriction(request)
            if not restriction.satisfies(state.reference):
                raise AssertionError('新邻域排除了同一参考解')
            state.begin(request)
            checkpoint()  # 求解前也保存，强制中止后仍保留参考解与尝试次数。
            if env is None and solve is optimize_once:
                import gurobipy as gp
                env = gp.Env(empty=True)
                env.setParam('OutputFlag', 0)
                env.start()
                own_env = True
            remaining = deadline-time.perf_counter()
            if remaining <= 0:
                reason = 'time_budget'
                break
            result = solve(data, state.reference, restriction,
                output/'rounds'/f'round{state.round_number:05d}', min(request['seconds'], remaining),
                config.threads, strengthen=True, compact=True, solver_env=env, deadline=deadline)
            improved = state.accept(request, result, elapsed())
            count += 1
            if improved:
                best = decode(data, state.reference)
                best['validation'] = validate_exact(data, best)
                export(output/'best', best)
            checkpoint()
            atomic_json(output/'progress.json', dict(best=evaluate(data, state.reference),
                mode=state.mode, round=state.round_number, new_solver_calls=count,
                elapsed_seconds=elapsed(), complete=False))
            print(json.dumps(dict(kind=request['kind'], round=state.round_number,
                best=evaluate(data, state.reference), improved=improved)), flush=True)
        else:
            reason = 'max_rounds'
    except BaseException:
        error, reason = traceback.format_exc(), 'error'
        write_json(output/'failure.json', {'error': error, 'seconds': elapsed()})
        raise
    finally:
        if own_env:
            env.dispose()
        checkpoint()
        final = decode(data, state.reference)
        final['validation'] = validate_exact(data, final)
        final['scope'] = 'restricted'
        final['original_optimality_proven_by_this_run'] = False
        export(output/'final', final)
        summary = dict(complete=error is None, case=data.case, segment_initial=segment_initial,
            original_reference=evaluate(data, state.original), final=final['objective'],
            segment_seconds=elapsed(), previous_reported_seconds=state.prior_reported_seconds,
            interruption_cost_unknown=state.interruption_cost_unknown, termination=reason,
            new_solver_calls=count, total_recorded_rounds=len(state.records), records=state.records,
            perturbations=0, scope='restricted', original_optimality_proven_by_this_run=False)
        write_json(output/'summary.json', summary)
        atomic_json(output/'progress.json', dict(best=final['objective'], complete=error is None,
            termination=reason, round=state.round_number, new_solver_calls=count,
            elapsed_seconds=summary['segment_seconds']))
        checkpoint()  # 将最后一次完整调度导出、汇总写入也计入续跑的已报告成本。
    return final
