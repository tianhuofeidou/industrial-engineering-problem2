"""Case 2限时多起点高温退火与区间精确重排，实时保存全局最好值下降过程。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
import argparse
import csv
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from problem2.common.data import load_case
from problem2.common.encoding import code_from_result, decode, evaluate
from problem2.common.solver import export
from problem2.common.validation import validate_exact
from problem2.stage1.config import ComparisonConfig
from problem2.stage1.construction import initialize
from problem2.stage1.annealing import run_annealing
from problem2.stage1.windows import refine_windows
from problem2.common.export import write_json
from problem2.common.exact_cache import ExactCache


class Trace:
    def __init__(self, data, initial, output, started_at):
        self.data, self.best, self.output, self.started_at = data, initial, output, started_at
        self.best_cost, self.events, self.improvements = evaluate(data, initial), [], []
        self.run = 'reference'
        self.initial_elapsed = time.time()-started_at
        self.monotonic_start = time.perf_counter()
        self.stream = (output/'events.jsonl').open('w', encoding='utf-8', newline='\n')
        self.record('reference', 'existing_incumbent', initial, elapsed_seconds=0,
                    previously_computed=True)

    def elapsed(self):
        return self.initial_elapsed+time.perf_counter()-self.monotonic_start

    def record(self, phase, event, code, **extra):
        value = evaluate(self.data, code)
        improved = value < self.best_cost
        if improved:
            self.best, self.best_cost = code, value
            result = decode(self.data, code)
            result['validation'] = validate_exact(self.data, result)
            result['discovery'] = {'elapsed_seconds': self.elapsed(), 'phase': phase, 'run': self.run}
            export(self.output/'improvements'/f'best{len(self.improvements)+1:03d}', result)
            export(self.output/'best', result)
        row = {'elapsed_seconds': self.elapsed(), 'run': self.run, 'phase': phase, 'event': event,
               'candidate_best': value, 'global_best': self.best_cost, 'global_improvement': improved, **extra}
        self.events.append(row)
        if improved:
            self.improvements.append(row | {'code': code.as_dict()})
            print(json.dumps({'phase': 'global_improvement', **row}), flush=True)
        self.stream.write(json.dumps(row, ensure_ascii=False)+'\n')
        self.stream.flush()
        if improved or event.endswith('end'):
            write_json(self.output/'progress.json', {'best': self.best_cost, 'elapsed_seconds': self.elapsed(),
                       'improvements': self.improvements, 'current_run': self.run})

    def annealing(self, event, code, row):
        self.record('annealing', event, code, **row)

    def exact(self, code, row):
        self.record('gurobi', 'round_end', code, round=row['round'], width=row['width'],
                    window_a=row['window_a'], window_b=row['window_b'],
                    range_before=row['before'], range_after=row['after'], policy=row['policy'],
                    solver_runtime=row['proof']['runtime'], solver_status=row['proof']['status'],
                    range_bound=row['proof']['bound'], range_optimal=row['proof']['optimal'],
                    cache_hit=row['proof'].get('cache_hit', False),
                    binary_variables=row['proof']['reduction']['binary_variables'])

    def close(self):
        self.stream.close()
        fields = sorted({key for row in self.events for key in row})
        with (self.output/'history.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(self.events)
        write_json(self.output/'history.json', {'events': self.events, 'improvements': self.improvements})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=1800)
    parser.add_argument('--started-at', type=float, required=True, help='整个任务开始的Unix秒数，包含准备时间')
    parser.add_argument('--reserve-seconds', type=float, default=90)
    parser.add_argument('--exploration-seconds', type=float, default=1260)
    parser.add_argument('--temperature-multiplier', type=float, default=2)
    parser.add_argument('--cooling', type=float, default=0.97)
    parser.add_argument('--annealing-seconds', type=float, default=90, help='每次退火时间上限')
    parser.add_argument('--cycle-solver-seconds', type=float, default=110, help='每个起点的精确阶段上限')
    parser.add_argument('--focus-seconds', type=float, default=100, help='每段集中精确搜索的上限')
    parser.add_argument('--seed', type=int, default=2026101101)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--reuse-initialization', action='store_true', help='新构造一次后复用该编码，并更换退火种子')
    parser.add_argument('--no-range-cache', action='store_true', help='关闭跨阶段已证明范围缓存，供对照')
    parser.add_argument('--no-batch-descent', action='store_true', help='关闭大算例初始化批量评分，供对照')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = ComparisonConfig(sa_temperature_multiplier=args.temperature_multiplier, sa_cooling=args.cooling)
    config.check()
    if args.output.exists():
        parser.error('输出目录已存在')
    if not 0 < args.reserve_seconds < args.seconds or args.threads < 1:
        parser.error('预留时间必须在总预算内，线程数必须为正')
    if min(args.annealing_seconds, args.cycle_solver_seconds, args.focus_seconds) <= 0:
        parser.error('各阶段时间上限必须为正')
    project, output = PROJECT_ROOT, args.output.resolve()
    data = load_case(project/'问题2数据.xlsx', 2)
    saved = json.loads(args.reference.read_text(encoding='utf-8'))
    validate_exact(data, saved)
    initial = code_from_result(saved, data.n)
    output.mkdir(parents=True)
    source = output/'source'
    source.mkdir()
    hashes = {}
    for p in source_files(project):
        raw = p.read_bytes()
        copy_source_file(p, source, raw)
        hashes[source_relative(p)] = hashlib.sha256(raw).hexdigest()
    write_json(output/'config.json', {'arguments': vars(args) | {'output': '.', 'reference': True},
               'search': asdict(config), 'code_sha256': hashes,
               'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (project/'问题2.pdf', project/'问题2数据.xlsx')},
               'reference_objective': saved['objective'],
               'includes_previous_reference_computation_time': False,
               'scope': 'restricted', 'original_optimality_proven_by_this_run': False})
    warm = decode(data, initial)
    warm['validation'] = validate_exact(data, warm)
    export(output/'reference', warm)
    export(output/'best', warm)
    trace = Trace(data, initial, output, args.started_at)
    work_deadline = time.perf_counter()+max(0, args.seconds-args.reserve_seconds-trace.elapsed())
    records, cycle = [], 0
    exact_cache = ExactCache() if not args.no_range_cache else None
    construction_code = construction_info = None
    write_json(output/'summary.json', {'complete': False, 'case': 2, 'records': [],
               'reference_objective': saved['objective']})
    try:
        while trace.elapsed() < args.exploration_seconds and time.perf_counter() < work_deadline-min(90, args.annealing_seconds):
            cycle += 1
            trace.run = f'cycle{cycle:02d}'
            seed = args.seed+13*(cycle-1)
            folder = output/trace.run
            folder.mkdir()
            trace.record('initialization', 'start', trace.best, seed=seed)
            if cycle == 1:
                code, info = trace.best, {'seconds': 0, 'source': 'previous_incumbent', 'local_best': trace.best_cost}
            elif args.reuse_initialization and construction_code is not None:
                code = construction_code
                info = {'seconds': 0, 'source': 'reused_construction', 'local_best': evaluate(data, code),
                        'construction_seed': construction_info['seed'], 'reused': True,
                        'complete': construction_info['complete']}
            else:
                code, info = initialize(data, seed, config, deadline=work_deadline,
                                        batch_descent=not args.no_batch_descent)
                construction_code, construction_info = code, info
            trace.record('initialization', 'end', code, seed=seed, initialization=info)
            schedule = decode(data, code)
            schedule['validation'] = validate_exact(data, schedule)
            export(folder/'initial', schedule)
            outcome = run_annealing(data, code, seed, config, deadline=min(work_deadline, time.perf_counter()+args.annealing_seconds),
                                    on_event=trace.annealing)
            trace.record('annealing', 'end', outcome.search.best, seed=seed, termination=outcome.termination,
                         stage_seconds=outcome.search.seconds)
            annealed = decode(data, outcome.search.best)
            annealed['validation'] = validate_exact(data, annealed)
            annealed['termination'] = outcome.termination
            export(folder/'annealing', annealed)
            write_json(folder/'annealing'/'temperature_history.json', {'levels': outcome.search.generation_history,
                       'improvements': outcome.search.progress, 'termination': outcome.termination})
            remaining = work_deadline-time.perf_counter()
            if remaining < 2:
                break
            # 各独立起点完成自己的精确阶段；不把全局最好编码混入该起点的结果。
            refined = refine_windows(data, outcome.search.best, {}, folder/'window', budget=min(args.cycle_solver_seconds, remaining),
                                      per_round=5, max_rounds=80, width=5, seed=seed,
                                      threads=args.threads, compact=True, reuse_env=True, on_round=trace.exact,
                                      exact_cache=exact_cache, cache_enabled=not args.no_range_cache,
                                      deadline=work_deadline)
            trace.record('gurobi', 'stage_end', code_from_result(refined, data.n))
            records.append({'variant': 'cycle', 'run': trace.run, 'seed': seed,
                            'initial': info['local_best'], 'heuristic': outcome.search.best_cost,
                            'before': outcome.search.best_cost, 'after': refined['objective'],
                            'initialization': info, 'annealing': outcome.termination,
                            'annealing_seconds': outcome.search.seconds, 'refinement': refined['refinement']})
            write_json(output/'summary.json', {'complete': False, 'case': 2, 'records': records,
                       'reference_objective': saved['objective'], 'best': trace.best_cost,
                       'elapsed_seconds': trace.elapsed()})
            print(json.dumps({'phase': 'cycle_end', 'cycle': cycle, 'global_best': trace.best_cost,
                              'elapsed_seconds': trace.elapsed()}), flush=True)
        focus = 0
        while time.perf_counter() < work_deadline-2:
            focus += 1
            trace.run = f'focus{focus:02d}'
            width = (5, 7, 9)[(focus-1) % 3]
            compact = focus % 2 == 1
            before = trace.best_cost
            trace.record('gurobi', 'stage_start', trace.best, width=width, compact=compact)
            refined = refine_windows(data, trace.best, {}, output/trace.run/'window',
                                      budget=min(args.focus_seconds, work_deadline-time.perf_counter()), per_round=8,
                                      max_rounds=100, width=width, seed=args.seed+10000+focus,
                                      threads=args.threads, compact=compact, reuse_env=True, on_round=trace.exact,
                                      exact_cache=exact_cache, cache_enabled=not args.no_range_cache,
                                      deadline=work_deadline)
            trace.record('gurobi', 'stage_end', code_from_result(refined, data.n))
            records.append({'variant': 'focus', 'run': trace.run, 'width': width, 'compact': compact,
                            'before': before, 'after': refined['objective'], 'refinement': refined['refinement']})
            write_json(output/'summary.json', {'complete': False, 'case': 2, 'records': records,
                       'reference_objective': saved['objective'], 'best': trace.best_cost,
                       'elapsed_seconds': trace.elapsed()})
        final = decode(data, trace.best)
        final['validation'] = validate_exact(data, final)
        final['run_info'] = {'scope': 'restricted', 'original_optimality_proven_by_this_run': False,
                             'global_improvements': len(trace.improvements), 'elapsed_seconds': trace.elapsed()}
        export(output/'final', final)
        trace.record('final', 'end', trace.best)
        write_json(output/'summary.json', {'complete': True, 'case': 2, 'records': records,
                   'reference_objective': saved['objective'], 'best': trace.best_cost,
                   'elapsed_seconds': trace.elapsed(), 'global_improvements': trace.improvements,
                   'cycles': cycle, 'focus_stages': focus,
                   'range_cache': exact_cache.summary() if exact_cache else {'enabled': False},
                   'includes_previous_reference_computation_time': False})
        print(json.dumps({'phase': 'complete', 'best': trace.best_cost, 'elapsed_seconds': trace.elapsed()}), flush=True)
    finally:
        trace.close()


if __name__ == '__main__':
    main()
