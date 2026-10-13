"""使用现有ReportLab标准图表与PDFium渲染高温试跑的静态曲线。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from reportlab.graphics.shapes import Drawing, String, Circle, Line
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics import renderSVG, renderPDF
from reportlab.lib import colors
import pypdfium2 as pdfium


PALETTE = ['#2563eb', '#e67e22', '#0f766e', '#7c3aed']


def chart(folder, name, title, datasets, legends, x_max, y_min, y_max, y_label, notes,
          markers=None, x_label='Elapsed task time (minutes, including setup)'):
    drawing = Drawing(1000, 450)
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 95, 80, 850, 300
    plot.data = datasets
    plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = 0, x_max
    plot.xValueAxis.valueSteps = list(range(0, math.ceil(x_max)+1, 5))
    plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = y_min, y_max
    plot.yValueAxis.visibleGrid = True
    plot.yValueAxis.gridStrokeColor = colors.HexColor('#e2e8f0')
    plot.xValueAxis.labels.fontSize = plot.yValueAxis.labels.fontSize = 10
    for i in range(len(datasets)):
        plot.lines[i].strokeColor = colors.HexColor(PALETTE[i % len(PALETTE)])
        plot.lines[i].strokeWidth = 1.8
    drawing.add(plot)
    for x, y, phase in markers or []:
        px, py = plot.x+x/x_max*plot.width, plot.y+(y-y_min)/(y_max-y_min)*plot.height
        color = '#e67e22' if phase == 'annealing' else '#0f766e' if phase == 'gurobi' else '#7c3aed'
        drawing.add(Circle(px, py, 3.5, fillColor=colors.HexColor(color), strokeColor=colors.white, strokeWidth=0.7))
    drawing.add(String(95, 415, title, fontName='Helvetica-Bold', fontSize=18))
    drawing.add(String(520, 35, x_label, textAnchor='middle', fontSize=11))
    drawing.add(String(95, 391, y_label, fontSize=11))
    for i, label in enumerate(legends):
        x = 95+i*250
        drawing.add(Line(x, 55, x+22, 55, strokeColor=colors.HexColor(PALETTE[i % len(PALETTE)]), strokeWidth=2))
        drawing.add(String(x+28, 51, label, fontSize=10))
    drawing.add(String(95, 12, notes, fontSize=9, fillColor=colors.HexColor('#475569')))
    renderSVG.drawToFile(drawing, str(folder/f'{name}.svg'))
    pdf_bytes = renderPDF.drawToString(drawing)
    (folder/f'{name}.pdf').write_bytes(pdf_bytes)
    pdf = pdfium.PdfDocument(pdf_bytes)
    page = pdf[0]
    bitmap = page.render(scale=1.5)
    bitmap.to_pil().save(folder/f'{name}.png')
    bitmap.close()
    page.close()
    pdf.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    folder = args.output
    rows = [json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    if not rows:
        raise ValueError('尚无过程记录')
    end = rows[-1]['elapsed_seconds']/60
    improvements = [r for r in rows if r['global_improvement']]
    first = rows[0]['global_best']
    step, previous = [(0, first)], first
    for row in improvements:
        t = row['elapsed_seconds']/60
        step.extend([(t, previous), (t, row['global_best'])])
        previous = row['global_best']
    step.append((end, previous))
    margin = max(10, (first-previous)*0.15)
    markers = [(r['elapsed_seconds']/60, r['global_best'], r['phase']) for r in improvements]
    legend = ['Global best', 'SA improvement', 'Gurobi improvement']
    if any(r['phase']=='initialization' for r in improvements):
        legend.append('Initialization improvement')
    chart(folder, 'best_curve', 'Case 2: best feasible makespan', [step], legend,
          max(5, end), previous-margin, first+margin, 'Makespan (seconds; lower is better)',
          f'Initial {first} was computed before this task. Current best {previous}. No global optimality proof.', markers)
    setup = next((r['elapsed_seconds'] for r in rows if r['phase']=='initialization' and r['event']=='start'), 0)/60
    search_step = [(max(0, t-setup), value) for t, value in step]
    search_markers = [(max(0, t-setup), value, phase) for t, value, phase in markers]
    chart(folder, 'best_curve_search', 'Case 2: improvement during computation', [search_step], legend,
          max(5, end-setup), previous-margin, first+margin, 'Makespan (seconds; lower is better)',
          f'Setup {setup:.2f} minutes excluded. Previous schedule {first} retained. Current best {previous}.',
          search_markers, x_label='Elapsed computation time (minutes)')
    levels = [r for r in rows if r['event']=='temperature_level']
    if levels:
        # 每个退火起点单独一条线，避免用线把两个独立运行的当前解连接起来。
        runs = list(dict.fromkeys(r['run'] for r in levels))
        current = [[(r['elapsed_seconds']/60, r['current']) for r in levels if r['run']==run] for run in runs]
        all_values = [v for group in current for _, v in group]
        chart(folder, 'annealing_current', 'Case 2: current state at each temperature level', current,
              [], max(5, end), min(all_values)*0.97, max(all_values)*1.03,
              'Current makespan (seconds)',
              'Each colored segment is one annealing run. Worse states can be accepted; the global best is retained.')
        temperatures = [[(r['elapsed_seconds']/60, math.log10(r['temperature']))
                         for r in levels if r['run']==run] for run in runs]
        values = [v for group in temperatures for _, v in group]
        chart(folder, 'temperature', 'Case 2: simulated annealing cooling history', temperatures,
              [], max(5, end), min(values)-0.1, max(values)+0.1, 'log10(temperature)',
              'Initial temperature multiplier 2; cooling factor 0.97; 1000 moves per temperature level.')
    metadata = {'events': len(rows), 'current_best': previous, 'task_seconds': rows[-1]['elapsed_seconds'],
                'plotter': 'ReportLab LinePlot / PDFium', 'plot_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'setup_seconds': setup*60, 'search_seconds': max(0, (end-setup)*60),
                'charts': ['best_curve', 'best_curve_search', 'annealing_current', 'temperature']}
    (folder/'chart_metadata.json').write_bytes(json.dumps(metadata, ensure_ascii=False, indent=2).encode('utf-8'))
    print(json.dumps(metadata))


if __name__ == '__main__':
    main()
