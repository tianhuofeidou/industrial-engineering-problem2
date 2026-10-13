"""导出CSV、JSON和独立SVG；原始Excel不回写。"""
import colorsys
import csv
import html
import json
import statistics
from dataclasses import asdict
from pathlib import Path


def write_csv(path, headers, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def job_color(j):
    r, g, b = colorsys.hsv_to_rgb((j*0.61803398875) % 1, 0.42, 0.88)
    return "#%02x%02x%02x" % (int(r*255), int(g*255), int(b*255))


def gantt_svg(data, schedule):
    width, left, right, top, row_height = 1600, 100, 30, 90, 62
    machines = ["1", "2", "3", "4", "5", "6-1", "6-2", "7", "8", "9", "10"]
    legend_rows = (data.n+13)//14
    height = top + len(machines)*row_height + 80 + legend_rows*26
    plot_width = width-left-right
    scale = plot_width / schedule.makespan
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<g font-family="Arial, Microsoft YaHei, sans-serif">',
             f'<text x="{left}" y="32" font-size="24">Case {data.case} — Cmax = {schedule.makespan} s</text>',
             f'<text x="{left}" y="58" font-size="15" fill="#475569">Earliest feasible schedule · colored: processing · gray: setup · hover for details</text>']
    for tick in range(11):
        value = schedule.makespan*tick/10
        x = left+value*scale
        parts.append(f'<line x1="{x:.2f}" y1="{top-10}" x2="{x:.2f}" y2="{top+11*row_height}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{x:.2f}" y="{top+11*row_height+25}" text-anchor="middle" font-size="13">{value:.0f}</text>')
    for i, machine in enumerate(machines):
        y = top+i*row_height
        parts.append(f'<text x="{left-16}" y="{y+29}" text-anchor="end" font-size="16">M{machine}</text>')
        parts.append(f'<line x1="{left}" x2="{width-right}" y1="{y+48}" y2="{y+48}" stroke="#cbd5e1"/>')
    for op in schedule.operations:
        y = top+machines.index(op.machine)*row_height+5
        j = data.jobs[op.job]
        tooltip = html.escape(f"{j}, M{op.machine}; arrival={op.arrival}; setup={op.setup_start}..{op.setup_end}; processing={op.start}..{op.end} s")
        if op.setup_end > op.setup_start:
            x, w = left+op.setup_start*scale, (op.setup_end-op.setup_start)*scale
            parts.append(f'<rect x="{x:.3f}" y="{y}" width="{w:.3f}" height="38" fill="#cbd5e1" stroke="white"><title>{tooltip}</title></rect>')
        x, w = left+op.start*scale, (op.end-op.start)*scale
        parts.append(f'<rect x="{x:.3f}" y="{y}" width="{w:.3f}" height="38" fill="{job_color(op.job)}" stroke="white"><title>{tooltip}</title></rect>')
        # 短工序不强行塞文字；颜色图例与悬停详情仍给出工件身份。
        if w >= len(j)*7+8:
            parts.append(f'<text x="{x+w/2:.3f}" y="{y+24}" text-anchor="middle" font-size="12" fill="#172033">{j}</text>')
    legend_y = top+len(machines)*row_height+65
    for j, name in enumerate(data.jobs):
        x, y = left+(j % 14)*104, legend_y+(j//14)*26
        parts.append(f'<rect x="{x}" y="{y-12}" width="18" height="16" fill="{job_color(j)}"/><text x="{x+24}" y="{y+1}" font-size="13">{name}</text>')
    parts.extend(["</g>", "</svg>"])
    return "\n".join(parts)


def convergence_svg(results):
    width, height, left, top, pw, ph = 1000, 470, 100, 60, 850, 320
    xmax = max(result.seconds for _, result in results)
    values = [v for _, result in results for _, v, _ in result.history]
    ymin, ymax = min(values), max(values)
    span = max(1, ymax-ymin)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<g font-family="Arial, Microsoft YaHei, sans-serif">',
             '<text x="100" y="30" font-size="23">Best makespan versus elapsed time</text>']
    for i in range(6):
        x, value = left+pw*i/5, xmax*i/5
        parts.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{top+ph}" stroke="#e2e8f0"/><text x="{x}" y="{top+ph+25}" text-anchor="middle" font-size="13">{value:.1f}</text>')
        y, value = top+ph*i/5, ymax-span*i/5
        parts.append(f'<line x1="{left}" y1="{y}" x2="{left+pw}" y2="{y}" stroke="#e2e8f0"/><text x="{left-12}" y="{y+5}" text-anchor="end" font-size="13">{value:.0f}</text>')
    for index, (seed, result) in enumerate(results):
        points = []
        previous = result.history[0][1]
        for elapsed, cost, _ in result.history:
            x = left+pw*elapsed/max(xmax, 0.001)
            points.append(f"{x:.2f},{top+ph*(ymax-previous)/span:.2f}")
            points.append(f"{x:.2f},{top+ph*(ymax-cost)/span:.2f}")
            previous = cost
        color = job_color(index)
        parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2"/>')
        parts.append(f'<text x="{left+index*160}" y="{top+ph+72}" fill="{color}" font-size="14">seed {seed}: {result.best_cost}</text>')
    parts.extend([f'<text x="{left+pw/2}" y="{top+ph+49}" text-anchor="middle" font-size="15">Elapsed time (s)</text>', "</g></svg>"])
    return "\n".join(parts)


