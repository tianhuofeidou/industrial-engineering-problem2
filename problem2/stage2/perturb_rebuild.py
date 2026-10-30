"""二阶段大组扰动与联合插入重建开发入口；完整评分，不调用Gurobi。"""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import time
import traceback

from problem2.common.data import load_case
from problem2.common.encoding import Chromosome, code_from_result, decode, evaluate
from problem2.common.evaluator import BudgetExpired, Evaluator
from problem2.common.export import export, write_json
from problem2.common.local_search import apply_move
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.validation import validate_exact
from problem2.stage2.neighborhood_search import atomic_json


@dataclass(frozen=True)
class RebuildConfig:
    sizes: tuple = (5, 7, 9)
    seed: int = 23
    max_passes: int = 50
    batch_size: int = 1024
    cache_limit: int = 8192
    round_seconds: float = 30

    def check(self, n):
        if n < 2 or not self.sizes or any(type(k) is not int or k < 1 for k in self.sizes):
            raise ValueError('至少两个工件，扰动数量须为正整数')
        if type(self.seed) is not int:
            raise ValueError('种子须为整数')
        if type(self.max_passes) is not int or self.max_passes < 1:
            raise ValueError('重建遍数须为正整数')
        if type(self.batch_size) is not int or not 0 <= self.batch_size <= 4096:
            raise ValueError('批大小须为0到4096的整数；0为逐个评分诊断')
        if type(self.cache_limit) is not int or self.cache_limit < 1:
            raise ValueError('缓存数量须为正整数')
        if not math.isfinite(self.round_seconds) or self.round_seconds <= 0:
            raise ValueError('单轮时间须有限且为正')


def check_jobs(code, jobs):
    jobs = tuple(jobs)
    code.check(len(code.a))
    if not jobs or len(set(jobs)) != len(jobs) or any(
            type(j) is not int or not 0 <= j < len(code.a) for j in jobs):
        raise ValueError('必须选择不重复的有效工件编号')
    return jobs


def same_unselected(reference, candidate, jobs):
    selected = set(jobs)
    return all(tuple(j for j in a if j not in selected) == tuple(j for j in b if j not in selected)
        for a, b in ((reference.a, candidate.a), (reference.b, candidate.b))) and all(
        reference.machines[j] == candidate.machines[j] for j in range(len(reference.a)) if j not in selected)


def perturb_selected(reference, jobs, rng):
    """改变所选工件在两个排列的位置，机器仍按工件编号；其余相对顺序不变。"""
    jobs = check_jobs(reference, jobs)
    current, n = reference, len(reference.a)
    if n < 2:
        raise ValueError('扰动至少需要两个工件')
    for job in jobs:
        for kind in ('insert_a', 'insert_b'):
            # A、B各按自己的当前位置移动，机器归属另按工件编号更新。
            sequence = current.a if kind == 'insert_a' else current.b
            source = sequence.index(job)
            destination = rng.randrange(n-1)
            destination += destination >= source
            current = apply_move(current, (kind, source, destination))
        if rng.random() < .5:
            current = apply_move(current, ('flip', job, job))
    if current == reference:
        current = apply_move(current, ('flip', jobs[0], jobs[0]))
    if not same_unselected(reference, current, jobs):
        raise AssertionError('扰动错误改变了未选工件的顺序或机器')
    return current


def joint_insertions(reference, job):
    """单个工件的2*n*n个完整编码；其余工件始终保留，不做残缺评分。"""
    check_jobs(reference, (job,))
    aa, bb = [], []
    for sequence, destination in ((reference.a, aa), (reference.b, bb)):
        base = tuple(j for j in sequence if j != job)
        destination.extend(base[:i]+(job,)+base[i:] for i in range(len(sequence)))
    mm = []
    for machine in (0, 1):
        value = list(reference.machines)
        value[job] = machine
        mm.append(tuple(value))
    for a, b, machines in itertools.product(aa, bb, mm):
        yield Chromosome(a, b, machines)


