"""命令行入口：从项目根目录执行 python -m problem2.experiments.legacy_main。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
import argparse
import json
from pathlib import Path
from problem2.common.data import load_case
from problem2.common.export import export_case, write_json
from problem2.experiments.schedule import Evaluator
from problem2.experiments.search import SearchConfig, search
from problem2.experiments.validate import validate_schedule


def main():
    root = PROJECT_ROOT
    parser = argparse.ArgumentParser(description="题目2纯Python启发式调度")
    parser.add_argument("--data", type=Path, default=root / "问题2数据.xlsx")
    parser.add_argument("--case", choices=["1", "2", "all"], default="all")
    parser.add_argument("--seconds", type=float, default=10, help="每个种子的搜索时间预算，含初始化")
    parser.add_argument("--seeds", type=int, nargs="+", default=[11, 23, 37])
    parser.add_argument("--neighbors", type=int, default=40)
    parser.add_argument("--destroy", type=int, default=3)
    parser.add_argument("--restart-after", type=int, default=35)
    parser.add_argument("--output", type=Path, default=root / "problem2" / "results" / "first_version")
    args = parser.parse_args()
    config = SearchConfig(args.seconds, args.neighbors, args.destroy, args.restart_after)
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("种子不得重复")
    cases = (1, 2) if args.case == "all" else (int(args.case),)
    summaries = []
    for case in cases:
        data = load_case(args.data, case)
        results = []
        for seed in args.seeds:
            evaluator = Evaluator(data)
            result = search(evaluator, seed, config)
            # 每次运行都验证最终方案，同时验证两个阶段的方案。
            for solution in (result.initial_solution, result.local_solution, result.solution):
                validate_schedule(data, evaluator.schedule(solution))
            results.append((seed, result))
            print(json.dumps({"case": case, "seed": seed, "initial": result.initial_cost,
                              "local": result.local_cost, "best": result.best_cost,
                              "seconds": round(result.seconds, 3), "valid": True}, ensure_ascii=False), flush=True)
        best = min(results, key=lambda item: item[1].best_cost)[1]
        schedule = Evaluator(data).schedule(best.solution)
        validation = validate_schedule(data, schedule)
        summary = export_case(args.output / f"case{case}", data, schedule, results, config, validation)
        summaries.append(summary)
    write_json(args.output / "summary.json", summaries)
    print("完成：两组数据的输出与验证均已保存。" if len(cases) == 2 else "完成：输出与验证已保存。", flush=True)


if __name__ == "__main__":
    main()
