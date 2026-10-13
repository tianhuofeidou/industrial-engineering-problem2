"""从已确定的加工、先后、相邻关系推导时间界，不规定额外的开工时刻。"""
from collections import deque
from problem2.common.data import m62_duration


def time_bounds(data, horizon, machines, orders, arcs):
    # 每条边 u -> v, d 表示 t[v] >= t[u] + d；只加入必然成立的边。
    n = data.n
    total = n*20+1
    end = total-1
    graph = [dict() for _ in range(total)]
    indegree = [0]*total

    def node(j, k, completion=False):
        return 20*j+2*k+int(completion)

    def edge(u, v, delta):
        if v not in graph[u]:
            indegree[v] += 1
        graph[u][v] = max(delta, graph[u].get(v, delta))

    for j in range(n):
        for k in range(10):
            p = data.processing[j][k]
            if k == 5 and machines.get(j) == 1:
                p = m62_duration(p)
            edge(node(j, k), node(j, k, True), p)
            if k:
                edge(node(j, k-1, True), node(j, k), 0)
        edge(node(j, 9, True), end, 0)
    for (q, i, j), value in orders.items():
        before, after = (i, j) if value else (j, i)
        for k in (range(5) if q == 'A' else range(6, 10)):
            edge(node(before, k, True), node(after, k), 0)
        if q == 'B':
            edge(node(before, 5, True), node(after, 5, True), 0)
    for q, i, j in arcs:
        if i < 0 or j == n:
            continue
        setup = data.setup[i][j]
        stages = range(5) if q == 'A' else range(6, 10) if q == 'B' else [5]
        for k in stages:
            edge(node(i, k, True), node(j, k), setup)
            if k:
                # 必须等待后件到达，换模不能提前进行。
                edge(node(j, k-1, True), node(j, k), setup)

    queue = deque(i for i, degree in enumerate(indegree) if degree == 0)
    order = []
    lower = [0]*total
    while queue:
        u = queue.popleft()
        order.append(u)
        for v, delta in graph[u].items():
            lower[v] = max(lower[v], lower[u]+delta)
            indegree[v] -= 1
            if not indegree[v]:
                queue.append(v)
    if len(order) != total:
        raise ValueError('确定的时间先后关系形成循环')
    upper = [horizon]*total
    for u in reversed(order):
        for v, delta in graph[u].items():
            upper[u] = min(upper[u], upper[v]-delta)
    if any(a > b for a, b in zip(lower, upper)):
        raise ValueError('固定关系的时间界排除了参考上界')
    ls = {(j, k): lower[node(j, k)] for j in range(n) for k in range(10)}
    lc = {(j, k): lower[node(j, k, True)] for j in range(n) for k in range(10)}
    us = {(j, k): upper[node(j, k)] for j in range(n) for k in range(10)}
    uc = {(j, k): upper[node(j, k, True)] for j in range(n) for k in range(10)}
    return ls, lc, us, uc, lower[end]