def repair(initial, jobs, evaluator, max_passes=50):
    """逐件联合插入下降；完成一遍无改善只说明该遍的单工件联合邻域。"""
    jobs = check_jobs(initial, jobs)
    if type(max_passes) is not int or max_passes < 1:
        raise ValueError('重建遍数须为正整数')
    current, before = initial, evaluate(evaluator.data, initial)
    cost = before
    start, evaluations = time.perf_counter(), evaluator.evaluations
    passes, scans, terminated = 0, 0, 'pass_limit'
    try:
        cost = evaluator.cost(current)
        for _ in range(max_passes):
            improved = False
            for job in jobs:
                local, local_cost = current, cost
                try:
                    for candidate, value in evaluator.costs(joint_insertions(current, job)):
                        if value < local_cost:
                            local, local_cost = candidate, value
                except BudgetExpired:
                    current, cost = local, local_cost
                    raise
                improved |= local_cost < cost
                current, cost = local, local_cost
                scans += 1
            passes += 1
            if not improved:
                terminated = 'selected_coordinate_stable'
                break
    except BudgetExpired:
        terminated = 'time_budget'
    return current, dict(before=before, after=cost, passes=passes, completed_job_scans=scans,
        evaluations=evaluator.evaluations-evaluations, termination=terminated,
        seconds=time.perf_counter()-start, original_optimality_proven_by_this_run=False)