def export_case(directory, data, schedule, results, config, validation):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    names = lambda order: [data.jobs[j] for j in order]
    records = {(op.job, op.station): op for op in schedule.operations}
    write_csv(directory / "schedule.csv",
              ["job", "station", "machine", "predecessor", "arrival_s", "setup_start_s",
               "setup_end_s", "processing_start_s", "processing_end_s", "processing_duration_s"],
              [(data.jobs[o.job], o.station, o.machine, "" if o.predecessor is None else data.jobs[o.predecessor],
                o.arrival, o.setup_start, o.setup_end, o.start, o.end, o.processing)
               for o in sorted(schedule.operations, key=lambda o: (o.job, o.station))])
    write_csv(directory / "start_times.csv", ["job"]+[f"M{k}_start_s" for k in range(1, 11)],
              [(data.jobs[j],)+tuple(records[j, k].start for k in range(1, 11)) for j in range(data.n)])
    write_csv(directory / "station6.csv",
              ["machine", "position", "job", "arrival_s", "setup_start_s", "setup_end_s", "start_s", "end_s"],
              [(m, pos+1, data.jobs[j], records[j, 6].arrival, records[j, 6].setup_start,
                records[j, 6].setup_end, records[j, 6].start, records[j, 6].end)
               for m, q in [("6-1", schedule.solution.q1), ("6-2", schedule.solution.q2)] for pos, j in enumerate(q)])
    write_csv(directory / "runs.csv",
              ["seed", "initial_cmax_s", "local_cmax_s", "best_cmax_s", "elapsed_s", "evaluations", "iterations", "restarts"],
              [(seed, r.initial_cost, r.local_cost, r.best_cost, round(r.seconds, 4), r.evaluations, r.iterations, r.restarts)
               for seed, r in results])
    write_csv(directory / "history.csv", ["seed", "elapsed_s", "best_cmax_s", "stage"],
              [(seed, round(t, 4), value, stage) for seed, r in results for t, value, stage in r.history])
    best_seed = min(results, key=lambda item: item[1].best_cost)[0]
    costs = [r.best_cost for _, r in results]
    summary = {"case": data.case, "jobs": data.n, "unit": "seconds", "status": "heuristic_feasible",
               "optimality_proven": False, "timing_rule": "earliest_feasible_at_all_stations",
               "best_seed": best_seed, "makespan": schedule.makespan,
               "pi_A": names(schedule.solution.pi_a), "Q1": names(schedule.solution.q1),
               "Q2": names(schedule.solution.q2), "pi_B": names(schedule.pi_b),
               "tie_priority": names(schedule.solution.tie_priority), "config": asdict(config),
               "runs": len(results), "mean_best": statistics.mean(costs),
               "std_best_population": statistics.pstdev(costs), "worst_best": max(costs),
               "validation": validation,
               "comparison_note": "initial/local/best为同一次搜索的阶段结果，不是相同时间预算的独立算法对照。"}
    write_json(directory / "summary.json", summary)
    (directory / "gantt.svg").write_text(gantt_svg(data, schedule), encoding="utf-8")
    (directory / "convergence.svg").write_text(convergence_svg(results), encoding="utf-8")
    return summary

def export(folder, result):
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    with (folder/'schedule.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result['operations'][0]))
        writer.writeheader()
        writer.writerows(sorted(result['operations'], key=lambda r: (r['job'], r['station'])))
    machines = ['1', '2', '3', '4', '5', '6-1', '6-2', '7', '8', '9', '10']
    colors = ['#2563eb', '#ea580c', '#16a34a', '#dc2626', '#9333ea', '#0891b2', '#ca8a04']
    job_count = len(result['queues']['A'])
    # 原来的7色保留；大算例按工件编号追加颜色，导出不改变调度。
    for j in range(len(colors), job_count):
        rgb = colorsys.hsv_to_rgb((j*0.61803398875) % 1, 0.70, 0.78)
        colors.append('#' + ''.join(f'{round(c*255):02x}' for c in rgb))
    case = result.get('case', 1 if job_count == 7 else 2 if job_count == 35 else '?')
    scale = 1100/result['objective']
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1260" height="560" viewBox="0 0 1260 560">',
           '<rect width="1260" height="560" fill="white"/>',
           f'<text x="20" y="28" font-size="19">Case {case} / Cmax = {result["objective"]:.6f} s</text>']
    for idx, machine in enumerate(machines):
        y = 60+idx*38
        svg.append(f'<text x="15" y="{y+20}" font-size="14">M{machine}</text>')
        for r in result['operations']:
            if r['machine'] != machine:
                continue
            for left, right, fill in [(r['setup_start'], r['start'], '#94a3b8'),
                                      (r['start'], r['finish'], colors[r['job']])]:
                svg.append(f'<rect x="{100+left*scale}" y="{y}" width="{max(0,right-left)*scale}" height="27" fill="{fill}"><title>{r["job_name"]}: {left:.4f} - {right:.4f} s</title></rect>')
            if (r['finish']-r['start'])*scale > 22:
                svg.append(f'<text x="{102+r["start"]*scale}" y="{y+18}" fill="white" font-size="11">{r["job_name"]}</text>')
    for t in range(0, int(result['objective'])+1, 500):
        svg.append(f'<text x="{100+t*scale}" y="500" font-size="12">{t}</text>')
    svg.append(f'<text x="100" y="535" font-size="14">Time (s); gray: setup; colors: J1-J{job_count}</text></svg>')
    (folder/'gantt.svg').write_text('\n'.join(svg), encoding='utf-8')

