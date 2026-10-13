"""独立核查研究输出、完整调度、固定关系、模型哈希及源码快照。"""
from problem2.common.paths import PROJECT_ROOT, source_files, source_relative, copy_source_file
import argparse
import csv
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from problem2.common.data import load_case
from problem2.common.encoding import code_from_result, evaluate, Chromosome
from problem2.common.validation import validate_exact
from problem2.common.stable_constraints import StableConstraints
from problem2.experiments.stable_relations import write_json


def audit(root):
    project = PROJECT_ROOT
    data = {case: load_case(project/'问题2数据.xlsx', case) for case in (1, 2)}
    records = []
    for run in sorted(p for p in root.iterdir() if p.is_dir() and (p/'config.json').exists()):
        config = json.loads((run/'config.json').read_text(encoding='utf-8'))
        summary = json.loads((run/'summary.json').read_text(encoding='utf-8'))
        if not summary['complete']:
            raise AssertionError(f'试验尚未完成: {run.name}')
        for name, digest in config['source_sha256'].items():
            assert hashlib.sha256((project/name).read_bytes()).hexdigest() == digest
        for name, digest in config['code_sha256'].items():
            assert hashlib.sha256((run/'source'/name).read_bytes()).hexdigest() == digest
        schedules, models = 0, 0
        for p in run.rglob('result.json'):
            result = json.loads(p.read_text(encoding='utf-8'))
            d = data[result['case']]
            validate_exact(d, result)
            code = code_from_result(result, d.n)
            assert evaluate(d, code) <= result['objective']+1e-4
            with (p.parent/'schedule.csv').open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            assert len(rows) == len(result['operations']) == 10*d.n
            actual = {(int(r['job']), int(r['station'])): r for r in rows}
            for row in result['operations']:
                csv_row = actual[row['job'], row['station']]
                assert csv_row['machine'] == row['machine']
                assert csv_row['predecessor'] == ('' if row['predecessor'] is None else str(row['predecessor']))
                for key in ('arrival', 'setup_start', 'setup_finish', 'start', 'finish'):
                    assert math.isclose(float(csv_row[key]), row[key], abs_tol=1e-4)
            ET.parse(p.parent/'gantt.svg')
            schedules += 1
            if result.get('proof', {}).get('cache_hit'):
                proof = result['proof']
                evidence = Path(proof['cache_evidence_folder'])
                original = json.loads((evidence/'result.json').read_text(encoding='utf-8'))
                assert original['proof']['optimal'] and original['proof']['status'] == 2
                assert proof['scope'] == original['proof']['scope'] == 'restricted'
                assert not proof['original_optimality_proven_by_this_run']
                assert abs(original['proof']['bound']-result['objective']) <= 1e-4
                assert original['objective'] == result['objective']
                assert hashlib.sha256((evidence/'model.mps').read_bytes()).hexdigest() == proof['model_sha256']
                restriction = json.loads((p.parent/'restrictions.json').read_text(encoding='utf-8'))
                source_restriction = json.loads((evidence/'restrictions.json').read_text(encoding='utf-8'))
                assert restriction['reference_code'] == source_restriction['reference_code']
                fixed = lambda r: sorted((tuple(x['key']), x['value']) for x in r['selected_relations'])
                assert fixed(restriction) == fixed(source_restriction)
                c = restriction['reference_code']
                r = StableConstraints(Chromosome(tuple(c['a']), tuple(c['b']), tuple(c['machines'])),
                                      restriction['selected_relations'])
                assert r.satisfies(code) and r.satisfies(r.reference)
            if (p.parent/'model.mps').exists():
                proof = result['proof']
                assert hashlib.sha256((p.parent/'model.mps').read_bytes()).hexdigest() == proof['model_sha256']
                assert proof['bound'] <= result['objective']+1e-4
                assert proof['scope'] in ('full', 'restricted')
                assert proof['original_optimality_proven_by_this_run'] == (proof['scope'] == 'full' and proof['optimal'])
                if proof['optimal']:
                    assert abs(proof['bound']-proof['solver_objective']) <= 1e-4
                    assert abs(proof['solver_objective']-result['objective']) <= 1e-4
                counts = proof['reduction']
                assert counts['full_binary_variables'] == counts['binary_variables']+counts['substituted_binary_variables']
                restriction = json.loads((p.parent/'restrictions.json').read_text(encoding='utf-8'))
                if 'reference_code' in restriction:
                    c = restriction['reference_code']
                    r = StableConstraints(Chromosome(tuple(c['a']), tuple(c['b']), tuple(c['machines'])),
                                          restriction['selected_relations'])
                    assert r.as_dict() == restriction
                    assert r.satisfies(code) and r.satisfies(r.reference)
                models += 1
        for row in summary['records']:
            if row.get('variant') == 'repeated_annealing':
                assert row['additional_search_seconds'] >= row['target_seconds']
                assert row['after'] <= row['before']
            if row.get('refinement'):
                prev = row['before']
                for step in row['refinement']['records']:
                    assert step['before'] == prev and step['after'] <= prev
                    prev = step['after']
                assert prev == row['after']
        record = {'run': run.name, 'valid': True, 'schedules': schedules, 'models': models,
                  'input_hashes_verified': True, 'source_snapshots_verified': True}
        write_json(run/'verification.json', record)
        records.append(record)
        print(json.dumps(record, ensure_ascii=False))
    total = {'valid': True, 'runs': records, 'schedules': sum(r['schedules'] for r in records),
             'models': sum(r['models'] for r in records)}
    write_json(root/'verification.json', total)
    return total


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('problem2/results/research_v2'))
    args = parser.parse_args()
    print(json.dumps(audit(args.output), ensure_ascii=False))
