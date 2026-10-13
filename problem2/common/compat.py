"""历史模块名转发；实现仅保留在新目录，不复制算法。"""
import importlib
import importlib.abc
import importlib.util
import sys

ALIASES = {'problem2.data': 'problem2.common.data', 'problem2.encoding': 'problem2.common.encoding', 'problem2.local_search': 'problem2.common.local_search', 'problem2.exact_cache': 'problem2.common.exact_cache', 'problem2.exact_validation': 'problem2.common.validation', 'problem2.exact_case1': 'problem2.common.solver', 'problem2.export': 'problem2.common.export', 'problem2.relation_tracking': 'problem2.common.relation_tracking', 'problem2.stable_constraints': 'problem2.common.stable_constraints', 'problem2.restrictions': 'problem2.common.restrictions', 'problem2.time_bounds': 'problem2.common.time_bounds', 'problem2.joint_search': 'problem2.stage2.joint_search', 'problem2.joint_main': 'problem2.stage2.main', 'problem2.multistart_main': 'problem2.stage2.multistart', 'problem2.neighborhoods': 'problem2.stage1.neighborhoods', 'problem2.long_budget': 'problem2.stage1.multistart_budget', 'problem2.main': 'problem2.experiments.legacy_main', 'problem2.stable_main': 'problem2.experiments.stable_relations', 'problem2.audit_research': 'problem2.experiments.audit_research', 'problem2.compare_case1': 'problem2.experiments.compare_case1', 'problem2.four_methods': 'problem2.experiments.four_methods', 'problem2.genetic': 'problem2.experiments.genetic', 'problem2.genetic_main': 'problem2.experiments.genetic_main', 'problem2.hybrid': 'problem2.experiments.hybrid', 'problem2.initialization': 'problem2.experiments.initialization', 'problem2.long_budget_plot': 'problem2.experiments.long_budget_plot', 'problem2.long_budget_report': 'problem2.experiments.long_budget_report', 'problem2.performance_main': 'problem2.experiments.performance_main', 'problem2.research_main': 'problem2.experiments.research_main', 'problem2.schedule': 'problem2.experiments.schedule', 'problem2.search': 'problem2.experiments.search', 'problem2.tests': 'problem2.tests.test_legacy', 'problem2.tests_batch': 'problem2.tests.test_batch', 'problem2.tests_exact_case1': 'problem2.tests.test_exact_case1', 'problem2.tests_four_methods': 'problem2.tests.test_four_methods', 'problem2.tests_genetic': 'problem2.tests.test_genetic', 'problem2.tests_improvements': 'problem2.tests.test_improvements', 'problem2.tests_joint': 'problem2.tests.test_joint', 'problem2.tests_multistart': 'problem2.tests.test_multistart', 'problem2.tests_research': 'problem2.tests.test_research', 'problem2.tests_stable': 'problem2.tests.test_stable', 'problem2.validate': 'problem2.experiments.validate'}

# tests现在是实际包；旧的python -m problem2.tests由tests/__main__.py转发。
ALIASES.pop('problem2.tests', None)

class _AliasLoader(importlib.abc.Loader):
    def __init__(self, target):
        self.target = target
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        sys.modules[module.__name__] = importlib.import_module(self.target)
    def get_code(self, fullname):
        return compile("import runpy\nrunpy.run_module("+repr(self.target)+", run_name='__main__', alter_sys=True)\n", '<兼容入口>', 'exec')
    def is_package(self, fullname):
        return False

class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ALIASES:
            return importlib.util.spec_from_loader(fullname, _AliasLoader(ALIASES[fullname]))
        return None

def install():
    if not any(isinstance(f, _AliasFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _AliasFinder())
