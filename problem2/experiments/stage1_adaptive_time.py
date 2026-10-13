"""一阶段受限求解：四组相同180秒追加预算，短跑后随机或解码试探选择追加。"""
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
from problem2.common.encoding import BatchEvaluator, Chromosome, code_from_result, decode, evaluate
from problem2.common.export import export, write_json
from problem2.common.paths import PROJECT_ROOT, snapshot_source
from problem2.common.restricted_session import RestrictedSession
from problem2.common.stable_constraints import StableConstraints
from problem2.common.validation import validate_exact
from problem2.experiments.stage1_free_jobs import CONFIG, SEEDS, audit, prepare, read
from problem2.stage1.windows import refine_windows
from problem2.stage2.joint_search import free_job_constraints

METHODS = ('interval', 'fixed15', 'adaptive_random', 'adaptive_scored')


def coordinate(code, job, field):
    if field == 'machines':
        for value in (0, 1):
            m = list(code.machines)
            m[job] = value
            yield Chromosome(code.a, code.b, tuple(m))
        return
    order = list(getattr(code, field))
    order.remove(job)
    for position in range(len(order)+1):
        q = tuple(order[:position]+[job]+order[position:])
        yield Chromosome(q if field == 'a' else code.a, q if field == 'b' else code.b, code.machines)


def probe(data, reference, jobs, scorer=None, width=4, deadline=None):
    """束搜索：每步保留四个完整编码，依次改变两个自由工件的A/B位置和机器。"""
    started = time.perf_counter()
    scorer = scorer or BatchEvaluator(data)
    restriction = free_job_constraints(reference, jobs)
    reference_cost = evaluate(data, reference)
    best, best_cost, count, alternatives = reference, reference_cost, 0, {}
    complete = True
    for job_order in (tuple(jobs), tuple(reversed(jobs))):
        beam = [reference]
        for job in job_order:
            for field in ('a', 'b', 'machines'):
                if deadline is not None and time.perf_counter() >= deadline:
                    complete = False
                    break
                candidates = list(dict.fromkeys(c for b in beam for c in coordinate(b, job, field)))
                values = scorer.evaluate(candidates)
                count += len(candidates)
                ranked = sorted(zip(values, candidates), key=lambda r: (r[0], r[1].a, r[1].b, r[1].machines))
                # 参考编码保留；其余名额允许暂时更差的完整编码，试探后续联合调整。
                beam = [reference]+[c for _, c in ranked if c != reference][:width-1]
                for value, candidate in ranked:
                    if candidate != reference:
                        alternatives[candidate] = value
                    if value < best_cost:
                        best, best_cost = candidate, value
            if not complete:
                break
        if not complete:
            break
    assert restriction.satisfies(best)
    assert evaluate(data, best) == best_cost
    rank_value = min(alternatives.values(), default=reference_cost)
    return best, {'jobs': list(jobs), 'reference_objective': reference_cost,
        'best_objective': best_cost, 'rank_value': rank_value,
        'near_count': sum(v <= reference_cost+50 for v in alternatives.values()),
        'evaluations': count, 'seconds': time.perf_counter()-started, 'complete': complete,
        'beam_width': width, 'all_candidates_complete': True}


def extend_index(entries, method, rng):
    eligible = [i for i, e in enumerate(entries) if not e['result']['proof']['optimal']]
    if not eligible:
        return None
    if method == 'adaptive_random':
        return rng.choice(eligible)
    if method != 'adaptive_scored':
        raise ValueError(method)
    # 下界和gap不作为改善概率；相同排名随机打破。
    return min(eligible, key=lambda i: (entries[i]['probe']['rank_value'],
        -entries[i]['probe']['near_count'], rng.random()))


