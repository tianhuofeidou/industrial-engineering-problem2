"""一阶段对照：连续区间、按关键工序/退火档案选两个自由工件、随机选两个。"""
import argparse
from dataclasses import asdict
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from problem2.common.annealing_records import as_code, model_counts
from problem2.common.data import load_case
from problem2.common.encoding import code_from_result, decode, evaluate
from problem2.common.export import export, write_json
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.restrictions import select_free_jobs
from problem2.common.solver_utils import optimize_once
from problem2.common.stable_constraints import StableConstraints
from problem2.common.validation import validate_exact
from problem2.stage1.annealing import run_annealing
from problem2.stage1.config import ComparisonConfig
from problem2.stage1.construction import initialize
from problem2.stage1.neighborhoods import critical_weights
from problem2.stage1.windows import refine_windows
from problem2.stage2.joint_search import free_job_constraints

SEEDS = (11, 23, 37)
METHODS = ('interval', 'guided', 'random')
CONFIG = ComparisonConfig(constructions=8, sa_temperature_multiplier=2, sa_cooling=.97)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def choose_jobs(data, reference, archive, method, iteration, rng, seen):
    """只将档案用于挑选自由工件；其余固定值始终取同一参考编码。"""
    available = [pair for pair in itertools.combinations(range(data.n), 2)
                 if (reference, pair) not in seen]
    if not available:
        return None
    if method == 'random':
        jobs = rng.choice(available)
        details = {'policy': 'random'}
    else:
        _, disagreement = select_free_jobs(reference, archive, data.n)
        weights = critical_weights(data, reference)
        critical = [weights['A'][j]+weights['B'][j] for j in range(data.n)]
        rank_c = sorted(range(data.n), key=lambda j: (-critical[j], j))
        rank_d = sorted(range(data.n), key=lambda j: (-disagreement[j], j))
        policy = ('critical', 'archive', 'mixed')[iteration % 3]
        if policy == 'critical':
            pool, score = set(rank_c[:10]), critical
        elif policy == 'archive':
            pool, score = set(rank_d[:10]), disagreement
        else:
            pool = set(rank_c[:6]+rank_d[:6])
            mc, md = max(critical) or 1, max(disagreement) or 1
            score = [critical[j]/mc+disagreement[j]/md for j in range(data.n)]
        candidates = [p for p in available if set(p) <= pool]
        if candidates:
            jobs = max(candidates, key=lambda p: (sum(score[j] for j in p), rng.random()))
        else:
            jobs, policy = rng.choice(available), 'random_after_pool_exhausted'
        details = {'policy': policy, 'critical_scores': critical,
                   'disagreement_scores': disagreement, 'quality_archive_size': len(archive)}
    seen.add((reference, jobs))
    return jobs, details


