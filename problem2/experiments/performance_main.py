"""重复调用开销研究：回放相同范围，并从相同初始调度比较完整区间搜索。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
import argparse
import hashlib
import importlib.util
import json
import random
import time
from pathlib import Path
from problem2.common.data import load_case
from problem2.common.encoding import Chromosome, code_from_result, decode
from problem2.common.solver import export
from problem2.common.validation import validate_exact
from problem2.common.stable_constraints import StableConstraints
from problem2.experiments.stable_relations import optimize_once, write_json
from problem2.experiments.research_main import refine_windows


def snapshot(folder, arguments, project):
    folder.mkdir(parents=True)
    source = folder/'source'
    source.mkdir()
    hashes = {}
    for p in source_files(project):
        raw = p.read_bytes()
        copy_source_file(p, source, raw)
        hashes[source_relative(p)] = hashlib.sha256(raw).hexdigest()
    write_json(folder/'config.json', {'arguments': arguments, 'code_sha256': hashes,
               'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (project/'问题2.pdf', project/'问题2数据.xlsx')}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('replay', 'search'), required=True)
    parser.add_argument('--seeds', type=int, nargs='+', default=[11, 23, 37])
    parser.add_argument('--variants', nargs='+', choices=('baseline', 'environment', 'compact'),
                        default=['baseline', 'environment', 'compact'])
    parser.add_argument('--rounds', type=int, nargs='+', default=[1, 3, 8, 15, 28, 34])
    parser.add_argument('--max-rounds', type=int, default=36)
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--round-seconds', type=float, default=5)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--legacy-baseline', action='store_true', help='baseline使用本次研究前的相邻弧排除实现')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('输出目录已经存在')
    if min(args.seconds, args.round_seconds, args.max_rounds, args.threads, *args.rounds) <= 0:
        parser.error('预算、线程数和轮次必须为正')
    project = PROJECT_ROOT
    data = load_case(project/'问题2数据.xlsx', 2)
    from problem2.common import stable_constraints as constraints_module
    fast_arc_constants = constraints_module.arc_constants
    old_arc_constants = fast_arc_constants
    legacy_path = project/'.backups/20261010-call-performance/problem2/stable_constraints.py'
    if args.legacy_baseline:
        spec = importlib.util.spec_from_file_location('problem2._performance_legacy_constraints', legacy_path)
        module = importlib.util.module_from_spec(spec)
        # dataclass会查询所属模块；只为这次对照注册，不替换生产模块。
        import sys
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        old_arc_constants = module.arc_constants
    root = args.output.resolve()
    root.mkdir(parents=True)
    comparisons = []
    for seed in args.seeds:
        prior = project/f'problem2/results/research_v2/case2_seed{seed}_run01'
        reference = json.loads((prior/'reference/result.json').read_text(encoding='utf-8'))
        validate_exact(data, reference)
        initial = code_from_result(reference, data.n)
        # 交替试验次序，避免全部旧实现先跑、全部新实现后跑造成固定时间偏差。
        variants = list(args.variants)
        if seed == 23:
            variants.reverse()
        for variant in variants:
            folder = root/f'seed{seed}_{variant}'
            snapshot(folder, vars(args) | {'output': '.', 'variant': variant, 'seed': seed}, project)
            if args.legacy_baseline:
                raw = legacy_path.read_bytes()
                name = 'baseline_stable_constraints.py'
                (folder/'source'/name).write_bytes(raw)
                config_path = folder/'config.json'
                config = json.loads(config_path.read_text(encoding='utf-8'))
                config['code_sha256'][name] = hashlib.sha256(raw).hexdigest()
                write_json(config_path, config)
            constraints_module.arc_constants = old_arc_constants if variant == 'baseline' else fast_arc_constants
            export(folder/'reference', reference)
            compact, reuse = variant == 'compact', variant != 'baseline'
            started = time.perf_counter()
            if args.mode == 'search':
                result = refine_windows(data, initial, {}, folder/'window', args.seconds,
                                        args.round_seconds, args.max_rounds, 5, seed, args.threads,
                                        compact=compact, reuse_env=reuse)
                records = [{'variant': 'window', 'before': reference['objective'], 'after': result['objective'],
                            'exact_seconds': time.perf_counter()-started, 'refinement': result['refinement']}]
            else:
                import gurobipy as gp
                env = None
                records = []
                try:
                    if reuse:
                        env = gp.Env(empty=True)
                        env.setParam('OutputFlag', 0)
                        env.start()
                    # 每种实现读取同一轮的参考编码及直接限制，不共享改善后的编码。
                    for index in args.rounds:
                        raw = json.loads((prior/f'window/round{index:03d}/restrictions.json').read_text(encoding='utf-8'))
                        c = raw['reference_code']
                        code = Chromosome(tuple(c['a']), tuple(c['b']), tuple(c['machines']))
                        restrictions = StableConstraints(code, raw['selected_relations'])
                        begin = time.perf_counter()
                        result = optimize_once(data, code, restrictions, folder/f'round{index:03d}',
                                               args.round_seconds, args.threads, strengthen=True,
                                               compact=compact, solver_env=env)
                        records.append({'variant': variant, 'round': index, 'before': decode(data, code)['objective'],
                                        'after': result['objective'], 'exact_seconds': time.perf_counter()-begin,
                                        'proof': result['proof']})
                        print(json.dumps({'phase': 'replay', 'seed': seed, 'variant': variant, **records[-1]}), flush=True)
                finally:
                    if env is not None:
                        env.dispose()
            summary = {'complete': True, 'case': 2, 'mode': args.mode, 'variant': variant,
                       'seed': seed, 'preparation_seconds': 0, 'reference_objective': reference['objective'],
                       'total_seconds': time.perf_counter()-started, 'records': records,
                       'same_reference_and_selection_inputs': True}
            write_json(folder/'summary.json', summary)
            comparisons.append(summary)
            write_json(root/'comparison.json', {'complete': False, 'records': comparisons})
            print(json.dumps({'phase': 'complete_variant', 'seed': seed, 'variant': variant,
                              'seconds': summary['total_seconds'], 'after': records[-1]['after']}), flush=True)
            constraints_module.arc_constants = fast_arc_constants
    write_json(root/'comparison.json', {'complete': True, 'records': comparisons})


if __name__ == '__main__':
    main()
