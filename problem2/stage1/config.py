"""构造与退火参数；保留旧算法对照字段兼容历史入口。"""
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class ComparisonConfig:
    constructions: int = 8
    vns_failures: int = 50
    tabu_stall: int = 5000
    sa_moves: int = 1000
    sa_cooling: float = 0.95
    sa_ratio: float = 0.0001
    sa_temperature_multiplier: float = 1.0
    generations: int = 5000
    population: int = 60
    archive_size: int = 12

    def check(self):
        if min(self.constructions, self.vns_failures, self.tabu_stall, self.sa_moves,
               self.generations, self.archive_size) < 1 or self.population < 6:
            raise ValueError('各迭代数量必须为正数，种群至少6个')
        if not 0 < self.sa_cooling < 1 or not 0 < self.sa_ratio < 1:
            raise ValueError('降温系数和最低温度比例必须在0到1之间')
        if not math.isfinite(self.sa_temperature_multiplier) or self.sa_temperature_multiplier <= 0:
            raise ValueError('初温倍率必须为有限正数')