def branch(root, seed, method, budget=180):
    folder = root/f'seed{seed}'/method
    folder.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    deadline = started+budget
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    initial = current = code_from_result(read(root/f'prefix_seed{seed}/annealing/result.json'), data.n)
    best = evaluate(data, current)
    records, improvements, probes, decisions = [], [], [], []
    def accept(code, source):
        nonlocal current, best
        value = evaluate(data, code)
        if value < best:
            current, best = code, value
            row = {'objective': best, 'source': source, 'elapsed_seconds': time.perf_counter()-started,
                   'code': code.as_dict()}
            improvements.append(row)
            export(folder/'best', decode(data, current))
            print(json.dumps({'event': 'improvement', 'seed': seed, 'method': method,
                              'objective': best, 'seconds': row['elapsed_seconds'], 'source': source}), flush=True)
            return True
        return False
    def progress():
        write_json(folder/'checkpoint.json', {'best': best, 'rounds': records,
            'improvements': improvements, 'probes': probes, 'decisions': decisions, 'complete': False})
    if method == 'interval':
        result = refine_windows(data, current, {}, folder/'window', budget=budget,
            per_round=5, max_rounds=200, width=5, seed=seed, threads=8, compact=True,
            reuse_env=True, cache_enabled=False, deadline=deadline,
            on_round=lambda code, row: accept(code, 'interval'))
        records = result['refinement']['records']
    else:
        import gurobipy as gp
        env = gp.Env(empty=True)
        env.setParam('OutputFlag', 0)
        env.start()
        rng, selection_rng = random.Random(seed+1000), random.Random(seed+2000)
        seen, pending, rounds = set(), [], 0
        scorer = BatchEvaluator(data) if method == 'adaptive_scored' else None
        try:
            while time.perf_counter() < deadline-.5 and rounds < 200:
                reference = current
                available = [p for p in itertools.combinations(range(data.n), 2) if (reference, p) not in seen]
                if not available:
                    break
                pair_count = 1 if method == 'fixed15' else min(4, len(available))
                pairs = rng.sample(available, pair_count)
                pending = []
                changed = False
                try:
                    for jobs in pairs:
                        if time.perf_counter() >= deadline-.5:
                            break
                        seen.add((reference, jobs))
                        rounds += 1
                        restriction = free_job_constraints(reference, jobs)
                        session = RestrictedSession(data, reference, restriction, folder/f'round{rounds:03d}', env)
                        entry = {'session': session, 'jobs': jobs, 'round': rounds}
                        pending.append(entry)
                        result = session.run(15 if method == 'fixed15' else 5, deadline)
                        entry['result'] = result
                        assert model_counts(restriction)['binary_variables'] == result['proof']['reduction']['binary_variables']
                        records.append({'round': rounds, 'jobs': list(jobs), 'phase': 'short' if method != 'fixed15' else 'fixed',
                            'before': best, 'after': min(best, result['objective']), 'proof': result['proof'],
                            'elapsed_seconds': time.perf_counter()-started})
                        changed = accept(code_from_result(result, data.n), 'gurobi_short' if method != 'fixed15' else 'gurobi_fixed')
                        progress()
                        if changed:
                            break
                    if changed or method == 'fixed15' or time.perf_counter() >= deadline-.5:
                        continue
                    if method == 'adaptive_scored':
                        for entry in pending:
                            if entry['result']['proof']['optimal']:
                                continue
                            candidate, details = probe(data, reference, entry['jobs'], scorer, deadline=deadline)
                            entry['probe'] = details
                            probes.append(details | {'round': entry['round'], 'elapsed_seconds': time.perf_counter()-started})
                            if accept(candidate, 'decoding_probe'):
                                changed = True
                                break
                        if changed or time.perf_counter() >= deadline-.5:
                            progress()
                            continue
                    index = extend_index(pending, method, selection_rng)
                    if index is None:
                        continue
                    entry = pending[index]
                    decisions.append({'rounds': [e['round'] for e in pending], 'selected_round': entry['round'],
                        'method': method, 'elapsed_seconds': time.perf_counter()-started,
                        'probe_scores': [e.get('probe') for e in pending], 'uses_bound_for_selection': False})
                    result = entry['session'].run(10, deadline)
                    records.append({'round': entry['round'], 'jobs': list(entry['jobs']), 'phase': 'extension',
                        'before': best, 'after': min(best, result['objective']), 'proof': result['proof'],
                        'elapsed_seconds': time.perf_counter()-started})
                    accept(code_from_result(result, data.n), 'gurobi_extension')
                    progress()
                finally:
                    # 参考解变化后丢弃待追加模型；不把旧固定条件用于新参考编码。
                    for entry in pending:
                        entry['session'].close()
                    pending = []
        finally:
            for entry in pending:
                entry['session'].close()
            env.dispose()
    final = decode(data, current)
    final['validation'] = validate_exact(data, final)
    export(folder/'final', final)
    summary = {'seed': seed, 'method': method, 'before': evaluate(data, initial), 'after': best,
        'budget_seconds': budget, 'additional_seconds': time.perf_counter()-started,
        'round_count': len({r['round'] for r in records}), 'optimize_calls': len(records),
        'rounds': records, 'probes': probes, 'decisions': decisions, 'improvements': improvements,
        'first_improvement_seconds': improvements[0]['elapsed_seconds'] if improvements else None,
        'start_code': initial.as_dict(), 'complete': True, 'original_optimality_proven': False}
    write_json(folder/'summary.json', summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('rounds','probes','decisions','improvements','start_code')}), flush=True)