def run(data, reference, output, config=None, seconds=60, max_rounds=3,
        started=None, metadata=None, save_source=True):
    config = config or RebuildConfig()
    config.check(data.n)
    reference.check(data.n)
    if not math.isfinite(seconds) or seconds < 0 or type(max_rounds) is not int or max_rounds < 0:
        raise ValueError('总时间须有限且非负，轮数须为非负整数')
    started = time.perf_counter() if started is None else started
    deadline = started+seconds
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('输出目录必须不存在')
    output.mkdir(parents=True)
    source = snapshot_source(output/'source') if save_source else {}
    write_json(output/'config.json', dict(parameters=asdict(config), seconds=seconds,
        max_rounds=max_rounds, metadata=metadata or {}, source_sha256=source,
        historical_reference_cost_included=False, solver_calls=0,
        original_optimality_proven_by_this_run=False))
    initial = decode(data, reference)
    initial['validation'] = validate_exact(data, initial)
    export(output/'reference', initial)
    export(output/'best', initial)
    evaluator = Evaluator(data, cache_limit=config.cache_limit, batch_size=config.batch_size)
    evaluator.cost(reference)  # 基准完整评分也计入记录；其后才开始候选预算检查。
    evaluator.deadline = deadline
    rng = random.Random(config.seed)
    sizes = tuple(dict.fromkeys(min(k, data.n) for k in config.sizes))
    size_index, rows, error, reason = 0, [], None, 'max_rounds'
    try:
        for number in range(1, max_rounds+1):
            if time.perf_counter() >= deadline:
                reason = 'time_budget'
                break
            base = evaluator.best
            before = evaluator.best_cost
            jobs = tuple(rng.sample(range(data.n), sizes[size_index]))
            tick, count_before = time.perf_counter(), evaluator.evaluations
            trial = perturb_selected(base, jobs, rng)
            trial_value = evaluate(data, trial)
            evaluator.deadline = min(deadline, tick+config.round_seconds)
            repaired, diagnostic = repair(trial, jobs, evaluator, config.max_passes)
            evaluator.deadline = deadline
            if not same_unselected(base, repaired, jobs):
                raise AssertionError('重建错误改变了未选工件的相对顺序或机器')
            # Evaluator先记录整批已评分候选；到时或中断一遍时也不会丢失该批最好解。
            if evaluate(data, evaluator.best) != evaluator.best_cost:
                raise AssertionError('批量最好分数与完整逐个评分不一致')
            improved = evaluator.best_cost < before
            row = dict(round=number, selected=list(jobs), size=len(jobs), before=before,
                perturbed=trial_value, repaired=evaluate(data, repaired), best=evaluator.best_cost,
                improved=improved, base=base.as_dict(), perturbed_code=trial.as_dict(),
                repaired_code=repaired.as_dict(), best_code=evaluator.best.as_dict(),
                evaluations=evaluator.evaluations-count_before, seconds=time.perf_counter()-tick,
                diagnostic=diagnostic)
            rows.append(row)
            write_json(output/'rounds.json', rows)
            atomic_json(output/'checkpoint.json', dict(best_code=evaluator.best.as_dict(),
                best=evaluator.best_cost, completed_rounds=len(rows), rng_state=rng.getstate(),
                elapsed_seconds=time.perf_counter()-started, resumable_search_state=False))
            if improved:
                best = decode(data, evaluator.best)
                best['validation'] = validate_exact(data, best)
                export(output/'best', best)
            size_index = 0 if improved else (size_index+1) % len(sizes)
            print(json.dumps(dict(round=number, size=len(jobs), perturb=trial_value,
                                  best=evaluator.best_cost, termination=diagnostic['termination'])), flush=True)
        else:
            reason = 'max_rounds'
    except BaseException:
        error, reason = traceback.format_exc(), 'error'
        write_json(output/'failure.json', dict(error=error))
        raise
    finally:
        final = decode(data, evaluator.best)
        final['validation'] = validate_exact(data, final)
        final['original_optimality_proven_by_this_run'] = False
        export(output/'best', final)
        export(output/'final', final)
        write_json(output/'rounds.json', rows)
        atomic_json(output/'checkpoint.json', dict(best_code=evaluator.best.as_dict(),
            best=evaluator.best_cost, completed_rounds=len(rows), rng_state=rng.getstate(),
            elapsed_seconds=time.perf_counter()-started, resumable_search_state=False))
        summary = dict(complete=error is None, initial=initial['objective'], best=final['objective'],
            rounds_completed=len(rows), termination=reason, evaluations=evaluator.evaluations,
            cache_hits=evaluator.cache_hits, cached_codes=len(evaluator.cache),
            cache_limit=config.cache_limit, improvements=evaluator.progress,
            seconds=time.perf_counter()-started, solver_calls=0,
            search='perturb_selected_jobs_then_joint_single_job_repair',
            original_optimality_proven_by_this_run=False,
            exhaustive_large_group_search=False, rows=rows)
        write_json(output/'summary.json', summary)
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=int, choices=(1, 2), required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--max-rounds', type=int, default=3)
    parser.add_argument('--sizes', type=int, nargs='+', default=[5, 7, 9])
    parser.add_argument('--seed', type=int, default=23)
    parser.add_argument('--max-passes', type=int, default=50)
    parser.add_argument('--batch-size', type=int, default=1024)
    parser.add_argument('--cache-limit', type=int, default=8192)
    parser.add_argument('--round-seconds', type=float, default=30)
    args = parser.parse_args()
    started = time.perf_counter()
    if args.output.exists():
        parser.error('输出目录已存在')
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', args.case)
    raw = args.reference.read_bytes()
    result = json.loads(raw.decode('utf-8-sig'))
    if result['case'] != args.case:
        parser.error('参考解算例错误')
    validate_exact(data, result)
    reference = code_from_result(result, data.n)
    metadata = dict(input_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (PROJECT_ROOT/'问题2.pdf', PROJECT_ROOT/'问题2数据.xlsx')},
        reference=str(args.reference.resolve()), reference_sha256=hashlib.sha256(raw).hexdigest())
    config = RebuildConfig(tuple(args.sizes), args.seed, args.max_passes, args.batch_size,
                           args.cache_limit, args.round_seconds)
    final = run(data, reference, args.output, config, args.seconds, args.max_rounds,
                started=started, metadata=metadata)
    print(json.dumps(dict(final=final['objective'], total_seconds=time.perf_counter()-started)))


if __name__ == '__main__':
    main()