def prepare(root, seed, total_deadline=None):
    folder = root/f'prefix_seed{seed}'
    folder.mkdir(exist_ok=False)
    started = time.perf_counter()
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    initial, initialization = initialize(data, seed, CONFIG, deadline=total_deadline)
    export(folder/'initial', decode(data, initial))
    write_json(folder/'initialization.json', initialization)
    def event(kind, code, row):
        if kind != 'temperature_level' or row['level'] % 20 == 0:
            write_json(folder/'progress.json', {'phase': 'annealing', **row})
    outcome = run_annealing(data, initial, seed, CONFIG, deadline=total_deadline, on_event=event)
    final = decode(data, outcome.search.best)
    final['validation'] = validate_exact(data, final)
    export(folder/'annealing', final)
    archive = [{'code': c.as_dict(), 'objective': evaluate(data, c)} for c in outcome.search.archive
               if evaluate(data, c) <= final['objective']*1.01]
    write_json(folder/'archive.json', archive)
    write_json(folder/'temperature_history.json', outcome.search.generation_history)
    summary = {'seed': seed, 'initial': evaluate(data, initial), 'annealing': final['objective'],
               'preparation_seconds': time.perf_counter()-started, 'initialization_seconds': initialization['seconds'],
               'annealing_seconds': outcome.search.seconds, 'termination': outcome.termination,
               'quality_archive_size': len(archive), 'archive_limit': CONFIG.archive_size,
               'uses_persistent_relation_tracker': False, 'complete': outcome.termination['reason'] == 'temperature_floor'}
    write_json(folder/'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def branch(root, seed, method, budget):
    folder = root/f'seed{seed}'/method
    folder.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    deadline = started+budget
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    current = code_from_result(read(root/f'prefix_seed{seed}/annealing/result.json'), data.n)
    initial = current
    initial_cost = best = evaluate(data, current)
    archive = [as_code(r['code']) for r in read(root/f'prefix_seed{seed}/archive.json')]
    records, improvements = [], []
    def event(kind, code, details=None):
        nonlocal current, best
        cost = evaluate(data, code)
        row = {'event': kind, 'elapsed_seconds': time.perf_counter()-started,
               'candidate': cost, **(details or {})}
        if cost < best:
            current, best = code, cost
            result = decode(data, code)
            result['validation'] = validate_exact(data, result)
            export(folder/'best', result)
            improvements.append(row | {'objective': cost, 'code': code.as_dict()})
        row['best'] = best
        write_json(folder/'progress.json', row)
        with (folder/'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')
    event('start', current)
    reason = 'round_limit'
    if method == 'interval':
        result = refine_windows(data, current, {}, folder/'window',
                budget=max(.1, deadline-time.perf_counter()), per_round=5, max_rounds=80,
                width=5, seed=seed, threads=8, compact=True, reuse_env=True,
                cache_enabled=False, deadline=deadline,
                on_round=lambda code, row: event('round', code, {'round': row['round'],
                    'status': row['proof']['status'], 'binaries': row['proof']['reduction']['binary_variables']}))
        event('end', code_from_result(result, data.n))
        records = result['refinement']['records']
        reason = 'time_budget' if time.perf_counter() >= deadline else 'round_limit_or_ranges_exhausted'
    else:
        import gurobipy as gp
        env = gp.Env(empty=True)
        env.setParam('OutputFlag', 0)
        env.start()
        seen, rng = set(), random.Random(seed+1000)
        try:
            for iteration in range(80):
                if time.perf_counter() >= deadline-.1:
                    reason = 'time_budget'
                    break
                choice = choose_jobs(data, current, archive, method, iteration, rng, seen)
                if choice is None:
                    reason = 'all_pairs_checked_for_current_code'
                    break
                jobs, details = choice
                restriction = free_job_constraints(current, jobs)
                counts = model_counts(restriction)
                before = best
                result = optimize_once(data, current, restriction, folder/f'round{iteration+1:03d}',
                        min(5, max(0, deadline-time.perf_counter())), 8, strengthen=True,
                        compact=True, solver_env=env, deadline=deadline)
                assert counts['binary_variables'] == result['proof']['reduction']['binary_variables']
                event('round', code_from_result(result, data.n), {'round': iteration+1,
                        'jobs': list(jobs), 'policy': details['policy'], 'status': result['proof']['status'],
                        'binaries': counts['binary_variables']})
                records.append({'round': iteration+1, 'before': before, 'after': best,
                                'jobs': list(jobs), 'selection': details, 'counts': counts,
                                'proof': result['proof'], 'elapsed_seconds': time.perf_counter()-started})
                write_json(folder/'checkpoint.json', {'records': records, 'best': best, 'complete': False})
        finally:
            env.dispose()
    final = decode(data, current)
    final['validation'] = validate_exact(data, final)
    export(folder/'final', final)
    reached = [r['elapsed_seconds'] for r in improvements if r['objective'] <= 10890]
    summary = {'seed': seed, 'method': method, 'before': initial_cost, 'after': best,
               'additional_seconds': time.perf_counter()-started, 'budget_seconds': budget,
               'first_improvement_seconds': improvements[0]['elapsed_seconds'] if improvements else None,
               'first_at_most_10890_seconds': min(reached) if reached else None,
               'round_count': len(records), 'rounds': records, 'improvements': improvements,
               'start_code': initial.as_dict(), 'termination': reason,
               'quality_archive_size': len(archive), 'complete': True,
               'scope': 'restricted', 'original_optimality_proven': False}
    write_json(folder/'summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in ('rounds', 'improvements', 'start_code')}, ensure_ascii=False), flush=True)


def run_worker(root, seed, phase, method, budget, global_deadline):
    name = f'prefix_seed{seed}' if phase == 'prepare' else f'seed{seed}_{method}'
    folder = root/f'prefix_seed{seed}' if phase == 'prepare' else root/f'seed{seed}'/method
    remaining = global_deadline-time.perf_counter()
    if remaining < (100 if phase == 'prepare' else budget+5):
        return None
    command = [sys.executable, '-u', '-B', '-m', 'problem2.experiments.stage1_free_jobs',
               '--output', str(root), '--phase', phase, '--seed', str(seed), '--budget', str(budget),
               '--global-seconds', str(remaining)]
    if method:
        command.extend(('--method', method))
    started = time.perf_counter()
    print(json.dumps({'event': 'start', 'run': name}), flush=True)
    with (root/f'{name}.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT,
                env=os.environ | {'PYTHONIOENCODING': 'utf-8'})
        previous = 0
        while process.poll() is None:
            elapsed = time.perf_counter()-started
            if elapsed-previous >= 45:
                try:
                    progress = read(folder/'progress.json') if (folder/'progress.json').is_file() else {}
                except json.JSONDecodeError:
                    progress = {}
                message = {'event': 'running', 'run': name, 'wall_seconds': elapsed,
                           **{k: progress[k] for k in ('phase', 'best', 'steps', 'round', 'jobs', 'binaries') if k in progress}}
                write_json(root/'status.json', message)
                print(json.dumps(message, ensure_ascii=False), flush=True)
                previous = elapsed
            if time.perf_counter() > global_deadline:
                process.terminate()
                process.wait(timeout=15)
                raise TimeoutError('全局预算结束；保留检查点，不报告完整对照')
            time.sleep(1)
    if process.returncode:
        raise RuntimeError(f'{name}: exit {process.returncode}; see {name}.log')
    result = read(folder/'summary.json')
    print(json.dumps({'event': 'finished', 'run': name,
                     **{k: result[k] for k in ('after', 'additional_seconds', 'annealing', 'quality_archive_size', 'round_count') if k in result}}, ensure_ascii=False), flush=True)
    return result


def audit(root, rows):
    # 单独核查新方法标签；不假定本目录具有ABC结果路径。
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    config = read(root/'config.json')
    for name, digest in config['source_sha256'].items():
        assert hashlib.sha256((PROJECT_ROOT/name).read_bytes()).hexdigest() == digest
    for name, digest in config['code_sha256'].items():
        assert hashlib.sha256((root/'source'/name).read_bytes()).hexdigest() == digest
        assert hashlib.sha256((PROJECT_ROOT/'problem2'/name).read_bytes()).hexdigest() == digest
    schedules = models = 0
    for path in root.rglob('result.json'):
        result = read(path)
        validate_exact(data, result)
        code = code_from_result(result, data.n)
        assert abs(evaluate(data, code)-result['objective']) <= 1e-4
        schedules += 1
        if (path.parent/'model.mps').exists():
            proof = result['proof']
            assert proof['scope'] == 'restricted' and not proof['original_optimality_proven_by_this_run']
            assert hashlib.sha256((path.parent/'model.mps').read_bytes()).hexdigest() == proof['model_sha256']
            raw = read(path.parent/'restrictions.json')
            restriction = StableConstraints(as_code(raw['reference_code']), raw['selected_relations'])
            assert restriction.satisfies(code) and restriction.satisfies(restriction.reference)
            assert proof['bound'] <= result['objective']+1e-4
            if proof['optimal']:
                assert abs(proof['bound']-result['objective']) <= 1e-4
            models += 1
    for seed in SEEDS:
        starts = [r['start_code'] for r in rows if r['seed'] == seed]
        assert all(c == starts[0] for c in starts)
    return {'schedules_validated': schedules, 'models_validated': models,
            'same_start_per_seed': True, 'hashes_verified': True, 'original_optimality_proven': False}


def orchestrate(root, budget, global_seconds):
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    started, deadline = time.perf_counter(), time.perf_counter()+global_seconds
    hashes = snapshot_source(root/'source')
    write_json(root/'config.json', {'case': 2, 'seeds': SEEDS, 'search': asdict(CONFIG),
               'methods': METHODS, 'budget_seconds': budget, 'global_seconds_after_launch': global_seconds,
               'free_jobs': 2, 'per_round_seconds': 5, 'max_rounds': 80, 'threads': 8,
               'quality_ratio': 1.01, 'code_sha256': hashes,
               'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (PROJECT_ROOT/'问题2.pdf', PROJECT_ROOT/'问题2数据.xlsx')},
               'uses_saved_reference': False, 'uses_persistent_relation_tracker': False,
               'original_optimality_proven': False})
    prefixes, rows = [], []
    for seed in SEEDS:
        prefix = run_worker(root, seed, 'prepare', None, budget, deadline)
        if prefix is None or not prefix['complete']:
            write_json(root/'partial_summary.json', {'complete': False, 'reason': 'global_budget', 'prefixes': prefixes})
            return
        prefixes.append(prefix)
    for seed, order in zip(SEEDS, (METHODS, METHODS[1:]+METHODS[:1], METHODS[2:]+METHODS[:2])):
        for method in order:
            result = run_worker(root, seed, 'branch', method, budget, deadline)
            if result is None:
                write_json(root/'partial_summary.json', {'complete': False, 'reason': 'global_budget',
                                                        'prefixes': prefixes, 'records': rows})
                return
            rows.append(result)
            write_json(root/'partial_summary.json', {'complete': False, 'prefixes': prefixes, 'records': rows})
    verification = audit(root, rows)
    write_json(root/'verification.json', verification)
    prepared = sum(p['preparation_seconds'] for p in prefixes)
    compact = [{k: r[k] for k in ('seed', 'method', 'before', 'after', 'additional_seconds',
                'first_improvement_seconds', 'first_at_most_10890_seconds', 'round_count', 'termination')}
               for r in sorted(rows, key=lambda r: (r['seed'], METHODS.index(r['method'])))]
    summary = {'complete': True, 'records': compact, 'prefixes': prefixes,
               'common_preparation_seconds': prepared, 'wall_seconds': time.perf_counter()-started,
               'verification': verification, 'original_optimality_proven': False}
    write_json(root/'summary.json', summary)
    write_json(root/'status.json', summary)
    lines = ['# 一阶段两个自由工件全位置重排对照', '',
             '三个种子均重新从原始Excel初始化并完成默认退火；同种子三方法从相同编码开始。档案直接取现有退火返回值，筛到最好值1%以内，不使用持续关系记录。',
             '每方法追加上限110秒，含读取、选工件、建模、求解、验证导出；每轮求解上限5秒、最多80轮、8线程。逐次时间不是平均值，也不宣称CPU工作量严格相同。',
             'interval为现有连续区间；guided轮换关键工序、档案分歧、两者归一合计；random均匀选两个未尝试工件。guided和random都固定未选33工件的机器和相对顺序，选中工件在A/B可分别任意插入。', '',
             '| 种子 | 方法 | 起点 | 最终 | 追加秒 | 首次改善秒 | 首次≤10890秒 | 轮数 |',
             '|---:|---|---:|---:|---:|---:|---:|---:|']
    for r in compact:
        fmt = lambda v: '-' if v is None else f'{v:.2f}'
        lines.append(f"|{r['seed']}|{r['method']}|{r['before']}|{r['after']}|{r['additional_seconds']:.2f}|{fmt(r['first_improvement_seconds'])}|{fmt(r['first_at_most_10890_seconds'])}|{r['round_count']}|")
    lines += ['', f'公共准备{prepared:.2f}秒；本次正式实验墙钟{summary["wall_seconds"]:.2f}秒，含核验，不含实现与测试。',
              f'独立核验{verification["schedules_validated"]}份完整调度、{verification["models_validated"]}个受限模型；参考保留、源码与输入哈希通过。',
              '每轮OPTIMAL、下界与gap只对当前固定范围有效，不能证明原题全局最优。每轮完整约束、选择评分、状态和改善编码见对应方法目录。']
    (root/'实验记录.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({'event': 'all_complete', **summary}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget', type=float, default=110)
    parser.add_argument('--global-seconds', type=float, default=1500)
    parser.add_argument('--phase', choices=('all', 'prepare', 'branch'), default='all')
    parser.add_argument('--seed', type=int, choices=SEEDS)
    parser.add_argument('--method', choices=METHODS)
    args = parser.parse_args()
    if min(args.budget, args.global_seconds) <= 0:
        parser.error('预算必须为正')
    root = args.output.resolve()
    if args.phase == 'all':
        orchestrate(root, args.budget, args.global_seconds)
    elif args.seed is None:
        parser.error('子进程需指定种子')
    elif args.phase == 'prepare':
        prepare(root, args.seed, time.perf_counter()+args.global_seconds)
    elif args.method is None:
        parser.error('分支需指定方法')
    else:
        branch(root, args.seed, args.method, args.budget)


if __name__ == '__main__':
    main()
