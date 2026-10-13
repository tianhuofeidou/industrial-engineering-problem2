"""独立核查一般模型的调度；允许等待，不调用求解器或解码函数。"""
from math import isfinite
from problem2.common.data import m62_duration


def validate_exact(data, result, tolerance=1e-4):
    n = data.n
    rows = result['operations']
    assert len(rows) == 10*n, '工序数不完整'
    records = {(r['job'], r['station']): r for r in rows}
    assert len(records) == 10*n, '重复工序'
    queues = result['queues']
    assert sorted(queues['A']) == list(range(n))
    assert sorted(queues['B']) == list(range(n))
    assert sorted(queues['6-1'] + queues['6-2']) == list(range(n))
    for key, stages in [('A', range(1, 6)), ('B', range(7, 11)),
                        ('6-1', [6]), ('6-2', [6])]:
        for k in stages:
            previous = None
            for j in queues[key]:
                r = records[j, k]
                assert r['predecessor'] == previous, '相邻前驱记录错误'
                assert r['machine'] == (key if k == 6 else str(k))
                assert all(isfinite(r[t]) for t in ('start', 'finish', 'setup_start', 'setup_finish', 'arrival'))
                arrival = 0 if k == 1 else records[j, k-1]['finish']
                setup = 0 if previous is None else data.setup[previous][j]
                p = data.processing[j][k-1]
                if key == '6-2':
                    p = m62_duration(p)
                assert abs(r['arrival']-arrival) <= tolerance, '到达时间错误'
                assert abs(r['finish']-r['start']-p) <= tolerance, '加工时长错误'
                assert abs(r['setup_finish']-r['setup_start']-setup) <= tolerance, '换模时长错误'
                assert abs(r['setup_finish']-r['start']) <= tolerance
                assert r['setup_start']+tolerance >= arrival, '提前换模'
                assert r['start'] >= -tolerance
                if previous is not None:
                    assert r['setup_start']+tolerance >= records[previous, k]['finish'], '机器冲突'
                previous = j
    for i, j in zip(queues['B'], queues['B'][1:]):
        assert records[i, 6]['finish'] <= records[j, 6]['finish']+tolerance, '后段顺序与工位6完工顺序不同'
    assert abs(min(records[j, 1]['start'] for j in range(n))) <= tolerance
    makespan = max(records[j, 10]['finish'] for j in range(n))
    assert abs(makespan-result['objective']) <= tolerance, '目标值不符'
    return {'valid': True, 'operations': len(rows), 'tolerance': tolerance,
            'makespan': makespan, 'allows_waiting': True}
