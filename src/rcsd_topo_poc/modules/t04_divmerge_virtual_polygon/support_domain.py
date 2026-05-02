from __future__ import annotations

from .support_domain_builder import _build_step5_unit_result, build_step5_support_domain
from .support_domain_models import T04Step5CaseResult, T04Step5UnitResult
from .support_domain_scenario import Step5SurfaceWindowConfig, derive_step5_surface_window_config
from .support_domain_windows import _build_fallback_support_strip, _build_terminal_window_domain

__all__ = [
    "Step5SurfaceWindowConfig",
    "T04Step5CaseResult",
    "T04Step5UnitResult",
    "build_step5_support_domain",
    "derive_step5_surface_window_config",
]
