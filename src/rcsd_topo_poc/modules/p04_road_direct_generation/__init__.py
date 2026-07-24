"""SWSD-first Road direct-generation POC."""

from pathlib import Path

from .config import MilestoneOneConfig, MilestoneOneResult
from .directional_config import DirectionalRoadV2Config, DirectionalRoadV2Result
from .high_precision_config import HighPrecisionRoadV3Config, HighPrecisionRoadV3Result
from .road_config import MilestoneTwoConfig, MilestoneTwoResult
from .segment_first_config import SegmentFirstConfig
from .segment_first_types import SegmentFirstResult


def run_milestone_one(config: MilestoneOneConfig) -> MilestoneOneResult:
    """延迟加载数据流水线，避免 QGIS Python 被 GeoPandas 依赖阻断。"""
    from .pipeline import run_milestone_one as _run_milestone_one

    return _run_milestone_one(config)


def run_milestone_two(config: MilestoneTwoConfig) -> MilestoneTwoResult:
    """延迟加载第二里程碑，保持 P04 研究 callable 与正式入口隔离。"""
    from .road_pipeline import run_milestone_two as _run_milestone_two

    return _run_milestone_two(config)


def run_directional_road_v2(
    config: DirectionalRoadV2Config,
) -> DirectionalRoadV2Result:
    """运行隔离的方向级 Road V2，不改变 M2 或正式主链。"""
    from .directional_pipeline import run_directional_road_v2 as _run_directional_road_v2

    return _run_directional_road_v2(config)


def run_high_precision_road_v3(
    config: HighPrecisionRoadV3Config,
) -> HighPrecisionRoadV3Result:
    """运行隔离的高精骨架优先 V3，不改变 M2、V2 或正式主链。"""
    from .high_precision_pipeline import (
        run_high_precision_road_v3 as _run_high_precision_road_v3,
    )

    return _run_high_precision_road_v3(config)


def run_segment_first_road_direct(
    config: SegmentFirstConfig,
) -> SegmentFirstResult:
    """运行隔离的 Segment-first POC，不改变旧P04版本或T01-T12。"""
    from .segment_first_pipeline import (
        run_segment_first_road_direct as _run_segment_first_road_direct,
    )

    return _run_segment_first_road_direct(config)


def finalize_segment_first_run(
    output_dir: Path,
    acceptance_manifest_path: Path,
) -> SegmentFirstResult:
    """在外部验收证据齐全后将技术通过run晋级为最终passed。"""
    from .segment_first_finalize import (
        finalize_segment_first_run as _finalize_segment_first_run,
    )

    return _finalize_segment_first_run(output_dir, acceptance_manifest_path)


__all__ = [
    "MilestoneOneConfig",
    "MilestoneOneResult",
    "MilestoneTwoConfig",
    "MilestoneTwoResult",
    "DirectionalRoadV2Config",
    "DirectionalRoadV2Result",
    "HighPrecisionRoadV3Config",
    "HighPrecisionRoadV3Result",
    "SegmentFirstConfig",
    "SegmentFirstResult",
    "run_milestone_one",
    "run_milestone_two",
    "run_directional_road_v2",
    "run_high_precision_road_v3",
    "run_segment_first_road_direct",
    "finalize_segment_first_run",
]
