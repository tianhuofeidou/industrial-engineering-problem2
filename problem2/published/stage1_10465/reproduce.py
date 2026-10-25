"""复现10465所用的一阶段配置；结果受机器、时限及求解器影响。"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def parameters(configuration):
    from problem2.stage1.config import ComparisonConfig
    moves, cooling = (2000, .998) if configuration == 'A' else (1000, .9989995966664914)
    return ComparisonConfig(constructions=8, sa_moves=moves, sa_cooling=cooling,
                            sa_temperature_multiplier=.5, sa_ratio=.0001)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration', choices=('A', 'B'), default='A')
    parser.add_argument('--seed', type=int, default=2026102513)
    parser.add_argument('--seconds', type=float, default=2400)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.seconds <= 3:
        parser.error('--seconds须大于3秒，含末尾3秒导出预留')
    if os.name != 'nt':
        parser.error('本复现入口使用Windows物理核绑定；其他系统可参照README的通用命令')
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[key] = '1'
    spec = importlib.util.spec_from_file_location('stage1_release_resources', Path(__file__).with_name('resources.py'))
    resources = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(resources)
    resource_config = resources.select()
    actual_resources = resources.apply(resource_config)
    from problem2.common.data import load_case
    from problem2.common.export import write_json
    from problem2.stage1 import main as entry
    started = time.perf_counter()
    data = load_case(ROOT/'问题2数据.xlsx', 2)
    original = entry.refine_windows
    def capped(*args, **kwargs):
        return original(*args, **(kwargs | {'max_width': 9}))
    entry.refine_windows = capped
    try:
        result = entry.run(data, args.output, seed=args.seed, seconds=args.seconds-3,
            annealing_seconds=args.seconds-3, solver_seconds=args.seconds-3,
            per_round=30, max_rounds=100000, width=5, threads=2,
            config=parameters(args.configuration), batch_descent=True, range_cache=False, started=started)
    finally:
        entry.refine_windows = original
    write_json(args.output.resolve()/'reproduction.json', {
        'configuration': args.configuration, 'seed': args.seed, 'nominal_seconds': args.seconds,
        'export_reserve_seconds': 3, 'resources': actual_resources,
        'complete_run_seconds': time.perf_counter()-started, 'scope': 'restricted',
        'exact_objective_reproduction_guaranteed': False})
    print(json.dumps({'objective': result['objective'], 'scope': 'restricted'}))


if __name__ == '__main__':
    main()
