"""独立按记录、原始时长与机器顺序核验时间表，不调用调度计算函数。"""
from problem2.common.data import m62_duration
from problem2.experiments.schedule import check_solution


def validate_schedule(data, schedule):
    check_solution(schedule.solution, data.n)
    records = {(op.job, op.station): op for op in schedule.operations}
    if len(records) != data.n*10 or len(schedule.operations) != data.n*10:
        raise ValueError("存在重复或缺失工序")
    expected = {(j, k) for j in range(data.n) for k in range(1, 11)}
    if set(records) != expected:
        raise ValueError("工序编号不完整")
    queues = {str(k): schedule.solution.pi_a for k in range(1, 6)}
    queues.update({"6-1": schedule.solution.q1, "6-2": schedule.solution.q2})
    queues.update({str(k): schedule.pi_b for k in range(7, 11)})
    if sorted(schedule.pi_b) != list(range(data.n)):
        raise ValueError("后段排列不完整")
    for machine, queue in queues.items():
        k = 6 if machine.startswith("6-") else int(machine)
        previous = None
        previous_end = 0
        for j in queue:
            op = records[j, k]
            arrival = 0 if k == 1 else records[j, k-1].end
            duration = data.processing[j][k-1]
            if machine == "6-2":
                duration = m62_duration(duration)
            setup = 0 if previous is None else data.setup[previous][j]
            if op.machine != machine or op.predecessor != previous or op.arrival != arrival:
                raise ValueError("机器、前驱或到达时间错误")
            if op.processing != duration or op.end-op.start != duration:
                raise ValueError("加工时间错误")
            if op.setup_end-op.setup_start != setup or op.setup_end != op.start:
                raise ValueError("换模时间错误")
            if op.setup_start < max(previous_end, arrival):
                raise ValueError("机器占用冲突或提前换模")
            if op.setup_start != max(previous_end, arrival):
                raise ValueError("初版要求最早递推，但记录中存在额外等待")
            previous, previous_end = j, op.end
    rank = {j: i for i, j in enumerate(schedule.solution.tie_priority)}
    expected_b = tuple(sorted(range(data.n), key=lambda j: (records[j, 6].end, rank[j])))
    if schedule.pi_b != expected_b:
        raise ValueError("后段顺序与工位6完工时间或并列规则不一致")
    if min(records[j, 1].start for j in range(data.n)) != 0:
        raise ValueError("时间原点不是0")
    if schedule.makespan != max(records[j, 10].end for j in range(data.n)):
        raise ValueError("目标值与实际最终完成时间不一致")
    return {"valid": True, "operations_checked": data.n*10, "machines_checked": 11,
            "timing_rule": "earliest_feasible_queue_recurrence"}