def diagnostic(root):
    old = PROJECT_ROOT/'problem2/results/stage1_round_time/run01/seed23/guided/round002'
    raw = read(old/'restrictions.json')
    ref = as_code(raw['reference_code'])
    restriction = StableConstraints(ref, raw['selected_relations'])
    data = load_case(PROJECT_ROOT/'问题2数据.xlsx', 2)
    session = RestrictedSession(data, ref, restriction, root/'resume_diagnostic')
    try:
        session.run(5)
        if not session.result['proof']['optimal']:
            session.run(10)
        assert session.digest == read(old/'result.json')['proof']['model_sha256']
        log = (session.folder/'solver.log').read_text(encoding='utf-8')
        resumed_log = 'Continuing optimization' in log
        write_json(root/'diagnostic.json', {'phases': session.phases, 'after': session.result['objective'],
            'same_model_sha256': True, 'continuation_log_detected': resumed_log,
            'historical_reference_cost_excluded': True, 'used_for_search': False})
        if len(session.phases) == 2 and not resumed_log:
            raise AssertionError('日志未确认保留原搜索，不能继续正式实验')
    finally:
        session.close()


def worker(root, phase, seed=None, method=None, deadline=None):
    label = phase if seed is None else f'{phase}_{seed}_{method or "prefix"}'
    command = [sys.executable, '-u', '-B', '-m', 'problem2.experiments.stage1_adaptive_time',
        '--output', str(root), '--phase', phase]
    if seed is not None:
        command += ['--seed', str(seed)]
    if method:
        command += ['--method', method]
    remaining = deadline-time.perf_counter()
    if remaining < (190 if phase == 'branch' else 100):
        return False
    with (root/f'{label}.log').open('w', encoding='utf-8') as log:
        completed = subprocess.run(command, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT,
            timeout=min(240, remaining), env=os.environ | {'PYTHONIOENCODING':'utf-8'})
    if completed.returncode:
        raise RuntimeError(f'{label} failed; inspect log')
    return True


def orchestrate(root, global_seconds):
    root.mkdir(parents=True, exist_ok=False)
    started, deadline = time.perf_counter(), time.perf_counter()+global_seconds
    hashes = snapshot_source(root/'source')
    write_json(root/'config.json', {'case':2, 'seeds':SEEDS, 'methods':METHODS,
        'search':asdict(CONFIG), 'budget_seconds':180, 'short_seconds':5, 'extension_seconds':10,
        'batch_pairs':4, 'beam_width':4, 'threads':8, 'code_sha256':hashes,
        'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (PROJECT_ROOT/'问题2.pdf',PROJECT_ROOT/'问题2数据.xlsx')},
        'global_seconds_after_launch':global_seconds, 'default_algorithm_modified':False,
        'full_case2_model_allowed':False})
    worker(root, 'diagnostic', deadline=deadline)
    prefixes, rows = [], []
    for seed in SEEDS:
        if not worker(root,'prepare',seed,deadline=deadline):
            raise TimeoutError('没有足够预算完成准备')
        prefixes.append(read(root/f'prefix_seed{seed}/summary.json'))
    for i, seed in enumerate(SEEDS):
        order = METHODS[i:]+METHODS[:i]
        for method in order:
            print(f'start seed={seed} method={method}',flush=True)
            if not worker(root,'branch',seed,method,deadline):
                write_json(root/'partial_summary.json',{'complete':False,'prefixes':prefixes,'records':rows})
                return
            row = read(root/f'seed{seed}'/method/'summary.json')
            rows.append(row)
            write_json(root/'partial_summary.json',{'complete':False,'prefixes':prefixes,'records':rows})
            print(json.dumps({k:row[k] for k in ('seed','method','after','additional_seconds')}),flush=True)
    verification = audit(root,rows)
    write_json(root/'verification.json',verification)
    write_json(root/'summary.json',{'complete':True,'prefixes':prefixes,'records':rows,
        'wall_seconds':time.perf_counter()-started,'verification':verification,
        'original_optimality_proven':False})
    print(json.dumps({'complete':True,'verification':verification}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--phase',choices=('all','diagnostic','prepare','branch'),default='all')
    parser.add_argument('--seed',type=int,choices=SEEDS)
    parser.add_argument('--method',choices=METHODS)
    parser.add_argument('--global-seconds',type=float,default=2900)
    args=parser.parse_args()
    if args.phase in ('prepare','branch') and args.seed is None:
        parser.error('子进程需要种子')
    if args.phase=='branch' and args.method is None:
        parser.error('分支需要方法')
    root=args.output.resolve()
    if args.phase=='all': orchestrate(root,args.global_seconds)
    elif args.phase=='diagnostic': diagnostic(root)
    elif args.phase=='prepare': prepare(root,args.seed)
    else: branch(root,args.seed,args.method)


if __name__=='__main__': main()
