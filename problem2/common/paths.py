"""统一原始输入定位与按新目录结构保存源码快照。"""
import hashlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / 'problem2'

def source_files(project=PROJECT_ROOT):
    package = Path(project) / 'problem2'
    files = list(package.glob('*.py'))
    for name in ('common', 'stage1', 'stage2', 'tests', 'experiments'):
        files.extend((package/name).rglob('*.py'))
    return sorted(files)

def source_relative(path):
    return Path(path).relative_to(PACKAGE_ROOT).as_posix()

def copy_source_file(path, destination, raw=None):
    target = Path(destination) / source_relative(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(Path(path).read_bytes() if raw is None else raw)

def snapshot_source(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for path in source_files():
        raw = path.read_bytes()
        copy_source_file(path, destination, raw)
        hashes[source_relative(path)] = hashlib.sha256(raw).hexdigest()
    return hashes
